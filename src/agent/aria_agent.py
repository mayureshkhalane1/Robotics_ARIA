"""ARIA Robot Navigation Agent - complete rewrite with correct architecture."""

# === Standard Library ===
import base64
import json
import re
import time
import urllib.request
from base64 import b64decode
from math import atan2, degrees
from typing import Any, Callable, Dict, List, Optional

# === Third-Party ===
import cv2
import numpy as np

# === Project ===
from src.agent.environment_graph import get_environment_graph
from src.agent.exploration_agent import ExplorationPlanner, RoomMapper
from src.agent.intelligent_decision_maker import IntelligentDecisionMaker
from src.common.config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_VISION_MODEL,
    OLLAMA_REASONING_MODEL,
    OLLAMA_VISION_IMAGE_MAX_DIM,
    OLLAMA_VISION_NUM_PREDICT,
    OLLAMA_VISION_SAMPLE_INTERVAL,
    OLLAMA_VISION_TIMEOUT,
)
from src.common.types import AgentState
from src.mcp_server.server import call_tool
from src.perception.camera import Frame, FrameMetadata, get_camera_manager
from src.perception.object_detector import get_detector

# === Motion Constants ===
CYCLE_INTERVAL = 4.0
MOVE_DURATION = 1.2
BACKUP_DURATION = 1.0
MOVE_VELOCITY = 2.2
BACKUP_VELOCITY = -2.0
TURN_90_DUR = 1.7
TURN_180_DUR = 3.4
TURN_VELOCITY = 1.5
OBSTACLE_THRESH = 600
CRITICAL_OBSTACLE_THRESH = 950  # Very close collision (wall right in front)

# === Global Stop Signal ===
_STOP_SIGNAL = False

def set_stop_signal(value: bool) -> None:
    """Set the global stop signal."""
    global _STOP_SIGNAL
    _STOP_SIGNAL = value

def get_stop_signal() -> bool:
    """Get the current stop signal state."""
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
}

_GOAL_STOPWORDS = {
    "find", "the", "a", "an", "and", "go", "towards", "toward", "to", "it",
    "stop", "away", "from", "centimeter", "centimeters", "cm", "meter", "meters",
    "near", "at", "search", "for", "object", "target",
}

# === System Prompt ===
_SYSTEM_PROMPT = """You are ARIA, an autonomous robot navigating a furnished apartment with 2 bedrooms, living room, kitchen, and hallways.

ENVIRONMENT: The apartment has multiple rooms and objects. You start at the center.

SENSING: 
- Camera gives YOLO-annotated image with bounding boxes and class labels
- 180° proximity sensors detect obstacles
- You get heading angle, current position, visited locations

NAVIGATION:
- Move by turning to face target, then move forward
- If target visible: approach it, stop when very close
- If target not visible: explore systematically (turn left/right to scan)

ACTIONS (use EXACTLY these):
move_forward, turn_left_90, turn_right_90, turn_around, stop, back_up, back_up_turn

SAFETY RULES:
1. NEVER move_forward if front_blocked=true
2. If stuck (visited same spot repeatedly), try different direction
3. White wall view = very close to wall, must backup

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


def _target_aliases(target: str) -> set[str]:
    t = target.lower().strip()
    aliases = {t}
    if t == "fire extinguisher":
        aliases.update({"extinguisher", "fire extinguisher"})
    if t == "table":
        aliases.update({"dining table"})
    if t == "plant":
        aliases.update({"potted plant"})
    if t == "sofa":
        aliases.update({"couch"})
    return aliases


def _detection_to_dict(d: Any) -> Dict[str, Any]:
    x1, y1, x2, y2 = d.bbox
    return {
        "class_name": d.class_name,
        "confidence": round(float(d.confidence), 3),
        "bbox": [round(float(x1), 1), round(float(y1), 1), round(float(x2), 1), round(float(y2), 1)],
        "center": [round(float(d.center[0]), 1), round(float(d.center[1]), 1)],
        "class_id": int(d.class_id),
    }


def _sensor_index(name: str) -> Optional[int]:
    m = re.search(r"(\d+)$", name)
    return int(m.group(1)) if m else None


def _proximity_scan(proximity: Dict[str, float]) -> Dict[str, Any]:
    """Summarize 180-degree obstacle scan. Higher Webots distance value means closer."""
    items = [(k, float(v), _sensor_index(k)) for k, v in proximity.items() if float(v) >= 0]
    if not items:
        return {"front_blocked": False, "critical": False, "front": 0.0, "left": 0.0, "right": 0.0, "clearer_turn": "turn_left_90"}

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
        front_vals = values
        left_vals = values
        right_vals = values

    front = max(front_vals or values)
    left = max(left_vals or [0.0])
    right = max(right_vals or [0.0])
    # Turn toward lower proximity value, i.e. more open space.
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


def _safe_exploration_action(scan: Dict[str, Any], white_wall: bool) -> tuple[str, str]:
    backup_turn = "back_up_turn_left" if scan.get("clearer_turn") == "turn_left_90" else "back_up_turn_right"
    if scan.get("critical") or (white_wall and scan.get("front", 0.0) > OBSTACLE_THRESH * 0.7):
        return backup_turn, "critical wall/corner proximity or white wall view, reverse then turn to clearer side"
    if scan.get("front_blocked"):
        return scan.get("clearer_turn", "turn_left_90"), "front obstacle in 180-degree scan, turning toward clearer side"
    return "move_forward", "path clear in 180-degree scan, exploring forward cautiously"


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
        
        # Flip camera image 180 degrees (upside down + horizontal flip)
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
            frame_bgr = cv2.resize(frame_bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
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
    # Strip Qwen <think>...</think> blocks
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # Find first complete JSON object
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
                candidate = text[start: i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    start = None
    return None


def _query_vision_model(
    jpeg_b64: Optional[str],
    user_prompt: str,
    temperature: float = 0.1,
) -> str:
    """Query vision model (llava-phi3) for image description only."""
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
            "temperature": temperature,
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
    text = raw.get("message", {}).get("content") or raw.get("response") or ""
    text = text.strip()
    if not text:
        raise RuntimeError(f"empty response from vision model {OLLAMA_VISION_MODEL}")
    return text


def _query_reasoning_model(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
) -> str:
    """Query reasoning model (qwen3:8b) for agent decisions - TEXT ONLY."""
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": OLLAMA_REASONING_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": {
            "temperature": temperature,
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
    text = raw.get("message", {}).get("content") or raw.get("response") or ""
    text = text.strip()
    if not text:
        raise RuntimeError(f"empty response from reasoning model {OLLAMA_REASONING_MODEL}")
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
    elif action == "back_up_turn":
        call_tool("execute_action", {"action_type": "move", "velocity": BACKUP_VELOCITY})
        time.sleep(BACKUP_DURATION)
        call_tool("stop", {})
        call_tool("execute_action", {"action_type": "turn", "angular_velocity": TURN_VELOCITY})
        time.sleep(TURN_90_DUR)
        call_tool("stop", {})
    elif action == "back_up_turn_left":
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


# === Main Agent ===

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
    
    # Initialize exploration planner
    explorer = ExplorationPlanner(goal, target)
    
    # Initialize intelligent decision maker
    decision_maker = IntelligentDecisionMaker()
    decision_maker.set_target(target)

    state = AgentState(goal=goal, step_count=0, success=False)
    objects_seen_so_far: List[str] = []
    visited_positions: List[str] = []
    stuck_steps = 0  # Counter for consecutive stuck detections
    last_successful_action = "move_forward"  # Track last action that worked


    print(f"\n[ARIA] Goal: {goal}")
    print(f"[ARIA] Target: {target}")
    print(f"[ARIA] Model: {model}")

    _emit(event_callback, {"type": "start", "step": 0, "goal": goal})

    for step in range(1, max_steps + 1):
        # Check for stop signal
        if get_stop_signal():
            print(f"\n[ARIA] STOP SIGNAL RECEIVED - Stopping at step {step}")
            _execute_motion("stop")
            call_tool("stop", {})
            break
        
        cycle_start = time.time()
        state.step_count = step

        print(f"\n{'='*60}")
        print(f"[ARIA] Step {step}/{max_steps}  |  goal: {goal}")
        print(f"{'='*60}")

        # === SENSE ===
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

        heading_deg = _heading_from_orientation(orientation)
        proximity_scan = _proximity_scan(proximity)
        front_blocked = bool(proximity_scan["front_blocked"])
        front_max_proximity = float(proximity_scan["front"])
        pos_key = f"({position[0]:.1f},{position[1]:.1f})"
        if pos_key not in visited_positions:
            visited_positions.append(pos_key)
        
        # Check if stuck
        is_stuck = explorer.detect_stuck((position[0], position[1]))
        if is_stuck:
            print(f"[ARIA] STUCK DETECTION: Repeating position {pos_key}, need to change strategy")
        
        visited_last_8 = visited_positions[-8:]

        # === DECODE CAMERA ===
        frame_bgr: Optional[np.ndarray] = None
        if camera_data:
            frame_bgr = _decode_camera_frame(camera_data)

        if frame_bgr is not None:
            meta = FrameMetadata(timestamp=float(timestamp))
            pose_dict = {"x": position[0], "y": position[1], "z": position[2], "rotation": heading_deg}
            camera.last_frame = Frame(data=frame_bgr, metadata=meta, pose=pose_dict)
            print(f"[ARIA] Camera frame updated: {frame_bgr.shape}")
        else:
            print("[ARIA] No camera frame this cycle")

        white_wall_view = _is_white_wall_view(frame_bgr)
        safe_action, safe_reason = _safe_exploration_action(proximity_scan, white_wall_view)
        print(
            "[ARIA] Proximity scan: "
            f"front={proximity_scan.get('front', 0):.0f} left={proximity_scan.get('left', 0):.0f} "
            f"right={proximity_scan.get('right', 0):.0f} max={proximity_scan.get('max', 0):.0f} "
            f"blocked={front_blocked} critical={proximity_scan.get('critical', False)} white_wall={white_wall_view}"
        )

        # === YOLO DETECTION ON EVERY FRAME ===
        detections = []
        target_found_yolo = False
        annotated_frame_bgr: Optional[np.ndarray] = frame_bgr
        if frame_bgr is not None:
            try:
                detections = detector.detect(frame_bgr)
                annotated_frame_bgr = detector.visualize_detections(frame_bgr, detections)
                detected_names = [d.class_name for d in detections]
                for name in detected_names:
                    if name not in objects_seen_so_far:
                        objects_seen_so_far.append(name)
                target_found_yolo = any(
                    d.class_name.lower() in target_aliases for d in detections
                )
                print("[ARIA] YOLO detections:")
                if detections:
                    for d in detections[:20]:
                        print(f"  - {d.class_name} conf={d.confidence:.2f} bbox={[round(x, 1) for x in d.bbox]} center={[round(x, 1) for x in d.center]}")
                else:
                    print("  - none")
            except Exception as e:
                print(f"[ARIA] YOLO error: {e}")

        detection_dicts = [_detection_to_dict(d) for d in detections]
        yolo_str = json.dumps(detection_dicts[:20]) if detection_dicts else "[]"

        # === VLM QUERY ON ANNOTATED IMAGE (EVERY FRAME) ===
        jpeg_b64: Optional[str] = None
        vlm_scene = "No image available."
        if annotated_frame_bgr is not None:
            jpeg_b64 = _frame_to_jpeg_b64(annotated_frame_bgr)

        _emit(event_callback, {"type": "vlm_query", "step": step, "goal": goal})

        user_prompt_dict = {
            "step": step,
            "max_steps": max_steps,
            "goal": goal,
            "target_to_find": target,
            "target_aliases": sorted(target_aliases),
            "position": [round(position[0], 3), round(position[1], 3), round(position[2], 3)],
            "heading_degrees": round(heading_deg, 1),
            "front_blocked": front_blocked,
            "front_max_proximity": round(front_max_proximity, 1),
            "proximity_scan_180": proximity_scan,
            "white_wall_view": white_wall_view,
            "all_proximity_sensors": {k: round(v, 1) for k, v in proximity.items()},
            "image_is_yolo_annotated": bool(annotated_frame_bgr is not None),
            "vision_sample_interval_seconds": OLLAMA_VISION_SAMPLE_INTERVAL,
            "yolo_detections_all_classes": detection_dicts[:20],
            "objects_seen_so_far": objects_seen_so_far,
            "visited_positions_last_8": visited_last_8,
            "scene_description_vlm": vlm_scene,
            "steps_remaining": max_steps - step,
        }

        llm_response_text = ""
        max_vlm_retries = 2
        try:
            # Step 1: Get image description from VISION model (llava-phi3)
            vision_description = ""
            if jpeg_b64:
                try:
                    vision_prompt = f"""Analyze this YOLO-annotated apartment image. Be VERY concise (2-3 sentences max).
Answer: 1) What room is this? 2) What objects are visible? 3) Where is the {target}? (visible/not visible)"""
                    vision_description = _query_vision_model(
                        jpeg_b64=jpeg_b64,
                        user_prompt=vision_prompt,
                    )
                    print(f"[ARIA] Vision: {vision_description[:100]}...")
                    # Emit vision event to UI
                    _emit(event_callback, {
                        "type": "vision",
                        "step": step,
                        "description": vision_description,
                    })
                except Exception as e:
                    print(f"[ARIA] Vision model failed: {type(e).__name__}: {e}")
                    vision_description = ""
            else:
                print("[ARIA] No image available for vision model")
            
            # Step 2: Use REASONING model to decide action
            user_prompt_dict["vision_description"] = vision_description
            
            # Get exploration-guided prompt
            current_room = vision_description.split('\n')[0] if vision_description else "unknown room"
            exploration_prompt = explorer.get_exploration_prompt(
                current_room, 
                vision_description
            )
            
            # Combine with exploration strategy
            combined_prompt = f"""{exploration_prompt}

SENSOR DATA:
- Front blocked: {front_blocked}
- Proximity: front={proximity_scan.get('front', 0):.0f}, left={proximity_scan.get('left', 0):.0f}, right={proximity_scan.get('right', 0):.0f}
- Position: {position}
- Heading: {heading_deg}°

Choose next action:"""
            
            for attempt in range(max_vlm_retries):
                try:
                    llm_response_text = _query_reasoning_model(
                        system_prompt=_SYSTEM_PROMPT,
                        user_prompt=combined_prompt,
                    )
                    if llm_response_text.strip():
                        print(f"[ARIA] Reasoning: {llm_response_text[:200]}")
                        # Emit reasoning event to UI
                        parsed = _extract_json(llm_response_text)
                        if parsed:
                            _emit(event_callback, {
                                "type": "reasoning",
                                "step": step,
                                "action": parsed.get("action", "unknown"),
                                "reasoning": parsed.get("reasoning", ""),
                            })
                        break
                except Exception as e:
                    if attempt < max_vlm_retries - 1:
                        print(f"[ARIA] Reasoning attempt {attempt+1}/{max_vlm_retries} failed, retrying: {e}")
                        time.sleep(0.5)
                    else:
                        raise
        except Exception as e:
            print(f"[ARIA] VLM error (using sensor-safe fallback): {type(e).__name__}: {e}")
            llm_response_text = json.dumps({
                "action": safe_action,
                "reasoning": f"VLM unavailable; {safe_reason}",
                "target_found": False,
                "target_direction": "not_visible",
            })

        # === PARSE LLM RESPONSE ===
        parsed = _extract_json(llm_response_text)
        if parsed is None:
            print("[ARIA] JSON parse failed, defaulting to sensor-safe action")
            parsed = {
                "action": safe_action,
                "reasoning": f"VLM parse error; {safe_reason}",
                "target_found": False,
                "target_direction": "not_visible",
            }

        action = parsed.get("action", "move_forward")
        reasoning = parsed.get("reasoning", "")
        llm_target_found = bool(parsed.get("target_found", False))
        try:
            llm_target_conf = float(parsed.get("target_visible_confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            llm_target_conf = 0.0
        target_direction = parsed.get("target_direction", "not_visible")
        target_bbox = parsed.get("target_bbox")

        valid_actions = {"move_forward", "turn_left_90", "turn_right_90", "turn_around", "back_up", "back_up_turn", "back_up_turn_left", "back_up_turn_right", "stop"}
        if action not in valid_actions:
            action = "move_forward"

        # === SENSOR-FIRST SAFETY OVERRIDE ===
        if proximity_scan.get("critical") or (white_wall_view and front_max_proximity > OBSTACLE_THRESH * 0.7):
            print(f"[ARIA] Critical safety override: max={proximity_scan.get('max', 0):.0f}, backing out")
            action = safe_action if str(safe_action).startswith("back_up_turn") else "back_up_turn_left"
            reasoning = f"[critical safety override] {safe_reason}; was:{reasoning}"
        elif action == "move_forward" and front_blocked:
            print(f"[ARIA] Safety override: front blocked (front={front_max_proximity:.0f}), forcing {safe_action}")
            action = safe_action if safe_action != "move_forward" else proximity_scan.get("clearer_turn", "turn_left_90")
            reasoning = f"[sensor safety override] {safe_reason}; was:{reasoning}"
        
        # === STUCK HANDLING: FORCE INTELLIGENT TURNS ===
        if is_stuck:
            stuck_steps += 1
            print(f"[ARIA] STUCK #{stuck_steps}: Force exploring different direction")
            
            # Rotate strategy: if front is blocked or we keep moving forward, force turns
            if stuck_steps == 1:
                action = "turn_left_90"
                reasoning = "[stuck-escape-1] Force left turn to explore"
            elif stuck_steps == 2:
                action = "turn_right_90"
                reasoning = "[stuck-escape-2] Force right turn to explore"
            elif stuck_steps >= 3:
                action = "back_up"
                reasoning = "[stuck-escape-3] Back up to get unstuck"
                stuck_steps = 0  # Reset after attempting escape
        else:
            # Reset stuck counter when not stuck
            if action in {"move_forward", "back_up"}:
                stuck_steps = 0
                last_successful_action = action
        
        # === INTELLIGENT DECISION MAKER: Override with semantic understanding ===
        # Use decision maker only when LLM is unsure or stuck
        if stuck_steps > 0 or llm_target_conf < 0.5:
            intelligent_decision = decision_maker.decide_action(
                proximity_front=front_max_proximity,
                vision_text=vision_description,
                current_heading=heading_deg,
                is_stuck=is_stuck,
                stuck_count=stuck_steps
            )
            
            # Override action if we're stuck or uncertain
            if is_stuck or llm_target_conf < 0.5:
                action = intelligent_decision["action"]
                reasoning = f"[intelligent-override] {intelligent_decision['reasoning']}"
                print(f"[ARIA] Intelligence Override: {reasoning}")

        # === TARGET DETECTION (YOLO only) ===
        vlm_confident_found = (
            llm_target_found
            and llm_target_conf >= 0.70
            and target_direction in {"left", "right", "center"}
            and target_bbox is not None
        )

        if target_found_yolo:
            print(f"[ARIA] Target '{target}' confirmed by YOLO")
            action = "stop"
            llm_target_found = True
        elif llm_target_found and not vlm_confident_found:
            print(
                f"[ARIA] Ignoring weak VLM target_found for '{target}' "
                f"(conf={llm_target_conf:.2f}, direction={target_direction}, bbox={target_bbox})"
            )
            llm_target_found = False
            if action == "stop":
                action = "turn_left_90" if not front_blocked else "turn_right_90"
                reasoning = f"Weak target evidence, continue searching. {reasoning}"

        state.reasoning_trace.append(
            f"step={step} pos={pos_key} hdg={heading_deg:.0f}° blocked={front_blocked} "
            f"action={action} yolo=[{yolo_str}] reason={reasoning}"
        )
        state.plan = reasoning

        print(f"[ARIA] Action: {action} | blocked={front_blocked} | reasoning: {reasoning}")

        # === UPDATE ENVIRONMENT GRAPH ===
        pose_dict_graph = {
            "x": position[0],
            "y": position[1],
            "z": position[2],
            "rotation": heading_deg,
        }
        objects_for_graph = [{"class_name": d.class_name, "confidence": d.confidence} for d in detections]
        obs_id = f"obs_{step}"
        try:
            env_graph.add_observation(
                pose=pose_dict_graph,
                timestamp=float(timestamp),
                observation_id=obs_id,
                objects_detected=objects_for_graph,
            )
        except Exception as e:
            print(f"[ARIA] Graph update error: {e}")

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
                "success": llm_target_found,
                "plan": reasoning,
                "action": action,
                "robot_state": {
                    "step": step,
                    "max_steps": max_steps,
                    "position": position,
                    "heading_degrees": heading_deg,
                    "front_blocked": front_blocked,
                    "proximity_scan_180": proximity_scan,
                    "white_wall_view": white_wall_view,
                    "proximity": proximity,
                    "detections": detection_dicts[:20],
                    "graph_stats": graph_stats,
                },
                "reasoning_tail": reasoning,
            },
        )

        # === SUCCESS CHECK ===
        if action == "stop" and (target_found_yolo or vlm_confident_found):
            _execute_motion("stop")
            state.success = True
            state.reasoning_trace.append(f"SUCCESS at step {step}: {target} found")
            _emit(event_callback, {"type": "success", "step": step, "goal": goal, "success": True})
            print(f"\n[ARIA] SUCCESS - found '{target}' at step {step}")
            break

        # === EXECUTE ACTION ===
        action_start = time.time()
        try:
            _execute_motion(action)
        except Exception as e:
            print(f"[ARIA] Action execution error: {e}")

        action_elapsed = time.time() - action_start

        # === WAIT FOR REMAINING CYCLE TIME ===
        elapsed_total = time.time() - cycle_start
        remaining = CYCLE_INTERVAL - elapsed_total
        if remaining > 0.05:
            time.sleep(remaining)

    # === FINAL RESULT ===
    print(f"\n{'='*60}")
    if state.success:
        print(f"[ARIA] SUCCESS: '{target}' found in {state.step_count} steps")
    else:
        print(f"[ARIA] TIMEOUT: '{target}' not found after {state.step_count} steps")
    print(f"{'='*60}\n")

    _emit(
        event_callback,
        {
            "type": "done",
            "step": state.step_count,
            "goal": goal,
            "success": state.success,
        },
    )

    return state
