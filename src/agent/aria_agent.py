"""ARIA Robot Navigation Agent — systematic exploration + spatial memory."""

# === Standard Library ===
import base64
import json
import re
import socket
import sys
import time
import urllib.request
from base64 import b64decode
from datetime import datetime
from math import atan2, degrees, hypot
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Callable, Dict, List, Optional, Tuple

# === Third-Party ===
import cv2
import numpy as np

# === Project ===
from src.agent.environment_graph import get_environment_graph
from src.agent.grid_explorer import GridExplorer
from src.agent.online_map import OnlineOccupancyGrid, parse_floor_extent
from src.agent.spatial_memory import SpatialMemory
from src.common.config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_VISION_MODEL,
    OLLAMA_REASONING_MODEL,
    OLLAMA_VISION_IMAGE_MAX_DIM,
    OLLAMA_VISION_NUM_PREDICT,
    OLLAMA_VISION_SAMPLE_INTERVAL,
    OLLAMA_VISION_TIMEOUT,
    USE_LLM,
    WEBOTS_WORLD_FILE,
    LOGS_PATH,
)
from src.common.types import AgentState
from src.mcp_server.server import call_tool
from src.perception.camera import Frame, FrameMetadata, get_camera_manager
from src.perception.object_detector import get_detector

# === Motion Constants ===
# Motion is now closed-loop in the Webots controller (it drives until the GPS
# distance / compass angle goal is met, then stops the wheels itself), so the
# agent no longer sleeps to time a motion.  CYCLE_INTERVAL is just a small floor
# between decision cycles.
CYCLE_INTERVAL = 0.4        # seconds — minimum spacing between decision cycles
MOVE_VELOCITY = 4.0         # wheel velocity (rad/s) for forward motion
BACKUP_VELOCITY = -3.0      # wheel velocity (rad/s) for reversing
TURN_VELOCITY = 2.0         # differential wheel velocity (rad/s) for turns
MOVE_DISTANCE = 0.6         # metres travelled per move_forward (closed-loop)
BACKUP_DISTANCE = 0.4       # metres travelled per back_up (closed-loop)
MOVE_STEP_CAP = 120         # sim-step safety cap for a single move
TURN_STEP_CAP = 160         # sim-step safety cap for a single turn

# Proximity threshold: Pioneer 3DX sonar values 0=no reading, ~800=obstacle ~0.5m away.
# Break_room walls 2m away read ~600–650; raise threshold so walls don't count as blocked.
OBSTACLE_THRESH = 800
CRITICAL_OBSTACLE_THRESH = 970

# === Target pursuit (find / approach) ===
APPROACH_DONE_FRAC = 0.55    # target bbox height ≥ this fraction of frame → close enough
APPROACH_CENTER_TOL = 0.30   # |image x-error| within this → drive straight at the target
PURSUIT_LOST_LIMIT = 6       # steps to keep re-acquiring after losing sight of the target

# How many steps to skip LLM after a connection failure before retrying
_OLLAMA_RETRY_INTERVAL = 10

# === Global Stop Signal ===
_STOP_SIGNAL = False


def set_stop_signal(value: bool) -> None:
    global _STOP_SIGNAL
    _STOP_SIGNAL = value


def get_stop_signal() -> bool:
    return _STOP_SIGNAL


# === Target Keyword Map ===
_TARGET_KEYWORDS: Dict[str, str] = {
    "kitchen": "kitchen",
    "bedroom": "bedroom",
    "bathroom": "bathroom",
    "living room": "living room",
    "lounge": "living room",
    "door": "door",
    "chair": "chair",
    "table": "table",
    "cup": "cup",
    "bottle": "bottle",
    "laptop": "laptop",
    "person": "person",
    "human": "person",
    "extinguisher": "fire extinguisher",
    "fire extinguisher": "fire extinguisher",
    "fire-extinguisher": "fire extinguisher",
    "dog": "dog",
    "cat": "cat",
    "duck": "duck",
    "ball": "sports ball",
    "soccer": "sports ball",
}

_GOAL_STOPWORDS = {
    "find", "the", "a", "an", "and", "go", "towards", "toward", "to", "it",
    "stop", "away", "from", "centimeter", "centimeters", "cm", "meter", "meters",
    "near", "at", "search", "for", "object", "target", "approach",
    # verbs / fillers that should never be treated as the object
    "locate", "look", "where", "is", "spot", "reach", "come", "walk", "get",
    "drive", "head", "navigate", "move", "please", "me", "this", "that", "of",
    "explore", "room", "around", "then", "once", "you", "your", "robot",
}

# === System Prompt ===
_SYSTEM_PROMPT = """You are ARIA, an autonomous robot exploring a furnished room.

SENSING:
- Camera gives YOLO-annotated image with bounding boxes and class labels
- 180° proximity sensors detect obstacles (value > 800 = obstacle within ~0.5m)
- GPS position and compass heading are available

ACTIONS (use EXACTLY one of these):
move_forward, turn_left_90, turn_right_90, turn_around, stop, back_up

SAFETY RULES:
1. NEVER choose move_forward if front_blocked=true
2. If target is visible in the image, choose stop

RESPONSE FORMAT (compact JSON only, no markdown, no thinking):
{"action": "<action>", "reasoning": "<one sentence>", "target_found": <true|false>, "target_visible_confidence": <0.0-1.0>, "target_direction": "<left|right|center|not_visible>", "target_bbox": [x1,y1,x2,y2] or null}
"""


# === Helpers ===

_APPROACH_PHRASES = (
    "approach", "go to", "goto", "go near", "navigate to", "navigate towards",
    "reach", "come to", "move to", "move towards", "walk to", "get to",
    "drive to", "head to", "head towards", "go towards", "go up to",
)


def _wants_approach(goal: str) -> bool:
    """True if the goal asks the robot to drive to the target (vs just find it).
    'find the dog and approach it' → True;  'find the dog' → False (stop on sight)."""
    g = goal.lower()
    return any(p in g for p in _APPROACH_PHRASES)


def _extract_target(goal: str) -> str:
    goal_lower = goal.lower()
    # whole-word match so "cat" doesn't fire inside "lo-cat-e", etc.
    for keyword, target in _TARGET_KEYWORDS.items():
        if re.search(rf"\b{re.escape(keyword)}\b", goal_lower):
            return target
    words = re.findall(r"[a-zA-Z][a-zA-Z-]*", goal_lower)
    candidates = [w for w in words if w not in _GOAL_STOPWORDS and not w.isdigit()]
    # the head noun is usually last ("wooden BOX", "red BALL") → take the last
    return candidates[-1] if candidates else "object"


# COCO four-legged-animal classes.  YOLOv8 frequently flips between these on a
# single rendered animal model (the Webots dog reads as "horse" up close and
# "dog"/"sheep" at range), so when the target is one of them we accept any of
# them as the target.  In these single-animal test worlds that's the right call;
# it's what makes "find the dog and approach it" robust to the misclassification
# the detector actually produces.
_COCO_QUADRUPEDS = {"dog", "cat", "horse", "sheep", "cow", "bear", "elephant", "zebra", "giraffe"}


def _target_aliases(target: str) -> set:
    t = target.lower().strip()
    aliases = {t}
    if t in _COCO_QUADRUPEDS:
        aliases.update(_COCO_QUADRUPEDS)
    if t == "fire extinguisher":
        aliases.update({"extinguisher"})
    if t == "table":
        aliases.update({"dining table"})
    if t == "plant":
        aliases.update({"potted plant"})
    if t in ("sofa", "couch"):
        aliases.update({"sofa", "couch"})
    if t in ("tv", "television", "monitor"):
        aliases.update({"tv", "television", "monitor"})
    if t in ("duck", "rubber duck"):
        aliases.update({"duck", "rubber duck"})
    if t in ("box", "wooden box", "cardboard box"):
        aliases.update({"box", "wooden box", "cardboard box", "carton"})
    if t in ("ball", "sports ball", "soccer ball"):
        aliases.update({"sports ball", "ball", "soccer ball"})
    return aliases


def _detection_to_dict(d: Any) -> Dict[str, Any]:
    x1, y1, x2, y2 = d.bbox
    return {
        "class_name": d.class_name,
        "confidence": round(float(d.confidence), 3),
        "bbox": [round(float(x1), 1), round(float(y1), 1),
                 round(float(x2), 1), round(float(y2), 1)],
        "center": [round(float(d.center[0]), 1), round(float(d.center[1]), 1)],
        "class_id": int(d.class_id),
    }


def _sensor_index(name: str) -> Optional[int]:
    m = re.search(r"(\d+)$", name)
    return int(m.group(1)) if m else None


def _proximity_scan(proximity: Dict[str, float]) -> Dict[str, Any]:
    """Summarise 180° obstacle scan.  Higher value = closer obstacle."""
    items = [(k, float(v), _sensor_index(k)) for k, v in proximity.items() if float(v) >= 0]
    if not items:
        return {
            "front_blocked": False, "critical": False,
            "front": 0.0, "left": 0.0, "right": 0.0,
            "clearer_turn": "turn_left_45",
        }

    indexed = [(k, v, i) for k, v, i in items if i is not None]
    values = [v for _k, v, _i in items]
    if indexed:
        n = max(i for _k, _v, i in indexed) + 1
        front_idx = {0, 1, 2, max(0, n - 1), max(0, n - 2)}
        left_idx = {i for i in range(n // 2, n)}
        right_idx = {i for i in range(0, max(1, n // 2))}
        front_vals = [v for _k, v, i in indexed if i in front_idx]
        left_vals = [v for _k, v, i in indexed if i in left_idx]
        right_vals = [v for _k, v, i in indexed if i in right_idx]
    else:
        front_vals = left_vals = right_vals = values

    front = max(front_vals or values)
    left = max(left_vals or [0.0])
    right = max(right_vals or [0.0])
    clearer_turn = "turn_left_45" if left < right else "turn_right_45"
    return {
        "front_blocked": front > OBSTACLE_THRESH,
        "critical": max(values) > CRITICAL_OBSTACLE_THRESH,
        "front": front,
        "left": left,
        "right": right,
        "max": max(values),
        "clearer_turn": clearer_turn,
    }


def _is_white_wall_view(frame_bgr: Optional[np.ndarray]) -> bool:
    if frame_bgr is None or frame_bgr.size == 0:
        return False
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    brightness = float(np.mean(hsv[:, :, 2]))
    saturation = float(np.mean(hsv[:, :, 1]))
    texture = float(np.std(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)))
    return brightness > 185 and saturation < 35 and texture < 28


def _safe_fallback_action(scan: Dict[str, Any], white_wall: bool) -> Tuple[str, str]:
    """Sensor-only fallback when LLM is unavailable."""
    if scan.get("critical") or (white_wall and scan.get("front", 0) > OBSTACLE_THRESH * 0.7):
        turn = scan.get("clearer_turn", "turn_left_45")
        return f"back_up_turn_{turn.split('_')[1]}", "critical proximity — backing out"
    if scan.get("front_blocked"):
        return scan.get("clearer_turn", "turn_left_45"), "front blocked — turning to clearer side"
    return "move_forward", "path clear — advancing"


def _decode_camera_frame(camera_data: Dict[str, Any]) -> Optional[np.ndarray]:
    encoding = camera_data.get("encoding", "bgra8_base64")
    raw_b64 = camera_data.get("data")
    width = camera_data.get("width", 320)
    height = camera_data.get("height", 240)
    if not raw_b64:
        return None
    try:
        image_bytes = b64decode(raw_b64)
        if encoding == "bgra8_base64":
            frame_bgra = np.frombuffer(image_bytes, dtype=np.uint8).reshape((height, width, 4))
            frame_bgr = frame_bgra[:, :, :3].copy()
        else:
            nparr = np.frombuffer(image_bytes, np.uint8)
            frame_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        frame_bgr = cv2.rotate(frame_bgr, cv2.ROTATE_180)
        return frame_bgr
    except Exception as e:
        print(f"[ARIA] Camera decode error: {e}")
        return None


def _frame_to_jpeg_b64(frame_bgr: np.ndarray, quality: int = 90) -> Optional[str]:
    try:
        h, w = frame_bgr.shape[:2]
        max_dim = max(32, OLLAMA_VISION_IMAGE_MAX_DIM)
        scale = min(1.0, max_dim / max(h, w))
        if scale < 1.0:
            frame_bgr = cv2.resize(
                frame_bgr, (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_AREA,
            )
        ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            return None
        return base64.b64encode(buf.tobytes()).decode("utf-8")
    except Exception:
        return None


def _heading_from_orientation(orientation: List[float]) -> float:
    """Convert a Webots compass reading to an absolute heading in degrees.

    The world is Z-up (ENU), so the compass north vector lies in the X-Y plane
    and its Z component is ~0 — heading comes from the X and Y components only.

        heading = atan2(bx, by)       0° = +X (east), 90° = +Y (north)

    This convention was derived EMPIRICALLY from the GPS displacement seen on
    every move_forward (a "move" at heading h always advanced along bearing h),
    and it matches GridExplorer.get_nav_action's bearing = atan2(dy, dx).

    NOTE: if a future run shows the robot driving 90° off from where it aims,
    the compass axis order differs for your build — this is the single line to
    re-derive (it depends on WorldInfo.northDirection / coordinate system).
    """
    if len(orientation) < 2:
        return 0.0
    bx, by = orientation[0], orientation[1]
    return degrees(atan2(bx, by))


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if start is None:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start: i + 1])
                except json.JSONDecodeError:
                    start = None
    return None


def _ollama_reachable(timeout: float = 1.5) -> bool:
    """Cheap TCP connect test so an unreachable Ollama costs ~1s, not a 35s
    HTTP read timeout (×2 calls)."""
    try:
        u = urlparse(OLLAMA_BASE_URL)
        host = u.hostname or "localhost"
        port = u.port or 11434
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _query_vision_model(jpeg_b64: Optional[str], user_prompt: str) -> str:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    user_msg: Dict[str, Any] = {"role": "user", "content": user_prompt}
    if jpeg_b64:
        user_msg["images"] = [jpeg_b64]
    payload = {
        "model": OLLAMA_VISION_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": "Describe the image briefly and accurately."},
            user_msg,
        ],
        "options": {
            "temperature": 0.1,
            "num_predict": OLLAMA_VISION_NUM_PREDICT,
            "num_ctx": 2048,
        },
        "keep_alive": "10m",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=OLLAMA_VISION_TIMEOUT) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    text = (raw.get("message", {}).get("content") or raw.get("response") or "").strip()
    if not text:
        raise RuntimeError(f"empty response from {OLLAMA_VISION_MODEL}")
    return text


def _query_reasoning_model(system_prompt: str, user_prompt: str) -> str:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": OLLAMA_REASONING_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": {
            "temperature": 0.1,
            "num_predict": OLLAMA_VISION_NUM_PREDICT,
            "num_ctx": 2048,
        },
        "keep_alive": "10m",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=OLLAMA_VISION_TIMEOUT) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    text = (raw.get("message", {}).get("content") or raw.get("response") or "").strip()
    if not text:
        raise RuntimeError(f"empty response from {OLLAMA_REASONING_MODEL}")
    return text


def _fwd(distance: float = MOVE_DISTANCE, velocity: float = MOVE_VELOCITY) -> Dict[str, Any]:
    res = call_tool("execute_action", {
        "action_type": "move", "velocity": velocity,
        "target_distance": distance, "steps": MOVE_STEP_CAP,
    })
    return res.get("feedback", {}) if isinstance(res, dict) else {}


def _turn(degrees_: float, direction: int) -> Dict[str, Any]:
    """direction: +1 = left/CCW, -1 = right/CW.  The step cap scales with the
    angle so a wedged turn that can't complete gives up quickly (~1.5× the
    expected steps) instead of spinning for the full fixed cap."""
    cap = max(25, int(abs(degrees_) * 1.1))
    res = call_tool("execute_action", {
        "action_type": "turn", "angular_velocity": direction * TURN_VELOCITY,
        "target_angle": abs(degrees_), "steps": cap,
    })
    return res.get("feedback", {}) if isinstance(res, dict) else {}


def _execute_motion(action: str) -> Dict[str, Any]:
    """Issue one closed-loop motion. Each call blocks until the controller has
    reached the sensor goal and stopped the wheels — no agent-side sleeps.

    Returns the controller feedback for the *primary* motion (distance_traveled,
    degrees_turned, reached_target, …) so the caller can log whether the robot
    actually translated/rotated as commanded."""
    if action == "move_forward":
        return _fwd()
    elif action == "turn_left_45":
        return _turn(45, +1)
    elif action == "turn_right_45":
        return _turn(45, -1)
    elif action == "turn_left_90":
        return _turn(90, +1)
    elif action == "turn_right_90":
        return _turn(90, -1)
    elif action == "turn_around":
        return _turn(180, +1)
    elif action == "back_up":
        return _fwd(distance=BACKUP_DISTANCE, velocity=BACKUP_VELOCITY)
    elif action in ("back_up_turn", "back_up_turn_left"):
        fb = _fwd(distance=BACKUP_DISTANCE, velocity=BACKUP_VELOCITY)
        _turn(45, +1)
        return fb
    elif action == "back_up_turn_right":
        fb = _fwd(distance=BACKUP_DISTANCE, velocity=BACKUP_VELOCITY)
        _turn(45, -1)
        return fb
    elif action == "stop":
        call_tool("stop", {})
    return {}


def _emit(callback: Optional[Callable], event: Dict[str, Any]) -> None:
    if callback is None:
        return
    try:
        callback(event)
    except Exception as e:
        print(f"[ARIA] Event callback error: {e}")


# =========================================================================
# Per-run logging — every run is captured to logs/run_<timestamp>.log
# =========================================================================

class _TimestampedFile:
    """Wraps a file so each complete line is prefixed with a wall-clock time —
    makes it obvious from the log exactly which step/section was slow."""

    def __init__(self, f):
        self._f = f
        self._buf = ""

    def write(self, data: str) -> int:
        self._buf += data
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            # Trim the timestamp's microseconds to milliseconds (3 digits) — the
            # slice must apply to the TIMESTAMP, not the whole line.  The old
            # `f"...{line}\n"[:-4]` chopped the last 4 chars off every log line
            # (e.g. "conf=0.41" → "conf=0", "turn_right_45" → "turn_right"),
            # silently corrupting the logs.
            ts = f"{datetime.now():%H:%M:%S.%f}"[:-3]
            self._f.write(f"{ts} {line}\n")
        return len(data)

    def flush(self):
        self._f.flush()


class _Tee:
    """Write to several streams at once (console + log file)."""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data: str) -> int:
        for s in self._streams:
            try:
                s.write(data)
            except Exception:
                pass
        return len(data)

    def flush(self):
        for s in self._streams:
            try:
                s.flush()
            except Exception:
                pass


def _open_run_log(goal: str):
    try:
        LOGS_PATH.mkdir(parents=True, exist_ok=True)
        path = LOGS_PATH / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"
        f = open(path, "w", encoding="utf-8")
        f.write(f"# ARIA run log — goal={goal!r} — {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        f.flush()
        print(f"[ARIA] Logging this run to {path}")
        return f
    except Exception as e:
        print(f"[ARIA] Could not open run log: {e}")
        return None


# =========================================================================
# Main Agent
# =========================================================================

def run_aria_agent(
    goal: str,
    max_steps: int = 100,
    model: str = OLLAMA_MODEL,
    event_callback: Optional[Callable[[Dict], None]] = None,
) -> AgentState:
    """Public entry: tees all output to a per-run log file, then runs the
    agent.  stdout is always restored, even on error."""
    orig_stdout = sys.stdout
    logf = _open_run_log(goal)
    if logf is not None:
        sys.stdout = _Tee(orig_stdout, _TimestampedFile(logf))
    try:
        return _run_aria_agent_impl(goal, max_steps, model, event_callback)
    except Exception:
        # Make crashes loud — an uncaught error in the worker thread would
        # otherwise be silently swallowed by the asyncio task and look like a hang.
        import traceback
        print("\n[ARIA] FATAL: agent crashed —")
        traceback.print_exc()
        if event_callback:
            try:
                event_callback({"type": "error", "step": 0,
                                "plan": "agent crashed (see console/log)"})
            except Exception:
                pass
        raise
    finally:
        sys.stdout = orig_stdout
        if logf is not None:
            try:
                logf.close()
            except Exception:
                pass


def _run_aria_agent_impl(
    goal: str,
    max_steps: int = 100,
    model: str = OLLAMA_MODEL,
    event_callback: Optional[Callable[[Dict], None]] = None,
) -> AgentState:

    target = _extract_target(goal)
    target_aliases = _target_aliases(target)
    approach_mode = _wants_approach(goal)   # drive to target vs just stop on sight
    camera = get_camera_manager()
    detector = get_detector()
    env_graph = get_environment_graph()

    # Open-vocabulary detectors (YOLO-World) can find objects outside the 80
    # COCO classes (duck, box, …) — tell it what to look for.  No-op for the
    # standard COCO models, which only ever see their fixed class list.
    if getattr(detector, "is_open_vocab", False):
        detector.set_classes(sorted(target_aliases | {
            "dog", "cat", "sports ball", "bottle", "duck", "rubber duck",
            "box", "wooden box", "cardboard box", "chair", "person", "potted plant",
        }))

    # --- Ask the simulator which world is actually loaded -----------------
    # The agent only talks to Webots over TCP and otherwise can't know which
    # .wbt is open.  The controller now reports it (state["world"]); we use that
    # to key spatial memory and to read the correct floor bounds, instead of
    # blindly trusting WEBOTS_WORLD_FILE (which caused the empty_room run to
    # load break_room's memory and chase a dog that wasn't there).
    detected_world: Optional[str] = None
    try:
        _probe = call_tool("get_state", {"include_camera": False})
        if _probe.get("success"):
            _pstate = _probe.get("state", {}) or {}
            detected_world = (_pstate.get("world") or "").strip() or None
            print(f"[ARIA] Webots reports world: {detected_world!r}  "
                  f"(sources: {_pstate.get('world_sources', {})})")
    except Exception as e:
        print(f"[ARIA] World probe failed: {e}")

    # Resolve the .wbt path to parse for floor bounds: prefer a file matching the
    # reported world in the same worlds directory; else fall back to config.
    world_file = WEBOTS_WORLD_FILE
    if detected_world:
        _candidate = Path(WEBOTS_WORLD_FILE).parent / f"{detected_world}.wbt"
        if _candidate.exists():
            world_file = str(_candidate)
        elif Path(WEBOTS_WORLD_FILE).stem != detected_world:
            print(f"[ARIA] WARNING: Webots is running '{detected_world}' but no "
                  f"matching .wbt found next to {WEBOTS_WORLD_FILE}; floor bounds "
                  f"may be wrong. Set WEBOTS_WORLD_FILE to the loaded world.")
    print(f"[ARIA] Using world file for floor bounds: {world_file}")

    # --- Autonomous exploration infrastructure ---
    # GridExplorer is kept ONLY for its map-agnostic helpers (heading→turn
    # action and the 360° scan state machine) — its lattice is not used.
    grid = GridExplorer(world_file, grid_spacing=1.5)
    # The robot discovers the room itself: a live occupancy grid built from the
    # Lidar, driven by frontier exploration.  No wall positions are read from
    # the .wbt — only the floor bounding box, to size the grid's frame.
    omap = OnlineOccupancyGrid(
        *parse_floor_extent(world_file), resolution=0.10, robot_radius=0.25
    )
    spatial_mem = SpatialMemory(world=detected_world)

    def _plan_action(cur_xy, goal_xy):
        """Heading-aware action toward goal_xy, routed around DISCOVERED
        obstacles via the live occupancy map.  Returns (action, dist_to_goal)."""
        d = hypot(goal_xy[0] - cur_xy[0], goal_xy[1] - cur_xy[1])
        if d <= grid.ARRIVAL_RADIUS:
            return "arrived", d
        carrot = omap.next_step_toward(cur_xy[0], cur_xy[1], tuple(goal_xy), lookahead=0.7)
        steer_to = carrot if carrot is not None else tuple(goal_xy)
        action, _sub = grid.get_nav_action(cur_xy, steer_to, heading_deg)
        if action == "arrived":          # close to carrot but not the goal → push on
            action = "move_forward"
        return action, d

    # Current exploration target (a frontier — edge of the unknown)
    active_frontier: Optional[Tuple[float, float]] = None
    no_frontier_count: int = 0          # consecutive steps with no frontier → done

    # Progress watchdog: if we can't get meaningfully closer to the active
    # frontier for a while, it's blocked — blacklist it and pick another.
    best_dist_to_wp: float = float("inf")
    no_progress_count: int = 0
    NO_PROGRESS_LIMIT = 6            # steps without getting closer → abandon
    PROGRESS_EPS = 0.15             # metres of improvement that counts as progress

    # Are we doing a 360° scan (look-around for YOLO + fill the map)?
    scanning = False

    # Target pursuit state (set once the target is seen by YOLO)
    pursuing = False
    pursuit_lost = 0
    last_seen_err = 0.0          # last image x-error sign, for re-acquiring

    # Ollama connectivity tracking (fail-fast: skip LLM when offline)
    ollama_online = True
    ollama_skip_until_step = 0   # re-try every _OLLAMA_RETRY_INTERVAL steps
    # LLM is an optional refinement layer. YOLO (every step) is the real target
    # detector, so we only pay for the slow vision+reasoning calls periodically
    # instead of on every single step.
    last_llm_ts = 0.0

    state = AgentState(goal=goal, step_count=0, success=False)
    objects_seen: List[str] = []

    print(f"\n[ARIA] Goal: {goal}")
    print(f"[ARIA] Target: {target}  aliases: {sorted(target_aliases)}  "
          f"mode: {'APPROACH (drive to it)' if approach_mode else 'FIND (stop on sight)'}")
    print(f"[ARIA] Model: {model}")
    print(f"[ARIA] Spatial memory: {spatial_mem.summary()}")

    _emit(event_callback, {"type": "start", "step": 0, "goal": goal})

    for step in range(1, max_steps + 1):
        if get_stop_signal():
            print(f"\n[ARIA] STOP SIGNAL RECEIVED at step {step}")
            _execute_motion("stop")
            call_tool("stop", {})
            break

        cycle_start = time.time()
        state.step_count = step

        print(f"\n{'='*60}")
        print(f"[ARIA] Step {step}/{max_steps}  |  goal: {goal}")
        print(f"{'='*60}")

        # ============================================================
        # SENSE
        # ============================================================
        _emit(event_callback, {"type": "sensing", "step": step, "goal": goal})

        robot_state_raw: Dict[str, Any] = {}
        try:
            result = call_tool("get_state", {"include_camera": True})
            if result.get("success") or "state" in result:
                robot_state_raw = result.get("state", {})
            else:
                print(f"[ARIA] get_state error: {result.get('error', 'unknown')}")
        except Exception as e:
            print(f"[ARIA] get_state exception: {e}")
            state.error = str(e)

        position = robot_state_raw.get("position", [0.0, 0.0, 0.0])
        orientation = robot_state_raw.get("orientation", [0.0, 0.0, 0.0])
        proximity: Dict[str, float] = robot_state_raw.get("proximity", {})
        timestamp = robot_state_raw.get("timestamp", time.time())
        camera_data = robot_state_raw.get("camera", {})

        # Closed-loop motions fully settle and stop the wheels before the
        # controller returns, so the compass read at the start of each cycle is
        # accurate — no dead-reckoning / 1-step-lag compensation is needed.
        heading_deg = _heading_from_orientation(orientation)
        scan_result = _proximity_scan(proximity)
        front_blocked = bool(scan_result["front_blocked"])
        pos_xy = (float(position[0]), float(position[1]))

        # Fuse this step's Lidar scan into the live occupancy map (the robot's
        # only source of obstacle knowledge — discovered, never pre-loaded).
        lidar_data = robot_state_raw.get("lidar")
        if lidar_data and (pos_xy[0] != 0.0 or pos_xy[1] != 0.0 or step == 1):
            omap.update_lidar(pos_xy[0], pos_xy[1], heading_deg, lidar_data)

        print(
            f"[ARIA] Pos=({pos_xy[0]:.2f},{pos_xy[1]:.2f}) hdg={heading_deg:.0f}°  "
            f"front={scan_result['front']:.0f} left={scan_result['left']:.0f} "
            f"right={scan_result['right']:.0f}  blocked={front_blocked}"
        )

        # ============================================================
        # DECODE CAMERA + YOLO
        # ============================================================
        frame_bgr: Optional[np.ndarray] = None
        if camera_data:
            frame_bgr = _decode_camera_frame(camera_data)

        if frame_bgr is not None:
            meta = FrameMetadata(timestamp=float(timestamp))
            pose_dict = {"x": position[0], "y": position[1],
                         "z": position[2], "rotation": heading_deg}
            camera.last_frame = Frame(data=frame_bgr, metadata=meta, pose=pose_dict)
        else:
            print("[ARIA] No camera frame this cycle")

        white_wall = _is_white_wall_view(frame_bgr)

        detections = []
        target_found_yolo = False
        annotated_frame = frame_bgr
        if frame_bgr is not None:
            try:
                detections = detector.detect(frame_bgr)
                annotated_frame = detector.visualize_detections(frame_bgr, detections)
                detected_names = [d.class_name for d in detections]
                for name in detected_names:
                    if name not in objects_seen:
                        objects_seen.append(name)
                target_found_yolo = any(
                    d.class_name.lower() in target_aliases for d in detections
                )
                print("[ARIA] YOLO:")
                for d in detections[:10]:
                    print(f"  {d.class_name} conf={d.confidence:.2f}")
                if not detections:
                    print("  (none)")

                # Record every detection with current GPS position to spatial memory
                if position[0] != 0.0 or position[1] != 0.0:
                    for d in detections:
                        spatial_mem.record(
                            d.class_name.lower(),
                            position[0], position[1],
                            float(d.confidence),
                        )
            except Exception as e:
                print(f"[ARIA] YOLO error: {e}")

        detection_dicts = [_detection_to_dict(d) for d in detections]

        # --- Locate the target in the frame (for find/approach decisions) ---
        target_det = None
        for d in detections:
            if d.class_name.lower() in target_aliases:
                if target_det is None or d.confidence > target_det.confidence:
                    target_det = d
        target_err = 0.0      # normalized horizontal offset of target in image, [-1..1]
        target_frac = 0.0     # target bbox height / frame height (proximity proxy)
        if target_det is not None and frame_bgr is not None:
            fh, fw = frame_bgr.shape[0], frame_bgr.shape[1]
            x1, y1, x2, y2 = target_det.bbox
            target_err = (target_det.center[0] - fw / 2.0) / (fw / 2.0)
            target_frac = (y2 - y1) / float(fh)

        t_sense = time.time()

        # ============================================================
        # DETERMINE BASE NAVIGATION ACTION
        # Deliberate cycle:  LOOK AROUND (360° in 45° steps) → pick frontier →
        # DRIVE to it → arrive/blocked → LOOK AROUND again.  YOLO + Lidar run at
        # every orientation during the scan, so the robot "rotates, identifies,
        # then acts" instead of spinning reactively.
        # ============================================================
        nav_action = None
        nav_reason = ""
        target_done = False        # True when we should STOP and succeed on the target
        exploration_done = False   # True when all reachable space is explored (give up)

        # ============================================================
        # TARGET PURSUIT  (highest priority — overrides scan/explore/LLM)
        # ============================================================
        if target_det is not None:
            pursuing = True
            pursuit_lost = 0
            last_seen_err = target_err
            scanning = False                      # abort any scan — we found it
            tconf = float(getattr(target_det, "confidence", 0.0))
            if not approach_mode:
                nav_action, target_done = "stop", True
                nav_reason = "found — stop & look"
            elif target_frac >= APPROACH_DONE_FRAC or scan_result.get("critical"):
                nav_action, target_done = "stop", True
                nav_reason = "reached (close enough)"
            elif abs(target_err) > APPROACH_CENTER_TOL:
                # Camera image is rotated 180°, so image-right = robot's LEFT.
                # If approach veers AWAY from the target, flip this one comparison
                # (target_err > 0  ->  < 0).  The log line below makes the
                # relationship explicit so the right fix is obvious.
                nav_action = "turn_left_45" if target_err > 0 else "turn_right_45"
                nav_reason = "centering"
            else:
                nav_action = "move_forward"
                nav_reason = "centered — advancing"
            # ONE consistent line per pursuit step: where the dog is in the image
            # (x-err sign + side), how big it is (bbox% = distance-decreasing proxy),
            # detection confidence, and the chosen action.  Watch bbox% grow and
            # |x-err| shrink across steps; if the robot turns AWAY from the side
            # shown here, flip the comparison marked above.
            side = "img-RIGHT" if target_err > 0 else "img-LEFT"
            print(f"[ARIA] TARGET[{'approach' if approach_mode else 'find'}] "
                  f"→ {nav_action} | {nav_reason} | {target} {side} "
                  f"x-err={target_err:+.2f} bbox={target_frac:.0%} conf={tconf:.2f} "
                  f"(YOLO saw '{target_det.class_name}')")

        elif pursuing:
            # Lost sight this step — turn back toward where it was to re-acquire.
            pursuit_lost += 1
            if pursuit_lost > PURSUIT_LOST_LIMIT:
                pursuing = False
                print(f"[ARIA] Lost '{target}' — resuming exploration")
            else:
                nav_action = "turn_left_45" if last_seen_err > 0 else "turn_right_45"
                nav_reason = f"re-acquiring '{target}' (lost {pursuit_lost}/{PURSUIT_LOST_LIMIT})"
                print(f"[ARIA] {nav_reason}")

        # ============================================================
        # EXPLORATION  (only runs when not pursuing a target)
        # ============================================================
        if nav_action is not None:
            pass
        elif scanning:
            # Mid-scan: keep turning 45°; on completion pick a frontier from the
            # freshly-built map.
            nav_action = grid.scan_step()
            nav_reason = f"360° scan ({omap.stats()['unknown']} cells unknown)"
            if grid.scan_done():
                scanning = False
                active_frontier = omap.nearest_frontier(pos_xy[0], pos_xy[1])
                best_dist_to_wp = float("inf")
                no_progress_count = 0
                if active_frontier is not None:
                    no_frontier_count = 0
                    print(f"[ARIA] Scan done → frontier "
                          f"({active_frontier[0]:.1f},{active_frontier[1]:.1f})  map: {omap.stats()}")
                else:
                    print(f"[ARIA] Scan done → no reachable frontier  map: {omap.stats()}")

        # NOTE: we deliberately do NOT blind-drive to a remembered coordinate
        # here.  Spatial memory is recorded for analysis and the UI, but it must
        # never replace live exploration: (a) it defeats the design goal of
        # discovering the room from sensors, and (b) memory is keyed by the
        # configured world file, which can differ from the world Webots actually
        # loaded — chasing a stale coordinate from another world is what made the
        # robot spin in place.  YOLO pursuit (above) handles the target the
        # moment it is actually seen; until then we always explore.

        elif active_frontier is None:
            # No current goal → look around (scan), then a frontier is chosen.
            no_frontier_count += 1
            if no_frontier_count >= 2:
                print(f"[ARIA] EXPLORATION COMPLETE — '{target}' not found  {omap.stats()}")
                nav_action = "stop"
                nav_reason = "explored all reachable space, target not found"
                exploration_done = True   # terminate: nothing left to explore
            else:
                scanning = True
                grid.start_scan()
                nav_action = grid.scan_step()
                nav_reason = "360° look-around to choose next frontier"
                print("[ARIA] Starting 360° look-around")

        else:
            # Drive toward the frontier chosen after the last scan.
            nav_action, dist = _plan_action(pos_xy, active_frontier)

            if dist < best_dist_to_wp - PROGRESS_EPS:
                best_dist_to_wp = dist
                no_progress_count = 0
            else:
                no_progress_count += 1

            if nav_action == "arrived":
                print(f"[ARIA] Reached frontier ({active_frontier[0]:.1f},{active_frontier[1]:.1f}) "
                      f"— will re-scan")
                active_frontier = None        # → triggers a fresh look-around next step
                nav_action = "move_forward"
                nav_reason = "reached frontier"
            elif no_progress_count >= NO_PROGRESS_LIMIT:
                print(f"[ARIA] Frontier ({active_frontier[0]:.1f},{active_frontier[1]:.1f}) "
                      f"blocked — blacklisting, will re-scan")
                omap.blacklist(*active_frontier)
                active_frontier = None
                nav_action = "turn_around"
                nav_reason = "blocked frontier — turning away"
            else:
                nav_reason = (
                    f"→ frontier ({active_frontier[0]:.1f},{active_frontier[1]:.1f}) "
                    f"dist={dist:.1f}m → {nav_action}  "
                    f"[progress {no_progress_count}/{NO_PROGRESS_LIMIT}]"
                )
                print(f"[ARIA] Explore: {nav_reason}")

        # Sensor-safe fallback for when nav_action isn't set
        if 'nav_action' not in dir() or nav_action is None:
            nav_action, nav_reason = _safe_fallback_action(scan_result, white_wall)

        t_nav = time.time()

        # ============================================================
        # LLM QUERY (optional refinement — used when Ollama is online)
        # ============================================================
        jpeg_b64: Optional[str] = None
        vlm_description = ""
        if annotated_frame is not None:
            jpeg_b64 = _frame_to_jpeg_b64(annotated_frame)

        llm_action: Optional[str] = None
        llm_conf = 0.0
        llm_target_found = False
        llm_target_direction = "not_visible"
        llm_target_bbox = None

        _emit(event_callback, {"type": "vlm_query", "step": step, "goal": goal})

        # The LLM is an optional refinement. Skip it on step 1 (so the robot
        # starts moving immediately) and throttle to once per
        # OLLAMA_VISION_SAMPLE_INTERVAL seconds. YOLO runs every step regardless.
        reachable = ollama_online or (step >= ollama_skip_until_step)
        due = (cycle_start - last_llm_ts) >= OLLAMA_VISION_SAMPLE_INTERVAL
        attempt_llm = USE_LLM and reachable and due and step > 1

        # Fast TCP pre-check: an unreachable Ollama now costs ~1s, not 2×35s.
        if attempt_llm and not _ollama_reachable():
            print("[ARIA] Ollama unreachable (fast check) — skipping LLM "
                  f"for {_OLLAMA_RETRY_INTERVAL} steps")
            ollama_online = False
            ollama_skip_until_step = step + _OLLAMA_RETRY_INTERVAL
            attempt_llm = False

        if attempt_llm:
            last_llm_ts = cycle_start
            try:
                if jpeg_b64:
                    try:
                        vlm_description = _query_vision_model(
                            jpeg_b64,
                            f"Describe this robot camera image briefly (2-3 sentences). "
                            f"Is a '{target}' visible?",
                        )
                        print(f"[ARIA] Vision: {vlm_description[:120]}")
                        _emit(event_callback, {
                            "type": "vision", "step": step,
                            "description": vlm_description,
                        })
                    except Exception as e:
                        print(f"[ARIA] Vision model error: {type(e).__name__}: {e}")

                user_prompt = (
                    f"Goal: find '{target}'.  Current navigation plan: {nav_reason}\n"
                    f"Front blocked: {front_blocked}.  "
                    f"Proximity front={scan_result['front']:.0f} "
                    f"left={scan_result['left']:.0f} right={scan_result['right']:.0f}\n"
                    f"YOLO detections: {[d['class_name'] for d in detection_dicts[:10]]}\n"
                    f"Vision: {vlm_description}\n"
                    f"Suggest action (JSON only):"
                )
                raw = _query_reasoning_model(_SYSTEM_PROMPT, user_prompt)
                parsed = _extract_json(raw)
                if parsed:
                    llm_action = parsed.get("action")
                    llm_conf = float(parsed.get("target_visible_confidence", 0.0) or 0.0)
                    llm_target_found = bool(parsed.get("target_found", False))
                    llm_target_direction = parsed.get("target_direction", "not_visible")
                    llm_target_bbox = parsed.get("target_bbox")
                    print(f"[ARIA] LLM: action={llm_action} conf={llm_conf:.2f} found={llm_target_found}")
                    _emit(event_callback, {
                        "type": "reasoning", "step": step,
                        "action": llm_action,
                        "reasoning": parsed.get("reasoning", ""),
                    })
                    ollama_online = True  # confirmed reachable

            except Exception as e:
                err_type = type(e).__name__
                print(f"[ARIA] LLM unavailable ({err_type}) — skipping for {_OLLAMA_RETRY_INTERVAL} steps")
                ollama_online = False
                ollama_skip_until_step = step + _OLLAMA_RETRY_INTERVAL
        elif not reachable:
            print(f"[ARIA] LLM offline — retry at step {ollama_skip_until_step}")
        else:
            print(f"[ARIA] LLM throttled (grid nav this step; next LLM in "
                  f"≤{OLLAMA_VISION_SAMPLE_INTERVAL:.0f}s)")

        t_llm = time.time()

        # ============================================================
        # ACTION SELECTION
        # Priority: target pursuit (nav_action+target_done) > LLM > nav_action
        # ============================================================
        valid_actions = {
            "move_forward", "turn_left_45", "turn_right_45",
            "turn_left_90", "turn_right_90", "turn_around",
            "back_up", "back_up_turn", "back_up_turn_left", "back_up_turn_right", "stop",
        }

        if llm_action and llm_action in valid_actions and llm_conf >= 0.7 and not pursuing:
            # LLM confident and online (never overrides an active target pursuit)
            action = llm_action
            reasoning = f"LLM decision (conf={llm_conf:.2f})"
        else:
            action = nav_action if nav_action in valid_actions else "move_forward"
            reasoning = nav_reason

        # ============================================================
        # SENSOR SAFETY OVERRIDE — skipped when we are intentionally stopping
        # on the target (target_done), since stopping never causes a collision.
        # ============================================================
        if not target_done:
            if scan_result.get("critical") or (white_wall and scan_result["front"] > OBSTACLE_THRESH * 0.7):
                clearer = scan_result.get("clearer_turn", "turn_left_45")
                action = f"back_up_turn_{clearer.split('_')[1]}"
                reasoning = f"[SAFETY] critical proximity {scan_result['max']:.0f}, backing out"
                print(f"[ARIA] Critical safety override → {action}")

            elif action == "move_forward" and front_blocked:
                action = scan_result.get("clearer_turn", "turn_left_45")
                reasoning = f"[SAFETY] front blocked ({scan_result['front']:.0f}), turning to clearer side"
                print(f"[ARIA] Front-blocked override → {action}")

        print(f"[ARIA] → ACTION: {action} | {reasoning}")
        state.plan = reasoning
        state.reasoning_trace.append(
            f"step={step} pos=({pos_xy[0]:.1f},{pos_xy[1]:.1f}) "
            f"hdg={heading_deg:.0f}° blocked={front_blocked} "
            f"action={action} reason={reasoning}"
        )

        # ============================================================
        # ENVIRONMENT GRAPH UPDATE
        # ============================================================
        try:
            env_graph.add_observation(
                pose={"x": position[0], "y": position[1],
                      "z": position[2], "rotation": heading_deg},
                timestamp=float(timestamp),
                observation_id=f"obs_{step}",
                objects_detected=[
                    {"class_name": d.class_name, "confidence": d.confidence}
                    for d in detections
                ],
            )
        except Exception:
            pass

        graph_stats = {}
        try:
            graph_stats = env_graph.get_stats()
        except Exception:
            pass

        _emit(
            event_callback,
            {
                "type": "step",
                "step": step,
                "goal": goal,
                "success": target_done,
                "plan": reasoning,
                "action": action,
                "robot_state": {
                    "step": step,
                    "max_steps": max_steps,
                    "position": position,
                    "heading_degrees": heading_deg,
                    "front_blocked": front_blocked,
                    "proximity_scan_180": scan_result,
                    "white_wall_view": white_wall,
                    "proximity": proximity,
                    "detections": detection_dicts[:20],
                    "graph_stats": graph_stats,
                    "map_stats": omap.stats(),
                    "spatial_memory": spatial_mem.summary(),
                },
                "reasoning_tail": reasoning,
            },
        )

        # ============================================================
        # SUCCESS CHECK  (find: stopped on sight;  approach: reached it)
        # ============================================================
        if action == "stop" and target_done:
            _execute_motion("stop")
            state.success = True
            verb = "reached" if approach_mode else "found"
            state.reasoning_trace.append(f"SUCCESS at step {step}: {target} {verb}")
            _emit(event_callback, {
                "type": "success", "step": step, "goal": goal, "success": True,
            })
            print(f"\n[ARIA] SUCCESS — {verb} '{target}' at step {step}")
            break

        # Exploration exhausted with no target → stop ONCE and end the run,
        # instead of re-scanning and re-printing "EXPLORATION COMPLETE" until
        # max_steps (which wasted the back half of run_20260604_164900).
        if exploration_done:
            _execute_motion("stop")
            state.reasoning_trace.append(
                f"DONE at step {step}: explored all reachable space, '{target}' not found"
            )
            _emit(event_callback, {
                "type": "done", "step": step, "goal": goal, "success": False,
            })
            print(f"\n[ARIA] DONE — explored all reachable space, '{target}' not found "
                  f"at step {step}")
            break

        # ============================================================
        # EXECUTE ACTION + UPDATE ESTIMATED HEADING
        # ============================================================
        motion_fb: Dict[str, Any] = {}
        try:
            motion_fb = _execute_motion(action) or {}
        except Exception as e:
            print(f"[ARIA] Motion error: {e}")

        # Motion feedback from the controller — shows whether the robot actually
        # TRANSLATED (distance) / ROTATED (degrees) vs just got commanded to.
        # This is the key signal for "does it really move or only spin?".
        if motion_fb:
            print(f"[ARIA] MOVED dist={motion_fb.get('distance_traveled', 0.0):.3f}m "
                  f"turned={motion_fb.get('degrees_turned', 0.0):.1f}° "
                  f"reached={motion_fb.get('reached_target')} "
                  f"steps={motion_fb.get('duration_steps')}")

        # Per-step timing breakdown (helps spot a slow section in the log)
        t_act = time.time()
        print(f"[ARIA] dt sense+yolo={t_sense - cycle_start:.2f}s "
              f"plan={t_nav - t_sense:.2f}s llm={t_llm - t_nav:.2f}s "
              f"move={t_act - t_llm:.2f}s total={t_act - cycle_start:.2f}s")

        # Pad to cycle interval
        elapsed = time.time() - cycle_start
        remaining = CYCLE_INTERVAL - elapsed
        if remaining > 0.05:
            time.sleep(remaining)

    # === FINAL RESULT ===
    print(f"\n{'='*60}")
    if state.success:
        print(f"[ARIA] SUCCESS: '{target}' found in {state.step_count} steps")
    else:
        print(f"[ARIA] STOPPED: '{target}' not found after {state.step_count} steps")
    print(f"[ARIA] Map: {omap.stats()}")
    print(f"[ARIA] Spatial memory: {spatial_mem.summary()}")
    print(f"{'='*60}\n")

    _emit(event_callback, {
        "type": "done",
        "step": state.step_count,
        "goal": goal,
        "success": state.success,
        "map_stats": omap.stats(),
        "spatial_memory": spatial_mem.summary(),
    })
    return state
