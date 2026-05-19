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
from src.common.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from src.common.types import AgentState
from src.mcp_server.server import call_tool
from src.perception.camera import Frame, FrameMetadata, get_camera_manager
from src.perception.object_detector import get_detector

# === Motion Constants ===
CYCLE_INTERVAL = 5.0
MOVE_DURATION = 2.5
MOVE_VELOCITY = 4.0
TURN_90_DUR = 1.7
TURN_180_DUR = 3.4
TURN_VELOCITY = 1.5
OBSTACLE_THRESH = 600

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
}

# === System Prompt ===
_SYSTEM_PROMPT = """You are ARIA, an autonomous indoor navigation robot.
Hardware: Pioneer 3-DX differential-drive robot.
  - Wheel radius: 0.097 m, half-track: 0.1564 m
  - Forward velocity 4.0 rad/s → ~0.388 m/s linear speed
  - 90-degree turn at angular_velocity 1.5 rad/s takes ~1.7 s
  - Proximity sensors: higher raw value = closer obstacle (blocked above 600)

Available actions (use EXACTLY these strings):
  move_forward   - Drive straight ahead ~0.97 m
  turn_left_90   - Rotate 90° counter-clockwise (CCW)
  turn_right_90  - Rotate 90° clockwise (CW)
  turn_around    - Rotate 180°
  stop           - Declare target found and halt

Rules:
  1. Never choose move_forward if front_blocked is true.
  2. When the target is visible in the image (confirmed by yolo_detections), choose stop and set target_found=true.
  3. Prefer unexplored directions; avoid re-visiting visited_positions_last_8 whenever possible.
  4. If stuck (blocked on all recent steps), alternate turns to escape.

Respond ONLY with a single JSON object — no markdown fences, no extra text:
{"action": "<action>", "reasoning": "<one sentence>", "target_found": <true|false>, "target_direction": "<left|right|center|not_visible>"}
"""


# === Helpers ===

def _extract_target(goal: str) -> str:
    goal_lower = goal.lower()
    for keyword, target in _TARGET_KEYWORDS.items():
        if keyword in goal_lower:
            return target
    words = goal_lower.split()
    return words[-1] if words else "object"


def _get_front_proximity(proximity: Dict[str, float]) -> tuple[bool, float]:
    front_keys = ["so0", "so1", "so2", "so15"]
    values = [proximity[k] for k in front_keys if k in proximity]
    if not values:
        values = list(proximity.values())
    if not values:
        return False, 0.0
    max_val = max(values)
    return max_val > OBSTACLE_THRESH, max_val


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
            return frame_bgra[:, :, :3].copy()
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return frame
    except Exception as e:
        print(f"[ARIA] Camera decode error: {e}")
        return None


def _frame_to_jpeg_b64(frame_bgr: np.ndarray, quality: int = 85) -> Optional[str]:
    try:
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


def _query_vlm(
    model: str,
    system_prompt: str,
    user_prompt: str,
    jpeg_b64: Optional[str],
    temperature: float = 0.1,
) -> str:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    user_msg: Dict[str, Any] = {"role": "user", "content": user_prompt}
    if jpeg_b64:
        user_msg["images"] = [jpeg_b64]
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            user_msg,
        ],
        "options": {"temperature": temperature},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    return raw.get("message", {}).get("content", "")


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
    camera = get_camera_manager()
    detector = get_detector()
    env_graph = get_environment_graph()

    state = AgentState(goal=goal, step_count=0, success=False)
    objects_seen_so_far: List[str] = []
    visited_positions: List[str] = []

    print(f"\n[ARIA] Goal: {goal}")
    print(f"[ARIA] Target: {target}")
    print(f"[ARIA] Model: {model}")

    _emit(event_callback, {"type": "start", "step": 0, "goal": goal})

    for step in range(1, max_steps + 1):
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
        front_blocked, front_max_proximity = _get_front_proximity(proximity)
        pos_key = f"({position[0]:.1f},{position[1]:.1f})"
        if pos_key not in visited_positions:
            visited_positions.append(pos_key)
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

        # === YOLO DETECTION ===
        detections = []
        target_found_yolo = False
        if frame_bgr is not None:
            try:
                detections = detector.detect(frame_bgr)
                detected_names = [d.class_name for d in detections]
                for name in detected_names:
                    if name not in objects_seen_so_far:
                        objects_seen_so_far.append(name)
                target_found_yolo = any(
                    d.class_name.lower() == target.lower() for d in detections
                )
                print(f"[ARIA] YOLO detections: {detected_names}")
            except Exception as e:
                print(f"[ARIA] YOLO error: {e}")

        yolo_str = (
            ", ".join(
                f"{d.class_name}({d.confidence:.2f}) @ ({d.center[0]:.0f},{d.center[1]:.0f})"
                for d in detections
            )
            if detections
            else "none"
        )

        # === VLM QUERY ===
        jpeg_b64: Optional[str] = None
        vlm_scene = "No image available."
        if frame_bgr is not None:
            jpeg_b64 = _frame_to_jpeg_b64(frame_bgr)

        _emit(event_callback, {"type": "vlm_query", "step": step, "goal": goal})

        user_prompt_dict = {
            "step": step,
            "max_steps": max_steps,
            "goal": goal,
            "target_to_find": target,
            "position": [round(position[0], 3), round(position[1], 3), round(position[2], 3)],
            "heading_degrees": round(heading_deg, 1),
            "front_blocked": front_blocked,
            "front_max_proximity": round(front_max_proximity, 1),
            "all_proximity_sensors": {k: round(v, 1) for k, v in proximity.items()},
            "yolo_detections": yolo_str,
            "objects_seen_so_far": objects_seen_so_far,
            "visited_positions_last_8": visited_last_8,
            "scene_description_vlm": vlm_scene,
            "steps_remaining": max_steps - step,
        }

        llm_response_text = ""
        try:
            llm_response_text = _query_vlm(
                model=model,
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=json.dumps(user_prompt_dict),
                jpeg_b64=jpeg_b64,
            )
            print(f"[ARIA] LLM raw: {llm_response_text[:200]}")
        except Exception as e:
            print(f"[ARIA] VLM error: {e}")
            llm_response_text = '{"action":"move_forward","reasoning":"VLM unavailable, exploring","target_found":false,"target_direction":"not_visible"}'

        # === PARSE LLM RESPONSE ===
        parsed = _extract_json(llm_response_text)
        if parsed is None:
            print("[ARIA] JSON parse failed, defaulting to move_forward")
            parsed = {
                "action": "move_forward",
                "reasoning": "parse error",
                "target_found": False,
                "target_direction": "not_visible",
            }

        action = parsed.get("action", "move_forward")
        reasoning = parsed.get("reasoning", "")
        llm_target_found = bool(parsed.get("target_found", False))
        target_direction = parsed.get("target_direction", "not_visible")

        valid_actions = {"move_forward", "turn_left_90", "turn_right_90", "turn_around", "stop"}
        if action not in valid_actions:
            action = "move_forward"

        # === SAFETY OVERRIDE ===
        if action == "move_forward" and front_blocked:
            print(f"[ARIA] Safety override: front blocked (max={front_max_proximity:.0f}), forcing turn_left_90")
            action = "turn_left_90"
            reasoning = f"[safety override] was:{reasoning}"

        # === TARGET DETECTION (YOLO only) ===
        if target_found_yolo:
            print(f"[ARIA] Target '{target}' confirmed by YOLO")
            action = "stop"
            llm_target_found = True

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
                    "position": position,
                    "heading_degrees": heading_deg,
                    "front_blocked": front_blocked,
                    "proximity": proximity,
                    "detections": yolo_str,
                    "graph_stats": graph_stats,
                },
                "reasoning_tail": reasoning,
            },
        )

        # === SUCCESS CHECK ===
        if action == "stop" and (target_found_yolo or llm_target_found):
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
