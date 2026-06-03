"""ARIA Robot Navigation Agent — systematic exploration + spatial memory."""

# === Standard Library ===
import base64
import json
import re
import time
import urllib.request
from base64 import b64decode
from math import atan2, degrees, hypot
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
    WEBOTS_WORLD_FILE,
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

def _extract_target(goal: str) -> str:
    goal_lower = goal.lower()
    for keyword, target in _TARGET_KEYWORDS.items():
        if keyword in goal_lower:
            return target
    words = re.findall(r"[a-zA-Z][a-zA-Z-]*", goal_lower)
    candidates = [w for w in words if w not in _GOAL_STOPWORDS and not w.isdigit()]
    return candidates[0] if candidates else "object"


def _target_aliases(target: str) -> set:
    t = target.lower().strip()
    aliases = {t}
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
            "clearer_turn": "turn_left_90",
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
    clearer_turn = "turn_left_90" if left < right else "turn_right_90"
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
        turn = scan.get("clearer_turn", "turn_left_90")
        return f"back_up_turn_{turn.split('_')[1]}", "critical proximity — backing out"
    if scan.get("front_blocked"):
        return scan.get("clearer_turn", "turn_left_90"), "front blocked — turning to clearer side"
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


def _fwd(distance: float = MOVE_DISTANCE, velocity: float = MOVE_VELOCITY) -> None:
    call_tool("execute_action", {
        "action_type": "move", "velocity": velocity,
        "target_distance": distance, "steps": MOVE_STEP_CAP,
    })


def _turn(degrees_: float, direction: int) -> None:
    """direction: +1 = left/CCW, -1 = right/CW."""
    call_tool("execute_action", {
        "action_type": "turn", "angular_velocity": direction * TURN_VELOCITY,
        "target_angle": abs(degrees_), "steps": TURN_STEP_CAP,
    })


def _execute_motion(action: str) -> None:
    """Issue one closed-loop motion. Each call blocks until the controller has
    reached the sensor goal and stopped the wheels — no agent-side sleeps."""
    if action == "move_forward":
        _fwd()
    elif action == "turn_left_90":
        _turn(90, +1)
    elif action == "turn_right_90":
        _turn(90, -1)
    elif action == "turn_around":
        _turn(180, +1)
    elif action == "back_up":
        _fwd(distance=BACKUP_DISTANCE, velocity=BACKUP_VELOCITY)
    elif action in ("back_up_turn", "back_up_turn_left"):
        _fwd(distance=BACKUP_DISTANCE, velocity=BACKUP_VELOCITY)
        _turn(90, +1)
    elif action == "back_up_turn_right":
        _fwd(distance=BACKUP_DISTANCE, velocity=BACKUP_VELOCITY)
        _turn(90, -1)
    elif action == "stop":
        call_tool("stop", {})


def _emit(callback: Optional[Callable], event: Dict[str, Any]) -> None:
    if callback is None:
        return
    try:
        callback(event)
    except Exception as e:
        print(f"[ARIA] Event callback error: {e}")


# =========================================================================
# Main Agent
# =========================================================================

def run_aria_agent(
    goal: str,
    max_steps: int = 100,
    model: str = OLLAMA_MODEL,
    event_callback: Optional[Callable[[Dict], None]] = None,
) -> AgentState:

    target = _extract_target(goal)
    target_aliases = _target_aliases(target)
    camera = get_camera_manager()
    detector = get_detector()
    env_graph = get_environment_graph()

    # --- Autonomous exploration infrastructure ---
    # GridExplorer is kept ONLY for its map-agnostic helpers (heading→turn
    # action and the 360° scan state machine) — its lattice is not used.
    grid = GridExplorer(WEBOTS_WORLD_FILE, grid_spacing=1.5)
    # The robot discovers the room itself: a live occupancy grid built from the
    # Lidar, driven by frontier exploration.  No wall positions are read from
    # the .wbt — only the floor bounding box, to size the grid's frame.
    omap = OnlineOccupancyGrid(
        *parse_floor_extent(WEBOTS_WORLD_FILE), resolution=0.10, robot_radius=0.25
    )
    spatial_mem = SpatialMemory()

    def _plan_action(cur_xy, goal_xy):
        """Heading-aware action toward goal_xy, routed around DISCOVERED
        obstacles via the live occupancy map.  Returns (action, dist_to_goal)."""
        d = hypot(goal_xy[0] - cur_xy[0], goal_xy[1] - cur_xy[1])
        if d <= grid.ARRIVAL_RADIUS:
            return "arrived", d
        carrot = omap.next_step_toward(cur_xy, tuple(goal_xy), lookahead=0.7)
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
    print(f"[ARIA] Target: {target}  aliases: {sorted(target_aliases)}")
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

        # ============================================================
        # DETERMINE BASE NAVIGATION ACTION
        # Hierarchy: scanning > known-target recall > frontier exploration
        # ============================================================
        nav_action: str
        nav_reason: str

        if scanning:
            # Mid-360° look-around (fills the map + lets YOLO see all directions)
            nav_action = grid.scan_step()
            nav_reason = f"360° look-around ({omap.stats()['unknown']} cells unknown)"
            if grid.scan_done():
                scanning = False
                active_frontier = None      # pick a fresh frontier next cycle
                print("[ARIA] Look-around complete")

        elif spatial_mem.has_target(target):
            # We've seen this target before — route to it through known-free space
            known_pos = spatial_mem.nearest(target, list(pos_xy))
            nav_action, dist = _plan_action(pos_xy, tuple(known_pos))
            if nav_action == "arrived":
                nav_action = "turn_right_90"   # at the known spot — sweep to reacquire
            nav_reason = (
                f"navigating to known {target} position "
                f"({known_pos[0]:.1f},{known_pos[1]:.1f}) dist={dist:.1f}m → {nav_action}"
            )
            print(f"[ARIA] Known target position → {nav_action}  {nav_reason}")

        else:
            # ---- Autonomous frontier exploration ----
            # Pick a new frontier when we have none, reached the current one, or
            # it is no longer on the boundary of the unknown.
            if active_frontier is None or not omap.is_free(*active_frontier) or \
                    hypot(active_frontier[0] - pos_xy[0], active_frontier[1] - pos_xy[1]) < grid.ARRIVAL_RADIUS:
                active_frontier = omap.nearest_frontier(pos_xy)
                best_dist_to_wp = float("inf")
                no_progress_count = 0
                if active_frontier is not None:
                    no_frontier_count = 0
                    print(f"[ARIA] New frontier target "
                          f"({active_frontier[0]:.1f},{active_frontier[1]:.1f})  "
                          f"map: {omap.stats()}")

            if active_frontier is None:
                # Nothing left to explore that we can reach.
                no_frontier_count += 1
                if no_frontier_count >= 3:
                    print(f"[ARIA] EXPLORATION COMPLETE — '{target}' not found  {omap.stats()}")
                    nav_action = "stop"
                    nav_reason = "explored all reachable space, target not found"
                else:
                    # give the map a couple of turns to find a frontier behind us
                    nav_action = "turn_right_90"
                    nav_reason = "no frontier visible — turning to map more"
            else:
                nav_action, dist = _plan_action(pos_xy, active_frontier)

                if dist < best_dist_to_wp - PROGRESS_EPS:
                    best_dist_to_wp = dist
                    no_progress_count = 0
                else:
                    no_progress_count += 1

                if nav_action == "arrived":
                    print("[ARIA] Reached frontier — 360° look-around")
                    scanning = True
                    grid.start_scan()
                    nav_action = grid.scan_step()
                    nav_reason = "reached frontier, starting 360° look-around"

                elif no_progress_count >= NO_PROGRESS_LIMIT:
                    # Couldn't make headway (furniture the Lidar didn't catch).
                    # Blacklist this frontier so we don't keep retrying it.
                    print(f"[ARIA] Frontier ({active_frontier[0]:.1f},"
                          f"{active_frontier[1]:.1f}) blocked — blacklisting")
                    omap.blacklist(*active_frontier)
                    active_frontier = None
                    best_dist_to_wp = float("inf")
                    no_progress_count = 0
                    nav_action = "turn_around"
                    nav_reason = "blocked frontier — turning away to re-plan"
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

        # Call the LLM only if (a) it was reachable recently AND (b) enough
        # wall-clock time has passed since the last call.  This caps the slow
        # vision+reasoning round-trips to ~once per OLLAMA_VISION_SAMPLE_INTERVAL
        # seconds; YOLO still runs every step so target detection is unaffected.
        reachable = ollama_online or (step >= ollama_skip_until_step)
        due = (cycle_start - last_llm_ts) >= OLLAMA_VISION_SAMPLE_INTERVAL
        attempt_llm = reachable and due

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

        # ============================================================
        # ACTION SELECTION
        # Priority: target_found_yolo > LLM (when confident) > nav_action
        # ============================================================
        valid_actions = {
            "move_forward", "turn_left_90", "turn_right_90", "turn_around",
            "back_up", "back_up_turn", "back_up_turn_left", "back_up_turn_right", "stop",
        }

        if target_found_yolo:
            # YOLO sees the target — stop and celebrate
            action = "stop"
            reasoning = f"YOLO confirmed '{target}' in frame"

        elif llm_action and llm_action in valid_actions and llm_conf >= 0.7:
            # LLM is confident and online — use its decision
            action = llm_action
            reasoning = f"LLM decision (conf={llm_conf:.2f})"
        else:
            # Fall back to systematic grid navigation
            action = nav_action if nav_action in valid_actions else "move_forward"
            reasoning = nav_reason

        # ============================================================
        # SENSOR SAFETY OVERRIDE (unconditional — nothing can bypass this)
        # ============================================================
        if scan_result.get("critical") or (white_wall and scan_result["front"] > OBSTACLE_THRESH * 0.7):
            clearer = scan_result.get("clearer_turn", "turn_left_90")
            action = f"back_up_turn_{clearer.split('_')[1]}"
            reasoning = f"[SAFETY] critical proximity {scan_result['max']:.0f}, backing out"
            print(f"[ARIA] Critical safety override → {action}")

        elif action == "move_forward" and front_blocked:
            action = scan_result.get("clearer_turn", "turn_left_90")
            reasoning = f"[SAFETY] front blocked ({scan_result['front']:.0f}), turning to clearer side"
            print(f"[ARIA] Front-blocked override → {action}")

        # ============================================================
        # TARGET CONFIRMATION (stop only if YOLO actually saw it)
        # ============================================================
        vlm_confirmed = (
            llm_target_found
            and llm_conf >= 0.70
            and llm_target_direction in {"left", "right", "center"}
            and llm_target_bbox is not None
        )
        if action == "stop" and not target_found_yolo and not vlm_confirmed:
            action = nav_action if nav_action in valid_actions else "turn_left_90"
            reasoning = f"Weak target evidence, continuing exploration. {reasoning}"

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
                "success": target_found_yolo,
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
        # SUCCESS CHECK
        # ============================================================
        if action == "stop" and (target_found_yolo or vlm_confirmed):
            _execute_motion("stop")
            state.success = True
            state.reasoning_trace.append(f"SUCCESS at step {step}: {target} found")
            _emit(event_callback, {
                "type": "success", "step": step, "goal": goal, "success": True,
            })
            print(f"\n[ARIA] SUCCESS — found '{target}' at step {step}")
            break

        # ============================================================
        # EXECUTE ACTION + UPDATE ESTIMATED HEADING
        # ============================================================
        try:
            _execute_motion(action)
        except Exception as e:
            print(f"[ARIA] Motion error: {e}")

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
