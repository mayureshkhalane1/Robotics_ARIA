"""ARIA Robot Navigation Agent — systematic exploration + spatial memory."""

# === Standard Library ===
import base64
import json
import re
import time
import urllib.request
from base64 import b64decode
from math import atan2, degrees
from typing import Any, Callable, Dict, List, Optional, Tuple

# === Third-Party ===
import cv2
import numpy as np

# === Project ===
from src.agent.environment_graph import get_environment_graph
from src.agent.exploration_agent import ExplorationPlanner, RoomMapper
from src.agent.grid_explorer import GridExplorer
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
CYCLE_INTERVAL = 2.5        # seconds per decision cycle (reduced for faster exploration)
MOVE_DURATION = 1.2
BACKUP_DURATION = 1.0
MOVE_VELOCITY = 2.2
BACKUP_VELOCITY = -2.0
TURN_90_DUR = 1.7
TURN_180_DUR = 3.4
TURN_VELOCITY = 1.5

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
    if len(orientation) < 3:
        return 0.0
    bx, _by, bz = orientation[0], orientation[1], orientation[2]
    return degrees(atan2(bx, bz))


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


def _execute_motion(action: str) -> None:
    if action == "move_forward":
        call_tool("execute_action", {"action_type": "move", "velocity": MOVE_VELOCITY})
        time.sleep(MOVE_DURATION)
        call_tool("stop", {})
    elif action == "turn_left_90":
        call_tool("execute_action", {"action_type": "turn", "angular_velocity": TURN_VELOCITY})
        time.sleep(TURN_90_DUR)
        call_tool("stop", {})
    elif action == "turn_right_90":
        call_tool("execute_action", {"action_type": "turn", "angular_velocity": -TURN_VELOCITY})
        time.sleep(TURN_90_DUR)
        call_tool("stop", {})
    elif action == "turn_around":
        call_tool("execute_action", {"action_type": "turn", "angular_velocity": TURN_VELOCITY})
        time.sleep(TURN_180_DUR)
        call_tool("stop", {})
    elif action == "back_up":
        call_tool("execute_action", {"action_type": "move", "velocity": BACKUP_VELOCITY})
        time.sleep(BACKUP_DURATION)
        call_tool("stop", {})
    elif action in ("back_up_turn", "back_up_turn_left"):
        call_tool("execute_action", {"action_type": "move", "velocity": BACKUP_VELOCITY})
        time.sleep(BACKUP_DURATION)
        call_tool("stop", {})
        call_tool("execute_action", {"action_type": "turn", "angular_velocity": TURN_VELOCITY})
        time.sleep(TURN_90_DUR)
        call_tool("stop", {})
    elif action == "back_up_turn_right":
        call_tool("execute_action", {"action_type": "move", "velocity": BACKUP_VELOCITY})
        time.sleep(BACKUP_DURATION)
        call_tool("stop", {})
        call_tool("execute_action", {"action_type": "turn", "angular_velocity": -TURN_VELOCITY})
        time.sleep(TURN_90_DUR)
        call_tool("stop", {})
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

    # --- Systematic exploration infrastructure ---
    grid = GridExplorer(WEBOTS_WORLD_FILE, grid_spacing=1.5)
    spatial_mem = SpatialMemory()

    # Active waypoint being navigated to
    active_wp_idx: Optional[int] = None
    active_wp_pos: Optional[Tuple[float, float]] = None

    # Are we doing a 360° scan at the current waypoint?
    scanning = False

    # Estimated heading (updated immediately on turn; avoids 1-step sensor lag)
    estimated_heading: Optional[float] = None   # None until first sensor reading

    # Ollama connectivity tracking (fail-fast: skip LLM when offline)
    ollama_online = True
    ollama_skip_until_step = 0   # re-try every _OLLAMA_RETRY_INTERVAL steps

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

        sensor_heading = _heading_from_orientation(orientation)

        # Seed estimated heading from sensors on first step, then keep our own
        # prediction to avoid the 1-step lag (sensors show pre-turn heading for
        # one full cycle after a turn command is issued).
        if estimated_heading is None:
            estimated_heading = sensor_heading
        else:
            # Sync back to sensor value only when they agree (turn has settled)
            diff = abs(sensor_heading - estimated_heading)
            if diff > 180:
                diff = 360 - diff
            if diff < 25:
                estimated_heading = sensor_heading

        heading_deg = estimated_heading
        scan_result = _proximity_scan(proximity)
        front_blocked = bool(scan_result["front_blocked"])
        pos_xy = (float(position[0]), float(position[1]))

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
        # Hierarchy: scanning > known-target waypoint > grid waypoint
        # ============================================================
        nav_action: str
        nav_reason: str

        if scanning:
            # Mid-360° sweep — keep turning
            nav_action = grid.scan_step()
            nav_reason = f"360° scan at waypoint {active_wp_idx} ({grid.progress()})"
            if grid.scan_done():
                scanning = False
                grid.mark_current_visited()
                active_wp_idx = None
                active_wp_pos = None
                print(f"[ARIA] Scan complete. {grid.progress()}")

        elif spatial_mem.has_target(target):
            # We've seen this target before — go straight to it
            known_pos = spatial_mem.nearest(target, list(pos_xy))
            nav_action, dist = grid.get_nav_action(pos_xy, tuple(known_pos), heading_deg)
            nav_reason = (
                f"navigating to known {target} position "
                f"({known_pos[0]:.1f},{known_pos[1]:.1f}) dist={dist:.1f}m"
            )
            print(f"[ARIA] Known target position → {nav_action}  {nav_reason}")

        else:
            # No known position — follow grid exploration
            if active_wp_pos is None or (
                active_wp_idx is not None and grid.visited[active_wp_idx]
            ):
                result_wp = grid.nearest_unvisited(pos_xy)
                if result_wp:
                    active_wp_idx, active_wp_pos = result_wp
                    grid.set_active(active_wp_idx)
                    print(
                        f"[ARIA] New waypoint: #{active_wp_idx} "
                        f"({active_wp_pos[0]:.1f},{active_wp_pos[1]:.1f})  "
                        f"{grid.progress()}"
                    )
                else:
                    # All waypoints visited — full scan done without finding target
                    print(f"[ARIA] ALL WAYPOINTS VISITED — target '{target}' not found")
                    nav_action = "stop"
                    nav_reason = "full room scan complete, target not found"
                    active_wp_pos = None

            if active_wp_pos is not None:
                nav_action, dist = grid.get_nav_action(
                    pos_xy, active_wp_pos, heading_deg
                )
                nav_reason = (
                    f"grid wp#{active_wp_idx} "
                    f"({active_wp_pos[0]:.1f},{active_wp_pos[1]:.1f}) "
                    f"dist={dist:.1f}m → {nav_action}"
                )
                print(f"[ARIA] Grid nav: {nav_reason}")

                if nav_action == "arrived":
                    print(f"[ARIA] Arrived at waypoint #{active_wp_idx} — starting 360° scan")
                    scanning = True
                    grid.start_scan()
                    nav_action = grid.scan_step()  # first turn of the sweep
                    nav_reason = f"arrived at wp#{active_wp_idx}, starting 360° scan"

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

        # Only call LLM if it was reachable recently
        attempt_llm = ollama_online or (step >= ollama_skip_until_step)

        if attempt_llm:
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
        else:
            print(f"[ARIA] LLM offline — retry at step {ollama_skip_until_step}")

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
                    "grid_progress": grid.progress(),
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

        # Update estimated_heading immediately so the next step uses the
        # predicted post-turn heading instead of the lagged sensor value.
        if estimated_heading is not None:
            if action == "turn_left_90":
                estimated_heading += 90
            elif action == "turn_right_90":
                estimated_heading -= 90
            elif action == "turn_around":
                estimated_heading += 180
            # Normalise to (-180, 180]
            while estimated_heading > 180:
                estimated_heading -= 360
            while estimated_heading <= -180:
                estimated_heading += 360

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
        if grid.all_visited():
            print(f"[ARIA] FULL SCAN COMPLETE: '{target}' not found after {state.step_count} steps")
        else:
            print(f"[ARIA] STOPPED: '{target}' not found after {state.step_count} steps "
                  f"({grid.progress()})")
    print(f"[ARIA] Spatial memory: {spatial_mem.summary()}")
    print(f"{'='*60}\n")

    _emit(event_callback, {
        "type": "done",
        "step": state.step_count,
        "goal": goal,
        "success": state.success,
        "grid_progress": grid.progress(),
        "spatial_memory": spatial_mem.summary(),
    })
    return state
