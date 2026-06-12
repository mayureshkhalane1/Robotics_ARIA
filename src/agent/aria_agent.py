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
from types import SimpleNamespace
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
    AGENT_CYCLE_INTERVAL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_VISION_MODEL,
    OLLAMA_REASONING_MODEL,
    OLLAMA_VISION_IMAGE_MAX_DIM,
    OLLAMA_VISION_NUM_PREDICT,
    OLLAMA_VISION_SAMPLE_INTERVAL,
    OLLAMA_VISION_TIMEOUT,
    PERCEPTION_MODE,
    USE_LLM,
    WEBOTS_WORLD_FILE,
    LOGS_PATH,
)
from src.common.types import AgentState
from src.mcp_server.server import call_tool
from src.perception.camera import (
    Frame,
    FrameMetadata,
    get_camera_manager,
    prepare_vision_frame,
)
from src.perception.object_detector import get_detector

# === Motion Constants ===
# Motion is now closed-loop in the Webots controller (it drives until the GPS
# distance / compass angle goal is met, then stops the wheels itself), so the
# agent no longer sleeps to time a motion.  CYCLE_INTERVAL is just a floor
# between decision cycles to keep the UI readable.
CYCLE_INTERVAL = AGENT_CYCLE_INTERVAL
MOVE_VELOCITY = 4.0         # wheel velocity (rad/s) for forward motion
BACKUP_VELOCITY = -3.0      # wheel velocity (rad/s) for reversing
TURN_VELOCITY = 2.0         # differential wheel velocity (rad/s) for turns
MOVE_DISTANCE = 0.6         # metres travelled per move_forward (closed-loop)
APPROACH_MOVE_DISTANCE = 0.25  # shorter step when closing in on a confirmed target
BACKUP_DISTANCE = 0.4       # metres travelled per back_up (closed-loop)
MOVE_STEP_CAP = 120         # sim-step safety cap for a single move
TURN_STEP_CAP = 160         # sim-step safety cap for a single turn

# Proximity threshold: Pioneer 3DX sonar values 0=no reading, ~800=obstacle ~0.5m away.
# Break_room walls 2m away read ~600–650; raise threshold so walls don't count as blocked.
OBSTACLE_THRESH = 800
CRITICAL_OBSTACLE_THRESH = 970

# === Target pursuit (find / approach) ===
APPROACH_DONE_FRAC = 0.18    # target bbox height ≥ this fraction of frame → roughly 1m away
APPROACH_CENTER_TOL = 0.30   # |image x-error| within this → drive straight at the target
YOLO_CONFIDENCE_STOP = 0.50   # treat YOLO as trusted enough to stop
YOLO_TARGET_REACHED_FRONT_PROXIMITY = OBSTACLE_THRESH  # centered target + blocked front ≈ close enough
YOLO_LOW_CONF_STREAK_LIMIT = 6
YOLO_RECENT_LOW_CONF_HOLD_LIMIT = 2
YOLO_RETRY_CONFIDENCE = 0.10
PURSUIT_LOST_LIMIT = 6       # steps to keep re-acquiring after losing sight of the target

# How many steps to skip LLM after a connection failure before retrying
_OLLAMA_RETRY_INTERVAL = 10
_VLM_FIND_CONFIDENCE = 0.50
_VLM_APPROACH_CONFIDENCE = 0.80
_VLM_BBOX_MIN_AREA_FRAC = 0.002

_DEFAULT_VLM_SYSTEM_PROMPT = """You are ARIA, a strict robot vision checker.

Rules:
- Report only what is visibly present in the image.
- Never invent a target that YOLO did not detect.
- If YOLO says the target is present, use the YOLO class, bbox, confidence, and frame-side hint to choose only a micro-action.
- If YOLO confidence is low, still approach the target.
- Stop only when YOLO confidence is above 0.5 and the robot is within about 1 meter.
- If the target is lost, rotate once to reacquire it, then continue exploring.
- Do not spin forever.

Return compact JSON only.
"""

_YOLO_VLM_SYSTEM_PROMPT = """You are ARIA.

You get:
- target class name
- YOLO bbox
- YOLO confidence
- frame-side hint from bbox
- robot instruction

Rules:
- YOLO confidence is ground truth.
- Do not invent objects or override YOLO.
- Answer only whether the target is visible in the current image and how to approach it.
- Keep scene_description focused on target visibility; do not provide broad room descriptions.
- Use bbox position only to choose direction:
  left -> slight left, center -> forward, right -> slight right.
- If confidence is low, still approach it.
- Keep updating the bbox every cycle.
- Stop only when confidence is above 0.5 and you are within 1 meter.
- If target is lost, rotate once to reacquire it, then continue exploring.
- Do not spin forever.

Return compact JSON:
{ action, reasoning, target_direction, target_visible_confidence, target_bbox }
"""

_YOLO_VLM_NO_DETECTION_PROMPT_SUFFIX = """If YOLO has no candidate in this frame:
- Do not treat the YOLO miss as proof the target is absent.
- Describe only the visible scene.
- Do not say 'YOLO found no target' or 'No target detected by YOLO' in scene_description or reasoning.
- If you personally cannot ground the target in the image, keep target_found=false and target_direction=not_visible.
"""


def _yolo_low_confidence_pursuit_response(
    target_close: bool,
    low_conf_streak: int,
) -> tuple[str, str, bool, bool, int]:
    """Decide what to do for a weak YOLO target hit.

    Returns:
        nav_action, nav_reason, pursuing, scanning, updated_low_conf_streak
    """
    if target_close:
        low_conf_streak += 1
        if low_conf_streak >= YOLO_LOW_CONF_STREAK_LIMIT:
            return (
                "turn_around",
                "low confidence near target — re-scan and keep exploring",
                False,
                True,
                0,
            )
        return (
            "move_forward",
            "low confidence near target — keep closing in to raise confidence",
            True,
            False,
            low_conf_streak,
        )

    return (
        "move_forward",
        "low confidence — closing in to raise confidence",
        True,
        False,
        0,
    )


def _high_confidence_target_pursuit_response(
    *,
    target_reached: bool,
    target_visual_close: bool,
    confidence: float,
    target_side: str,
    guided_action: str,
) -> tuple[str, str, bool, bool, bool]:
    """Drive toward a trusted fresh YOLO target until the stop rule is met."""
    if target_reached:
        reason = (
            "reached (visual bbox close)"
            if target_visual_close
            else "reached (centered YOLO target + front proximity)"
        )
        return "stop", reason, True, False, True

    side = target_side if target_side in ("left", "center", "right") else "visible"
    guide = f" | VLM {guided_action}" if guided_action else ""
    return (
        "move_forward",
        f"YOLO {float(confidence or 0.0):.2f} {side}{guide} — approaching visible target",
        True,
        False,
        False,
    )


_ACTIVE_VISION_MODEL: Optional[str] = None
_LAST_VLM_RETRY_USED: bool = False
_LAST_VLM_WEAK: bool = False

_VLM_RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "scene_description": {"type": "string"},
        "action": {"type": "string"},
        "target_found": {"type": "boolean"},
        "target_visible_confidence": {"type": "number"},
        "target_direction": {
            "type": "string",
            "enum": ["left", "right", "center", "not_visible"],
        },
        "target_bbox": {
            "anyOf": [
                {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 4,
                    "maxItems": 4,
                },
                {"type": "null"},
            ],
        },
        "reasoning": {"type": "string"},
    },
    "required": [
        "scene_description",
        "action",
        "target_found",
        "target_visible_confidence",
        "target_direction",
        "target_bbox",
        "reasoning",
    ],
}

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

_VLM_NON_PHYSICAL_MARKERS = {
    "statue", "statuette", "figurine", "toy", "model", "replica",
    "picture", "photo", "poster", "painting", "drawing", "image", "screen",
    "display", "icon", "logo", "illustration", "render",
}

# === System Prompt ===
_SYSTEM_PROMPT = """You are ARIA, an autonomous robot exploring a furnished room.

SENSING:
- Camera gives a raw RGB image
- 180° proximity sensors detect obstacles (value > 800 = obstacle within ~0.5m)
- GPS position and compass heading are available

ACTIONS (use EXACTLY one of these):
move_forward, turn_left_90, turn_right_90, turn_around, stop, back_up

SAFETY RULES:
1. NEVER choose move_forward if front_blocked=true
2. If target is visible in the image, only trust it when YOLO also confirms it with a matching box/class.
   If YOLO does not confirm, treat it as not found and keep exploring.

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


def _frame_side_hint_from_bbox(
    bbox: Optional[Any],
    frame_shape: Optional[Tuple[int, ...]],
) -> str:
    """Return a coarse left/center/right hint from a pixel bbox."""
    if bbox is None or frame_shape is None:
        return "not_visible"
    try:
        x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
    except Exception:
        return "not_visible"
    if x2 <= x1 or y2 <= y1 or len(frame_shape) < 2:
        return "not_visible"
    frame_w = float(frame_shape[1])
    if frame_w <= 0:
        return "not_visible"
    center_x = (x1 + x2) / 2.0
    if center_x < frame_w * 0.40:
        return "left"
    if center_x > frame_w * 0.60:
        return "right"
    return "center"


def _coerce_vlm_action(action: str) -> str:
    """Normalize loose VLM action wording into a closed action set."""
    a = (action or "").strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "left": "turn_left_45",
        "slight_left": "turn_left_45",
        "turn_left": "turn_left_45",
        "rotate_left": "turn_left_45",
        "right": "turn_right_45",
        "slight_right": "turn_right_45",
        "turn_right": "turn_right_45",
        "rotate_right": "turn_right_45",
        "forward": "move_forward",
        "advance": "move_forward",
        "probe_forward": "move_forward",
        "approach": "move_forward",
        "move_forward": "move_forward",
        "stop": "stop",
        "halt": "stop",
        "back": "back_up",
        "back_up": "back_up",
        "reacquire": "turn_around",
        "scan": "turn_around",
        "re_scan": "turn_around",
    }
    return mapping.get(a, a)


def _build_yolo_vlm_prompt(
    *,
    instruction: str,
    target: str,
    target_det: Optional[Any],
    frame_shape: Optional[Tuple[int, ...]],
    scan_result: Dict[str, Any],
    approach_mode: bool,
) -> Tuple[str, str]:
    """Build the grounded YOLO+VLM prompt pair."""
    system_prompt = _YOLO_VLM_SYSTEM_PROMPT
    if target_det is not None:
        bbox_value = getattr(target_det, "bbox", None)
        bbox = [float(v) for v in (bbox_value[:4] if bbox_value is not None else [])]
        bbox_text = "[" + ", ".join(f"{v:.0f}" for v in bbox) + "]"
        confidence = float(getattr(target_det, "confidence", 0.0))
        class_name = str(getattr(target_det, "class_name", target) or target)
        candidate_line = f"YOLO candidate class: {class_name}\n"
    else:
        bbox = None
        bbox_text = "null"
        confidence = 0.0
        class_name = "none"
        candidate_line = "YOLO candidate in this frame: none\n"
        system_prompt = f"{_YOLO_VLM_SYSTEM_PROMPT}\n{_YOLO_VLM_NO_DETECTION_PROMPT_SUFFIX}"
    frame_side = _frame_side_hint_from_bbox(bbox, frame_shape)
    frame_size = "unknown"
    if frame_shape is not None and len(frame_shape) >= 2:
        frame_size = f"{int(frame_shape[1])}x{int(frame_shape[0])}"

    user_prompt = (
        f"Instruction: {instruction}\n"
        f"Target: {target}\n"
        f"{candidate_line}"
        f"YOLO confidence: {confidence:.2f}\n"
        f"YOLO bbox: {bbox_text}\n"
        f"Frame side hint: {frame_side}\n"
        f"Frame size: {frame_size}\n"
        f"Approach mode: {str(bool(approach_mode)).lower()}\n"
        f"Proximity front={float(scan_result.get('front', 0.0)):.0f} "
        f"left={float(scan_result.get('left', 0.0)):.0f} "
        f"right={float(scan_result.get('right', 0.0)):.0f}\n"
        "Return one compact JSON object only with keys:\n"
        "scene_description, reasoning, action, target_found, "
        "target_visible_confidence, target_direction, target_bbox.\n"
        "Use the provided YOLO information as truth."
    )
    return system_prompt, user_prompt


def _sanitize_yolo_vlm_text(text: str, *, target_det_present: bool) -> str:
    """Strip prompt-parroting text when YOLO had no candidate."""
    cleaned = (text or "").strip()
    if target_det_present or not cleaned:
        return cleaned
    lowered = cleaned.lower()
    banned_fragments = (
        "detected by yolo",
        "yolo found no target",
        "no target detected by yolo",
        "frame side hint indicates not_visible",
    )
    if any(fragment in lowered for fragment in banned_fragments):
        return "No grounded target in this frame; continuing exploration."
    return cleaned


def _should_query_vlm_after_yolo(perception_mode: str, detections: List[Any]) -> bool:
    """In yolo_vlm mode, VLM should wait until YOLO produced classes for the frame."""
    if perception_mode != "yolo_vlm":
        return True
    return bool(detections)


def _should_retry_yolo_for_target(detections: List[Any], target_aliases: set[str]) -> bool:
    """Retry the same frame when the first pass missed the requested target."""
    if not detections:
        return True
    for det in detections:
        if str(getattr(det, "class_name", "") or "").lower() in target_aliases:
            return False
    return True


def _enhance_yolo_retry_frame(frame_bgr: np.ndarray) -> np.ndarray:
    """Make a same-frame retry a little friendlier for small/far household objects."""
    if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
        return frame_bgr
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    boosted_l = clahe.apply(l_channel)
    merged = cv2.merge((boosted_l, a_channel, b_channel))
    enhanced = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
    sharpen_kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    return cv2.filter2D(enhanced, -1, sharpen_kernel)


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


def _vision_prompt(
    goal: str,
    target: str,
    scan_result: Dict[str, Any],
    front_blocked: bool,
    approach_mode: bool,
    perception_mode: str,
) -> str:
    """Prompt the VLM for scene understanding and target visibility."""
    return (
        f"Goal: {goal}\n"
        f"Target to search for: {target}\n"
        "Image size: 320 pixels wide x 240 pixels high.\n"
        f"Robot navigation mode: {'approach' if approach_mode else 'find'}\n"
        f"Perception mode: {perception_mode}\n"
        f"Front blocked: {front_blocked}\n"
        f"Proximity front={scan_result['front']:.0f} left={scan_result['left']:.0f} "
        f"right={scan_result['right']:.0f}\n"
        "Look at the image from the robot's perspective and answer with compact JSON only.\n"
        "In scene_description, describe only visible scene contents; do not mention the search goal.\n"
        "Do not guess. Only set target_found=true if the target is unmistakably visible as a physical object.\n"
        "Do not infer the target from the prompt, labels, furniture, shadows, or nearby objects.\n"
        "If you mention the target in reasoning or scene_description without a grounded pixel box, "
        "treat that as NOT_FOUND and keep exploring.\n"
        "If target_found=true, include a tight pixel bounding box inside the image: "
        "x1,y1,x2,y2 with x in 0..319 and y in 0..239. Do not return normalized 0..1 boxes.\n"
        "If you are unsure, set target_found=false, target_visible_confidence=0, "
        "target_direction='not_visible', target_bbox=null.\n"
        "Return exactly these keys:\n"
        '{"scene_description":"1-2 short sentences about what the robot sees",'
        '"target_found":true/false,'
        '"target_visible_confidence":0.0-1.0,'
        '"target_direction":"left|right|center|not_visible",'
        '"target_bbox":[x1,y1,x2,y2] or null,'
        '"reasoning":"one short sentence explaining the next move"}'
    )


def _normalize_vlm_bbox(
    target_bbox: Any,
    frame_shape: Optional[Tuple[int, ...]],
) -> Optional[Tuple[float, float, float, float]]:
    """Return an in-frame pixel bbox, accepting native pixels or Qwen 0..1000 boxes."""
    if not isinstance(frame_shape, tuple) or len(frame_shape) < 2:
        return None
    if not isinstance(target_bbox, (list, tuple)) or len(target_bbox) != 4:
        return None
    try:
        x1, y1, x2, y2 = [float(v) for v in target_bbox]
    except (TypeError, ValueError):
        return None
    frame_h = float(frame_shape[0])
    frame_w = float(frame_shape[1])
    if frame_h <= 0 or frame_w <= 0:
        return None
    if not (0.0 <= x1 < x2 and 0.0 <= y1 < y2):
        return None

    coords = (x1, y1, x2, y2)
    if all(0.0 <= v <= 1.0 for v in coords):
        return None

    if x2 <= frame_w and y2 <= frame_h:
        px_bbox = coords
    elif max(coords) <= 1000.0:
        px_bbox = (
            x1 / 1000.0 * frame_w,
            y1 / 1000.0 * frame_h,
            x2 / 1000.0 * frame_w,
            y2 / 1000.0 * frame_h,
        )
    else:
        return None

    x1, y1, x2, y2 = px_bbox
    if not (0.0 <= x1 < x2 <= frame_w and 0.0 <= y1 < y2 <= frame_h):
        return None
    area_frac = ((x2 - x1) * (y2 - y1)) / (frame_w * frame_h)
    if area_frac < _VLM_BBOX_MIN_AREA_FRAC:
        return None
    return px_bbox


def _vlm_bbox_is_valid(target_bbox: Any, frame_shape: Optional[Tuple[int, ...]]) -> bool:
    """True only when the VLM provides a real, in-frame box."""
    return _normalize_vlm_bbox(target_bbox, frame_shape) is not None


def _accept_vlm_target_claim(
    target_found: bool,
    target_visible_confidence: float,
    target_direction: str,
    target_bbox: Any,
    frame_shape: Optional[Tuple[int, ...]],
    min_confidence: float = _VLM_FIND_CONFIDENCE,
) -> bool:
    """Only trust a VLM target claim when it is very explicit and localizable."""
    if not target_found:
        return False
    if float(target_visible_confidence or 0.0) < min_confidence:
        return False
    bbox = _normalize_vlm_bbox(target_bbox, frame_shape)
    if bbox is None:
        return False
    if isinstance(frame_shape, tuple) and len(frame_shape) >= 2:
        frame_h = float(frame_shape[0])
        _, y1, _, y2 = bbox
        center_y = (y1 + y2) / 2.0
        # Reject ceiling-hugging claims unless confidence is strong enough.
        if center_y < frame_h * 0.12 and float(target_visible_confidence or 0.0) < 0.70:
            return False
    return True


def _direction_to_err(direction: str) -> float:
    """Convert an image-relative direction into the same sign convention used by YOLO."""
    direction = (direction or "").strip().lower()
    if direction == "right":
        return 1.0
    if direction == "left":
        return -1.0
    return 0.0


def _vlm_text_mentions_target(text: str, aliases: List[str]) -> bool:
    """True when a VLM text answer mentions the target name, even if no box is present."""
    if not text:
        return False
    lowered = text.lower()
    if any(marker in lowered for marker in _VLM_NON_PHYSICAL_MARKERS):
        return False
    for alias in aliases:
        alias = (alias or "").strip().lower()
        if not alias:
            continue
        if " " in alias:
            if alias in lowered:
                return True
        elif re.search(rf"\b{re.escape(alias)}\b", lowered):
            return True
    return False


def _vlm_text_only_hint_is_actionable(text_only_hint: bool, target_found: bool) -> bool:
    """Text-only target mentions are never actionable without a grounded claim."""
    return bool(text_only_hint and target_found)


def _vlm_hint_action(direction: str, repeat_count: int) -> Tuple[str, str]:
    """Convert a weak text-only VLM hint into a bounded navigation action."""
    d = (direction or "not_visible").lower()
    if d == "left":
        if repeat_count > 0:
            return "move_forward", "VLM hint repeated on left without grounding — probing forward"
        return "turn_left_45", "VLM hint: target on left — reorienting"
    if d == "right":
        if repeat_count > 0:
            return "move_forward", "VLM hint repeated on right without grounding — probing forward"
        return "turn_right_45", "VLM hint: target on right — reorienting"
    return "move_forward", "VLM hint: target in view — probing forward"


def _target_close_enough(target_bbox_frac: float) -> bool:
    """True when visual target size, not proximity sensors, says approach is done."""
    return float(target_bbox_frac or 0.0) >= APPROACH_DONE_FRAC


def _target_reached_by_yolo(
    *,
    target_bbox_frac: float,
    target_err: float,
    confidence: float,
    scan_result: Dict[str, Any],
) -> bool:
    """True when a fresh YOLO target is close enough to stop.

    Bbox height works well for compact objects, but tall/thin objects like
    plants can trigger front proximity before their box reaches the visual
    size threshold. In that case, only accept proximity if the trusted YOLO box
    is centered, so safety recovery does not turn away from the target.
    """
    if _target_close_enough(target_bbox_frac):
        return True
    try:
        front_proximity = float(scan_result.get("front", 0.0) or 0.0)
    except (TypeError, ValueError):
        front_proximity = 0.0
    return (
        float(confidence or 0.0) >= YOLO_CONFIDENCE_STOP
        and abs(float(target_err or 0.0)) <= APPROACH_CENTER_TOL
        and front_proximity >= YOLO_TARGET_REACHED_FRONT_PROXIMITY
    )


def _summarize_vision_text(text: str, limit: int = 160) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _append_recent_vision(recent_vision: List[str], summary: str, limit: int = 4) -> List[str]:
    item = _summarize_vision_text(summary, limit=180)
    if not item:
        return recent_vision
    next_items = [x for x in recent_vision if x != item]
    next_items.append(item)
    return next_items[-limit:]


def _vision_memory_summary(recent_vision: List[str]) -> str:
    if not recent_vision:
        return "no recent visual memory"
    return " | ".join(recent_vision[-3:])

    memory_hint = _vision_memory_summary(recent_vision)
    if not reasoning_hint:
        reasoning_hint = f"live-map exploration | recent vision: {memory_hint}"
    if not vision_summary:
        vision_summary = "No fresh image analysis this cycle."
    if not target_found and target_det is None and not pursuing:
        reasoning_hint = f"{reasoning_hint} | correction: keep exploring".strip()

    return (
        nav_action,
        nav_reason,
        target_done,
        exploration_done,
        scanning,
        pursuit_lost,
        active_frontier,
        last_seen_err,
        target_err,
        vision_summary,
        reasoning_hint,
        memory_hint,
    )


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
        return frame_bgr
    except Exception as e:
        print(f"[ARIA] Camera decode error: {e}")
        return None


def _frame_to_jpeg_b64(frame_bgr: np.ndarray, quality: int = 90) -> Optional[str]:
    try:
        frame_bgr = prepare_vision_frame(frame_bgr, target_max_dim=max(32, OLLAMA_VISION_IMAGE_MAX_DIM))
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


def _query_vision_model(
    jpeg_b64: Optional[str],
    user_prompt: str,
    *,
    system_prompt: Optional[str] = None,
    response_schema: Optional[Dict[str, Any]] = None,
) -> str:
    global _LAST_VLM_RETRY_USED
    global _LAST_VLM_WEAK
    _LAST_VLM_RETRY_USED = False
    _LAST_VLM_WEAK = False
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    user_msg: Dict[str, Any] = {"role": "user", "content": user_prompt}
    if jpeg_b64:
        user_msg["images"] = [jpeg_b64]
    model_name = _ACTIVE_VISION_MODEL or OLLAMA_VISION_MODEL
    base_payload = {
        "model": model_name,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": system_prompt or _DEFAULT_VLM_SYSTEM_PROMPT,
            },
            user_msg,
        ],
        "options": {
            "temperature": 0.0,
            "num_predict": OLLAMA_VISION_NUM_PREDICT,
            "num_ctx": 2048,
        },
        "keep_alive": "10m",
    }

    def _chat(payload: Dict[str, Any]) -> str:
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
            raise RuntimeError(f"empty response from {model_name}")
        return text

    def _safe_vlm_fallback() -> str:
        global _LAST_VLM_WEAK
        _LAST_VLM_WEAK = True
        return json.dumps({
            "scene_description": "No reliable vision response available.",
            "action": "move_forward",
            "target_found": False,
            "target_visible_confidence": 0.0,
            "target_direction": "not_visible",
            "target_bbox": None,
            "reasoning": "Vision model did not return a usable final answer; continue exploring.",
        })

    try:
        return _chat({**base_payload, "format": response_schema or _VLM_RESPONSE_SCHEMA})
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        if e.code == 400:
            _LAST_VLM_RETRY_USED = True
            print(
                f"[ARIA] VLM strict-schema request rejected for {model_name}; "
                "retrying with plain JSON prompt. "
                f"Body={body[:240]!r}"
            )
            return _chat({**base_payload, "format": "json"})
        raise
    except RuntimeError as e:
        if "empty response" in str(e):
            print(f"[ARIA] VLM returned no final text for {model_name}; using fallback JSON.")
            return _safe_vlm_fallback()
        raise


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


def _should_sample_vlm(
    perception_mode: str,
    frame_present: bool,
    step: int,
    last_llm_ts: float,
    cycle_start: float,
    backoff_until_step: int,
) -> bool:
    """Decide whether to query the local VLM this cycle.

    `vlm_first` should sample every cycle so the robot does not spend many
    frontier steps before the first grounded scene read. `yolo_vlm` also
    samples every cycle so each action can be grounded in the latest box/class
    pair. Other hybrid modes can stay throttled to keep cost lower.
    """
    if not USE_LLM:
        return False
    if perception_mode == "sensor_only" or not frame_present:
        return False
    if step < backoff_until_step:
        return False
    if perception_mode in ("vlm_first", "yolo_vlm"):
        return True
    if step <= 1:
        return False
    return (cycle_start - last_llm_ts) >= OLLAMA_VISION_SAMPLE_INTERVAL


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


def _execute_motion(action: str, approach_mode: bool = False) -> Dict[str, Any]:
    """Issue one closed-loop motion. Each call blocks until the controller has
    reached the sensor goal and stopped the wheels — no agent-side sleeps.

    Returns the controller feedback for the *primary* motion (distance_traveled,
    degrees_turned, reached_target, …) so the caller can log whether the robot
    actually translated/rotated as commanded."""
    if action == "move_forward":
        distance = APPROACH_MOVE_DISTANCE if approach_mode else MOVE_DISTANCE
        return _fwd(distance=distance)
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


def _extract_robot_state(result: Any) -> Dict[str, Any]:
    """Normalize a get_state response into a robot-state dict."""
    if not isinstance(result, dict):
        return {}
    if result.get("success") or "state" in result:
        state = result.get("state", {})
        return state if isinstance(state, dict) else {}
    return {}


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
    perception_mode: str = PERCEPTION_MODE,
    event_callback: Optional[Callable[[Dict], None]] = None,
) -> AgentState:
    """Public entry: tees all output to a per-run log file, then runs the
    agent.  stdout is always restored, even on error."""
    orig_stdout = sys.stdout
    orig_stderr = sys.stderr
    global _ACTIVE_VISION_MODEL
    prev_vision_model = _ACTIVE_VISION_MODEL
    _ACTIVE_VISION_MODEL = OLLAMA_VISION_MODEL
    logf = _open_run_log(goal)
    if logf is not None:
        log_stream = _TimestampedFile(logf)
        sys.stdout = _Tee(orig_stdout, log_stream)
        sys.stderr = _Tee(orig_stderr, log_stream)
    try:
        return _run_aria_agent_impl(goal, max_steps, model, perception_mode, event_callback)
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
        _ACTIVE_VISION_MODEL = prev_vision_model
        sys.stdout = orig_stdout
        sys.stderr = orig_stderr
        if logf is not None:
            try:
                logf.close()
            except Exception:
                pass


def _run_aria_agent_impl(
    goal: str,
    max_steps: int = 100,
    model: str = OLLAMA_MODEL,
    perception_mode: str = PERCEPTION_MODE,
    event_callback: Optional[Callable[[Dict], None]] = None,
) -> AgentState:

    target = _extract_target(goal)
    target_aliases = _target_aliases(target)
    approach_mode = _wants_approach(goal)   # drive to target vs just stop on sight
    camera = get_camera_manager()
    detector = None
    env_graph = get_environment_graph()

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

    def _prefer_forward_frontier(cur_xy, frontier_xy, prox: Dict[str, float]):
        """If the frontier only asks for a turn, try the open corridor ahead
        first so exploration keeps translating through the room."""
        action, dist = _plan_action(cur_xy, frontier_xy)
        if action.startswith("turn_") and not front_blocked:
            open_target = omap.open_direction_target(
                cur_xy[0], cur_xy[1], heading_deg, prox, reach=1.0
            )
            open_action, _ = _plan_action(cur_xy, open_target)
            if open_action == "move_forward":
                return open_action, dist, "forward-open fallback"
        return action, dist, None

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
    vlm_hint_repeat_count = 0
    low_conf_streak = 0
    last_yolo_target_seen_step = 0
    last_yolo_target_confidence = 0.0

    # VLM is an optional refinement layer. The live occupancy grid is the real
    # navigation backbone, so we only pay for image analysis periodically.
    last_llm_ts = 0.0
    vlm_weak_streak = 0
    vlm_backoff_until_step = 0

    state = AgentState(goal=goal, step_count=0, success=False)
    objects_seen: List[str] = []

    print(f"\n[ARIA] Goal: {goal}")
    print(f"[ARIA] Target: {target}  aliases: {sorted(target_aliases)}  "
          f"mode: {'APPROACH (drive to it)' if approach_mode else 'FIND (stop on sight)'}")
    print(f"[ARIA] Model: {model}")
    print(f"[ARIA] Perception: {perception_mode}")
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
            robot_state_raw = _extract_robot_state(result)
            if not robot_state_raw:
                message = result.get("error", "unknown") if isinstance(result, dict) else "no response"
                print(f"[ARIA] get_state error: {message}")
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
        # DECODE CAMERA + PERCEPTION
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
        vision_frame = prepare_vision_frame(frame_bgr) if frame_bgr is not None else None

        detections = []
        annotated_frame = vision_frame
        detection_dicts: List[Dict[str, Any]] = []

        vision_summary = ""
        reasoning_hint = ""
        vlm_action = ""
        raw_vlm = ""
        perception_source = "sensor"
        perception_fresh = False
        target_found = False
        target_visible_confidence = 0.0
        target_direction = "not_visible"
        target_bbox = None
        target_det = None
        target_source = "sensor"
        target_err = 0.0      # normalized horizontal offset of target in image, [-1..1]
        target_frac = 0.0     # target bbox height / frame height (proximity proxy)
        yolo_prefetched = False

        should_try_vlm = _should_sample_vlm(
            perception_mode=perception_mode,
            frame_present=frame_bgr is not None,
            step=step,
            last_llm_ts=last_llm_ts,
            cycle_start=cycle_start,
            backoff_until_step=vlm_backoff_until_step,
        )

        if should_try_vlm and not _ollama_reachable():
            print("[ARIA] VLM unreachable (fast check) — waiting this cycle")
            should_try_vlm = False

        if vision_frame is not None and perception_mode == "yolo_vlm":
            try:
                if detector is None:
                    detector = get_detector()
                if getattr(detector, "is_open_vocab", False):
                    common_classes = set(detector.get_common_classes())
                    common_classes.update(target_aliases)
                    common_classes.update({
                        "dog", "cat", "horse", "sheep", "cow", "bear", "elephant", "zebra", "giraffe",
                        "sports ball", "bottle", "cup", "chair", "person", "potted plant", "box",
                        "wooden box", "cardboard box", "duck", "rubber duck",
                    })
                    detector.set_classes(sorted(common_classes))
                detections = detector.detect(vision_frame)
                if _should_retry_yolo_for_target(detections, target_aliases):
                    retry_frame = _enhance_yolo_retry_frame(vision_frame)
                    retry_detections = detector.detect(
                        retry_frame,
                        confidence_threshold=min(
                            float(getattr(detector, "confidence_threshold", YOLO_RETRY_CONFIDENCE)),
                            YOLO_RETRY_CONFIDENCE,
                        ),
                    )
                    retry_has_target = any(
                        str(getattr(det, "class_name", "") or "").lower() in target_aliases
                        for det in retry_detections
                    )
                    first_has_target = any(
                        str(getattr(det, "class_name", "") or "").lower() in target_aliases
                        for det in detections
                    )
                    if retry_has_target or (not detections and retry_detections):
                        detections = retry_detections
                    elif (not first_has_target) and len(retry_detections) > len(detections):
                        detections = retry_detections
                annotated_frame = detector.visualize_detections(vision_frame, detections)
                yolo_prefetched = True
                perception_source = "yolo"
                detection_dicts = [_detection_to_dict(d) for d in detections]
                detected_names = [d.class_name for d in detections]
                for name in detected_names:
                    if name not in objects_seen:
                        objects_seen.append(name)
                print("[ARIA] YOLO pre-pass:")
                for d in detections[:10]:
                    print(f"  {d.class_name} conf={d.confidence:.2f}")
                if not detections:
                    print("  (none)")
                if position[0] != 0.0 or position[1] != 0.0:
                    for d in detections:
                        spatial_mem.record(
                            d.class_name.lower(),
                            position[0], position[1],
                            float(d.confidence),
                        )
                for d in detections:
                    if d.class_name.lower() in target_aliases:
                        if target_det is None or d.confidence > target_det.confidence:
                            target_det = d
                if target_det is not None:
                    target_found = True
                    target_source = "yolo"
                    target_visible_confidence = float(getattr(target_det, "confidence", 0.0))
                    fh, fw = vision_frame.shape[0], vision_frame.shape[1]
                    x1, y1, x2, y2 = target_det.bbox
                    target_err = (target_det.center[0] - fw / 2.0) / (fw / 2.0)
                    target_frac = (y2 - y1) / float(fh)
                    target_direction = _frame_side_hint_from_bbox(target_det.bbox, vision_frame.shape)
                    vision_summary = (
                        f"YOLO saw {target_det.class_name} conf={target_visible_confidence:.2f} "
                        f"on the {target_direction}"
                    )
                    reasoning_hint = (
                        f"YOLO box is {target_direction}; use the box to steer and keep approaching."
                    )
                    last_yolo_target_seen_step = step
                    last_yolo_target_confidence = target_visible_confidence
                    print(
                        f"[ARIA] YOLO target match: {target_det.class_name} "
                        f"conf={target_visible_confidence:.2f} side={target_direction}"
                    )
                else:
                    vision_summary = "YOLO found no target match; keep exploring."
                    reasoning_hint = "No YOLO target yet; keep exploring the live map."
            except Exception as e:
                print(f"[ARIA] YOLO pre-pass error: {e}")

        if perception_mode == "yolo_vlm" and should_try_vlm and not _should_query_vlm_after_yolo(
            perception_mode,
            detections,
        ):
            print("[ARIA] Skipping VLM — YOLO produced no classes for this frame")
            should_try_vlm = False
            if not vision_summary:
                vision_summary = "YOLO produced no classes for this frame."
            if not reasoning_hint:
                reasoning_hint = "No YOLO classes to pass to VLM; keep exploring with the live map."

        if should_try_vlm:
            last_llm_ts = cycle_start
            try:
                jpeg_b64 = _frame_to_jpeg_b64(vision_frame) if vision_frame is not None else None
                _emit(event_callback, {
                    "type": "vision_wait",
                    "step": step,
                    "model": _ACTIVE_VISION_MODEL or OLLAMA_VISION_MODEL,
                    "message": "waiting for VLM",
                    "vision": "Waiting for VLM response...",
                })
                if perception_mode == "yolo_vlm":
                    system_prompt, user_prompt = _build_yolo_vlm_prompt(
                        instruction=goal,
                        target=target,
                        target_det=target_det,
                        frame_shape=vision_frame.shape if vision_frame is not None else None,
                        scan_result=scan_result,
                        approach_mode=approach_mode,
                    )
                else:
                    system_prompt = _DEFAULT_VLM_SYSTEM_PROMPT
                    user_prompt = (
                        f"Goal: {goal}.\n"
                        f"Target aliases: {sorted(target_aliases)}\n"
                        f"Current navigation plan: {nav_reason or 'none yet'}\n"
                        f"Front blocked: {front_blocked}\n"
                        f"Proximity front={scan_result['front']:.0f} "
                        f"left={scan_result['left']:.0f} right={scan_result['right']:.0f}\n"
                        f"Known detections: {[d['class_name'] for d in detection_dicts[:10]]}\n"
                        "Return ONE compact JSON object only with keys:\n"
                        "scene_description, reasoning, target_found, target_visible_confidence,\n"
                        "target_direction, target_bbox, action.\n"
                        "Rules:\n"
                        "- target_found=true only if the real target is visible now.\n"
                        "- target_direction must be left, right, center, or not_visible.\n"
                        "- target_bbox must be pixel coords [x1,y1,x2,y2] for the real target, or null.\n"
                        "- If target is only mentioned in text/labels/context, set target_found=false.\n"
                        "- If target is visible but you cannot localize it, set target_found=false and target_direction=not_visible.\n"
                        "- Do not label statues, pictures, logos, or screens as the target."
                    )
                raw_vlm = _query_vision_model(
                    jpeg_b64,
                    user_prompt,
                    system_prompt=system_prompt,
                )
                parsed_vlm = _extract_json(raw_vlm) or {}
                if parsed_vlm:
                    perception_fresh = True
                    perception_source = "yolo_vlm" if perception_mode == "yolo_vlm" else "vlm"
                    vlm_action = str(parsed_vlm.get("action", "") or "").strip().lower()
                    vision_summary = str(
                        parsed_vlm.get("scene_description")
                        or parsed_vlm.get("vision")
                        or parsed_vlm.get("reasoning")
                        or raw_vlm
                    )
                    reasoning_hint = str(parsed_vlm.get("reasoning") or vision_summary)
                    if perception_mode == "yolo_vlm":
                        vision_summary = _sanitize_yolo_vlm_text(
                            vision_summary,
                            target_det_present=target_det is not None,
                        )
                        reasoning_hint = _sanitize_yolo_vlm_text(
                            reasoning_hint,
                            target_det_present=target_det is not None,
                        )
                    if perception_mode == "yolo_vlm":
                        target_claimed = bool(parsed_vlm.get("target_found", False))
                        if target_det is not None:
                            target_visible_confidence = float(getattr(target_det, "confidence", 0.0))
                            target_direction = _frame_side_hint_from_bbox(
                                getattr(target_det, "bbox", None),
                                vision_frame.shape if vision_frame is not None else None,
                            )
                            target_bbox = list(getattr(target_det, "bbox", None) or [])
                            if not target_bbox:
                                target_bbox = None
                        else:
                            target_visible_confidence = float(
                                parsed_vlm.get("target_visible_confidence", 0.0) or 0.0
                            )
                            target_direction = str(
                                parsed_vlm.get("target_direction", "not_visible") or "not_visible"
                            ).lower()
                            target_bbox = parsed_vlm.get("target_bbox")
                        if target_claimed and target_det is None:
                            print("[ARIA] VLM target claim ignored; no YOLO match")
                            reasoning_hint = (
                                f"{reasoning_hint} VLM target claim ignored because YOLO had no match."
                            ).strip()
                        elif target_det is not None:
                            reasoning_hint = (
                                f"{reasoning_hint} YOLO confidence={target_visible_confidence:.2f}; "
                                f"frame-side={target_direction}."
                            ).strip()
                    else:
                        target_claimed = bool(parsed_vlm.get("target_found", False))
                        target_visible_confidence = float(parsed_vlm.get("target_visible_confidence", 0.0) or 0.0)
                        target_direction = str(parsed_vlm.get("target_direction", "not_visible") or "not_visible").lower()
                        target_bbox = parsed_vlm.get("target_bbox")
                        frame_shape = vision_frame.shape if vision_frame is not None else None
                        vlm_min_confidence = (
                            _VLM_APPROACH_CONFIDENCE if approach_mode else _VLM_FIND_CONFIDENCE
                        )
                        normalized_target_bbox = _normalize_vlm_bbox(target_bbox, frame_shape)
                        target_found = _accept_vlm_target_claim(
                            target_claimed,
                            target_visible_confidence,
                            target_direction,
                            target_bbox,
                            frame_shape,
                            min_confidence=vlm_min_confidence,
                        )
                        if target_found:
                            target_bbox = list(normalized_target_bbox or target_bbox)
                        elif target_claimed:
                            raw_summary = vision_summary
                            print(
                                "[ARIA] VLM target claim rejected "
                                f"(conf={target_visible_confidence:.2f}, bbox={target_bbox})"
                            )
                            vision_summary = (
                                "VLM target claim rejected; continuing exploration. "
                                f"Raw scene: {raw_summary}"
                            )
                            target_direction = "not_visible"
                            target_bbox = None
                            reasoning_hint = (
                                f"{reasoning_hint} "
                                "Target claim rejected; keep exploring."
                            ).strip()
                            vlm_weak_streak += 1
                            state.correction_count += 1
                    print(f"[ARIA] VLM: { _summarize_vision_text(vision_summary) }")
                    state.recent_vision = _append_recent_vision(state.recent_vision, vision_summary)
                    _emit(event_callback, {
                        "type": "vision",
                        "step": step,
                        "description": vision_summary,
                        "source": perception_source,
                        "fresh": True,
                        "retry_used": _LAST_VLM_RETRY_USED,
                        "model": _ACTIVE_VISION_MODEL or OLLAMA_VISION_MODEL,
                    })
                else:
                    print("[ARIA] VLM returned non-JSON output; relying on fallback perception")
                    vlm_weak_streak += 1
                    state.correction_count += 1
            except Exception as e:
                print(f"[ARIA] VLM error: {type(e).__name__}: {e}")
                vlm_weak_streak += 1
                state.correction_count += 1

            if vlm_weak_streak >= 2:
                vlm_backoff_until_step = step + 2
                print(
                    f"[ARIA] VLM correction → back off until step {vlm_backoff_until_step} "
                    f"(weak_streak={vlm_weak_streak}, corrections={state.correction_count})"
                )
                vlm_weak_streak = 0

        vlm_text_only_hint = (
            frame_bgr is not None
            and not target_found
            and (
                _vlm_text_mentions_target(raw_vlm, target_aliases)
                or _vlm_text_mentions_target(vision_summary, target_aliases)
            )
        )
        vlm_target_hint = bool(target_found)
        vlm_target_hint_direction = (
            target_direction if vlm_target_hint and target_direction != "not_visible" else "not_visible"
        )
        if vlm_text_only_hint:
            print("[ARIA] VLM text-only target mention ignored; no grounded bbox")
            if not reasoning_hint:
                reasoning_hint = "VLM mentioned the target without a grounded box; keep exploring."
            else:
                reasoning_hint = (
                    f"{reasoning_hint} VLM mention lacked grounding; keep exploring."
                ).strip()
            state.correction_count += 1
        fallback_needed = (
            frame_bgr is not None
            and perception_mode == "yolo_vlm"
            and not yolo_prefetched
            and (
                not target_found
                or target_visible_confidence < _VLM_FIND_CONFIDENCE
                or (approach_mode and target_found and target_bbox is None)
            )
        )

        if fallback_needed:
            try:
                if detector is None:
                    detector = get_detector()
                if getattr(detector, "is_open_vocab", False):
                    common_classes = set(detector.get_common_classes())
                    common_classes.update(target_aliases)
                    common_classes.update({
                        "dog", "cat", "horse", "sheep", "cow", "bear", "elephant", "zebra", "giraffe",
                        "sports ball", "bottle", "cup", "chair", "person", "potted plant", "box",
                        "wooden box", "cardboard box", "duck", "rubber duck",
                    })
                    detector.set_classes(sorted(common_classes))
                detections = detector.detect(vision_frame)
                annotated_frame = detector.visualize_detections(vision_frame, detections)
                if not perception_fresh:
                    perception_source = "yolo"
                detected_names = [d.class_name for d in detections]
                for name in detected_names:
                    if name not in objects_seen:
                        objects_seen.append(name)
                print("[ARIA] YOLO fallback:")
                for d in detections[:10]:
                    print(f"  {d.class_name} conf={d.confidence:.2f}")
                if not detections:
                    print("  (none)")
                if position[0] != 0.0 or position[1] != 0.0:
                    for d in detections:
                        spatial_mem.record(
                            d.class_name.lower(),
                            position[0], position[1],
                            float(d.confidence),
                        )

                detection_dicts = [_detection_to_dict(d) for d in detections]
                for d in detections:
                    if d.class_name.lower() in target_aliases:
                        if target_det is None or d.confidence > target_det.confidence:
                            target_det = d
                if target_det is not None:
                    target_found = True
                    target_source = "yolo"
                    target_visible_confidence = float(getattr(target_det, "confidence", 0.0))
                    fh, fw = vision_frame.shape[0], vision_frame.shape[1]
                    x1, y1, x2, y2 = target_det.bbox
                    target_err = (target_det.center[0] - fw / 2.0) / (fw / 2.0)
                    target_frac = (y2 - y1) / float(fh)
                    if not vision_summary:
                        vision_summary = "YOLO fallback saw the target."
                    if not reasoning_hint:
                        reasoning_hint = "YOLO fallback confirmed the target."
                    last_yolo_target_seen_step = step
                    last_yolo_target_confidence = target_visible_confidence
            except Exception as e:
                print(f"[ARIA] YOLO error: {e}")

        # VLM target pursuit needs a real, normalized image box. Text-only
        # sightings are logged as observations but must not end the search.
        if target_det is None and target_found and target_direction != "not_visible":
            target_source = "vlm"
            if frame_bgr is not None:
                fh, fw = frame_bgr.shape[0], frame_bgr.shape[1]
                normalized_bbox = _normalize_vlm_bbox(target_bbox, frame_bgr.shape)
                if normalized_bbox is not None:
                    x1, y1, x2, y2 = normalized_bbox
                    x_center = (x1 + x2) / 2.0
                    target_err = (x_center - fw / 2.0) / (fw / 2.0)
                    target_frac = max(0.0, (y2 - y1) / float(fh))
                    target_bbox = [x1, y1, x2, y2]
                    target_det = SimpleNamespace(
                        class_name=target,
                        confidence=max(0.0, min(1.0, target_visible_confidence or 0.6)),
                        bbox=(x1, y1, x2, y2),
                        center=(x_center, (y1 + y2) / 2.0),
                        class_id=-1,
                    )

        if target_found and target_source == "vlm" and target_det is None:
            target_found = False
            target_direction = "not_visible"
            target_bbox = None
            reasoning_hint = (
                f"{reasoning_hint} VLM claim had no grounded bbox; continuing exploration."
            ).strip()

        if target_found and target_source == "vlm" and target_det is not None:
            yolo_confirmed = any(
                d.class_name.lower() in target_aliases for d in detections
            )
            if not yolo_confirmed:
                print("[ARIA] VLM target claim not confirmed by YOLO; rejecting")
                target_found = False
                target_source = "vlm_rejected"
                target_det = None
                target_direction = "not_visible"
                target_bbox = None
                target_visible_confidence = 0.0
                reasoning_hint = (
                    f"{reasoning_hint} YOLO did not confirm the target; keep exploring."
                ).strip()
                vision_summary = (
                    f"{vision_summary} | VLM claim rejected by YOLO confirmation check."
                ).strip(" |")
                state.correction_count += 1

        if not detection_dicts and target_det is not None:
            detection_dicts = [_detection_to_dict(target_det)]

        wait_for_vlm_answer = bool(
            should_try_vlm and not perception_fresh and perception_mode == "vlm_first"
        )
        if wait_for_vlm_answer:
            nav_action = "stop"
            nav_reason = "waiting for grounded VLM answer"

        agent_camera_jpeg = None
        if annotated_frame is not None:
            agent_camera_jpeg = _frame_to_jpeg_b64(annotated_frame, quality=80)
        if agent_camera_jpeg:
            _emit(
                event_callback,
                {
                    "type": "camera",
                    "step": step,
                    "captured_at": time.time(),
                    "robot_timestamp": float(timestamp),
                    "data": agent_camera_jpeg,
                    "width": int(annotated_frame.shape[1]),
                    "height": int(annotated_frame.shape[0]),
                    "detections": detection_dicts[:20],
                    "graph_stats": env_graph.get_stats() if hasattr(env_graph, "get_stats") else {},
                    "source": "agent",
                    "perception_mode": perception_mode,
                },
            )

        if not vision_summary:
            if perception_fresh:
                vision_summary = reasoning_hint or "VLM reported no usable scene summary."
            elif detections:
                names = [d.class_name for d in detections[:5]]
                vision_summary = f"YOLO fallback saw: {', '.join(names)}"
            else:
                vision_summary = "No fresh image analysis this cycle."

        if not reasoning_hint:
            if target_found and target_source == "vlm":
                reasoning_hint = "VLM sees the target and the robot will use that to decide the next move."
            elif detections:
                reasoning_hint = "No VLM result yet; using fallback detections and live map navigation."
            else:
                reasoning_hint = "No image target detected; keep exploring with the live map."

        state.recent_vision = _append_recent_vision(state.recent_vision, vision_summary)

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
            vlm_hint_repeat_count = 0
            scanning = False                      # abort any scan — we found it
            tconf = float(getattr(target_det, "confidence", 0.0))
            low_conf = tconf < YOLO_CONFIDENCE_STOP
            target_visual_close = _target_close_enough(target_frac)
            target_reached = _target_reached_by_yolo(
                target_bbox_frac=target_frac,
                target_err=target_err,
                confidence=tconf,
                scan_result=scan_result,
            )
            target_side = _frame_side_hint_from_bbox(
                getattr(target_det, "bbox", None),
                frame_bgr.shape if frame_bgr is not None else None,
            )
            guided_action = _coerce_vlm_action(vlm_action)
            if target_source == "yolo" and perception_mode == "yolo_vlm":
                if low_conf:
                    nav_action, nav_reason, pursuing, scanning, low_conf_streak = (
                        _yolo_low_confidence_pursuit_response(
                            target_reached,
                            low_conf_streak,
                        )
                    )
                    nav_reason = f"{nav_reason} | YOLO {tconf:.2f} / VLM {guided_action or 'none'}"
                else:
                    low_conf_streak = 0
                    nav_action, nav_reason, pursuing, scanning, target_done = (
                        _high_confidence_target_pursuit_response(
                            target_reached=target_reached,
                            target_visual_close=target_visual_close,
                            confidence=tconf,
                            target_side=target_side,
                            guided_action=guided_action,
                        )
                    )
            elif target_source == "vlm":
                nav_action = "move_forward"
                nav_reason = "VLM saw target — driving straight"
            elif low_conf:
                nav_action, nav_reason, pursuing, scanning, low_conf_streak = (
                    _yolo_low_confidence_pursuit_response(
                        target_reached,
                        low_conf_streak,
                    )
                )
            elif target_reached:
                low_conf_streak = 0
                nav_action, target_done = "stop", True
                nav_reason = (
                    "reached (visual bbox close)"
                    if target_visual_close
                    else "reached (centered YOLO target + front proximity)"
                )
            elif abs(target_err) > APPROACH_CENTER_TOL:
                # Turn toward the side the target occupies in the frame.
                nav_action = "turn_left_45" if target_err > 0 else "turn_right_45"
                nav_reason = "centering"
            else:
                low_conf_streak = 0
                nav_action = "move_forward"
                nav_reason = "centered — advancing"
            if not low_conf and tconf >= YOLO_CONFIDENCE_STOP:
                low_conf_streak = 0
            # One line per pursuit step keeps the console readable and makes it
            # easy to spot whether the box is getting larger and more centered.
            side = f"img-{target_side.upper()}" if target_side in ("left", "right", "center") else ("img-RIGHT" if target_err > 0 else "img-LEFT")
            source_label = "VLM" if target_source == "vlm" else "YOLO"
            print(f"[ARIA] TARGET[{'approach' if approach_mode else 'find'}] "
                  f"→ {nav_action} | {nav_reason} | {target} {side} "
                  f"x-err={target_err:+.2f} bbox={target_frac:.0%} conf={tconf:.2f} "
                  f"({source_label} saw '{target_det.class_name}')")

        elif pursuing:
            recent_low_conf_yolo = (
                last_yolo_target_seen_step > 0
                and last_yolo_target_confidence < YOLO_CONFIDENCE_STOP
                and (step - last_yolo_target_seen_step) <= YOLO_RECENT_LOW_CONF_HOLD_LIMIT
            )
            if recent_low_conf_yolo:
                nav_action = "move_forward"
                nav_reason = (
                    f"recent low-confidence {target} hit ({last_yolo_target_confidence:.2f}) "
                    "— keep approaching to see if confidence rises"
                )
                pursuit_lost = 0
                low_conf_streak = 0
                print(f"[ARIA] {nav_reason}")
            elif vlm_target_hint:
                nav_action, nav_reason = _vlm_hint_action(
                    vlm_target_hint_direction,
                    vlm_hint_repeat_count,
                )
                pursuit_lost = 0
                if vlm_target_hint_direction in ("left", "right") and nav_action.startswith("turn_"):
                    vlm_hint_repeat_count += 1
                else:
                    vlm_hint_repeat_count = 0
            else:
                # Lost sight this step — turn back toward where it was to re-acquire.
                pursuit_lost += 1
                if pursuit_lost > PURSUIT_LOST_LIMIT:
                    pursuing = False
                    vlm_hint_repeat_count = 0
                    low_conf_streak = 0
                    print(f"[ARIA] Lost '{target}' — resuming exploration")
                else:
                    nav_action = "turn_left_45" if last_seen_err > 0 else "turn_right_45"
                    nav_reason = f"re-acquiring '{target}' (lost {pursuit_lost}/{PURSUIT_LOST_LIMIT})"
                    print(f"[ARIA] {nav_reason}")

        elif vlm_target_hint:
            pursuing = True
            nav_action = "move_forward"
            nav_reason = "VLM saw target — driving straight"
            vlm_hint_repeat_count = 0
            low_conf_streak = 0

        # ============================================================
        # EXPLORATION  (only runs when not pursuing a target)
        # ============================================================
        if wait_for_vlm_answer:
            pass
        elif nav_action is not None:
            pass
        elif scanning:
            # Mid-scan: keep turning 45°; on completion pick a frontier from the
            # freshly-built map.
            nav_action = grid.scan_step()
            nav_reason = f"360° scan ({omap.stats()['unknown']} cells unknown)"
            if grid.scan_done():
                scanning = False
                active_frontier = omap.best_frontier(pos_xy[0], pos_xy[1], heading_deg)
                best_dist_to_wp = float("inf")
                no_progress_count = 0
                if active_frontier is not None:
                    no_frontier_count = 0
                    print(
                        f"[ARIA] Scan done → frontier "
                        f"({active_frontier[0]:.1f},{active_frontier[1]:.1f}) "
                        f"score={omap.frontier_score(pos_xy[0], pos_xy[1], active_frontier, heading_deg):.2f} "
                        f"map: {omap.stats()}"
                    )
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
                if omap.frontier_count() == 0:
                    print(f"[ARIA] EXPLORATION COMPLETE — '{target}' not found  {omap.stats()}")
                    nav_action = "stop"
                    nav_reason = "explored all reachable space, target not found"
                    exploration_done = True   # terminate: nothing left to explore
                else:
                    active_frontier = omap.best_frontier(pos_xy[0], pos_xy[1], heading_deg)
                    if active_frontier is not None:
                        no_frontier_count = 0
                        nav_action, dist, fallback_note = _prefer_forward_frontier(pos_xy, active_frontier, proximity)
                        nav_reason = (
                            f"→ frontier ({active_frontier[0]:.1f},{active_frontier[1]:.1f}) "
                            f"dist={dist:.1f}m → {nav_action}"
                        )
                        if fallback_note:
                            nav_reason += f" [{fallback_note}]"
                        print(f"[ARIA] Explore recovery: {nav_reason}")
                    else:
                        scanning = True
                        grid.start_scan()
                        nav_action = grid.scan_step()
                        nav_reason = "360° look-around to choose next frontier"
                        print("[ARIA] Starting 360° look-around")
            else:
                if omap.frontier_count() > 0:
                    active_frontier = omap.best_frontier(pos_xy[0], pos_xy[1], heading_deg)
                    if active_frontier is not None:
                        nav_action, dist, fallback_note = _prefer_forward_frontier(pos_xy, active_frontier, proximity)
                        nav_reason = (
                            f"→ frontier ({active_frontier[0]:.1f},{active_frontier[1]:.1f}) "
                            f"dist={dist:.1f}m → {nav_action}"
                        )
                        if fallback_note:
                            nav_reason += f" [{fallback_note}]"
                        print(f"[ARIA] Explore: {nav_reason}")
                    else:
                        open_target = omap.open_direction_target(
                            pos_xy[0], pos_xy[1], heading_deg, proximity, reach=1.0
                        )
                        nav_action, _ = _plan_action(pos_xy, open_target)
                        if nav_action == "move_forward":
                            nav_reason = "open-direction fallback toward unexplored space"
                            print(f"[ARIA] Explore fallback: {nav_reason}")
                        else:
                            scanning = True
                            grid.start_scan()
                            nav_action = grid.scan_step()
                            nav_reason = "360° look-around to choose next frontier"
                            print("[ARIA] Starting 360° look-around")
                else:
                    open_target = omap.open_direction_target(
                        pos_xy[0], pos_xy[1], heading_deg, proximity, reach=1.0
                    )
                    nav_action, _ = _plan_action(pos_xy, open_target)
                    if nav_action == "move_forward":
                        nav_reason = "open-direction fallback toward unexplored space"
                        print(f"[ARIA] Explore fallback: {nav_reason}")
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
                blocked_frontier = active_frontier
                omap.blacklist(*blocked_frontier)
                next_frontier = omap.best_frontier(pos_xy[0], pos_xy[1], heading_deg)
                active_frontier = next_frontier
                no_progress_count = 0
                if next_frontier is not None:
                    nav_action, dist, fallback_note = _prefer_forward_frontier(pos_xy, next_frontier, proximity)
                    nav_reason = (
                        f"blocked frontier → frontier ({next_frontier[0]:.1f},{next_frontier[1]:.1f}) "
                        f"dist={dist:.1f}m → {nav_action}"
                    )
                    if fallback_note:
                        nav_reason += f" [{fallback_note}]"
                    print(f"[ARIA] Frontier recovery → {nav_reason}")
                else:
                    scanning = True
                    grid.start_scan()
                    nav_action = grid.scan_step()
                    nav_reason = "blocked frontier — re-scan"
                    if blocked_frontier is not None:
                        print(
                            f"[ARIA] Frontier ({blocked_frontier[0]:.1f},{blocked_frontier[1]:.1f}) "
                            f"blocked — re-scan"
                        )
                    else:
                        print("[ARIA] Frontier blocked — re-scan")
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
        # ACTION SELECTION
        # Priority: target pursuit / exploration from live map. The VLM is a
        # perception and reasoning aid, not the source of the navigation policy.
        # ============================================================
        valid_actions = {
            "move_forward", "turn_left_45", "turn_right_45",
            "turn_left_90", "turn_right_90", "turn_around",
            "back_up", "back_up_turn", "back_up_turn_left", "back_up_turn_right", "stop",
        }

        action = nav_action if nav_action in valid_actions else "move_forward"
        if (
            perception_mode != "yolo_vlm"
            and perception_fresh
            and vlm_action in valid_actions
            and not pursuing
            and not target_done
        ):
            action = vlm_action
        reasoning = nav_reason or reasoning_hint or vision_summary or "live-map exploration"
        if target_found and target_source == "vlm" and not nav_reason:
            reasoning = reasoning_hint or vision_summary or "VLM confirmed the target"
        elif perception_fresh and vlm_action in valid_actions and not nav_reason:
            reasoning = reasoning_hint or vision_summary or "VLM suggested the next action"

        if exploration_done:
            exploration_mode = "complete"
        elif target_done or target_found:
            exploration_mode = "target_pursuit"
        elif pursuing:
            exploration_mode = "target_reacquire"
        elif scanning:
            exploration_mode = "scan"
        elif active_frontier is not None:
            exploration_mode = "frontier_move"
        elif no_progress_count >= max(1, NO_PROGRESS_LIMIT // 2) or no_frontier_count > 0:
            exploration_mode = "recovering"
        else:
            exploration_mode = "explore"
        stuck_flag = no_progress_count >= max(1, NO_PROGRESS_LIMIT // 2) or no_frontier_count > 1
        frontier_count = omap.frontier_count()

        # ============================================================
        # SENSOR SAFETY OVERRIDE — skipped when we are intentionally stopping
        # on the target (target_done), since stopping never causes a collision.
        # ============================================================
        if not target_done:
            critical_proximity = (
                scan_result.get("front", 0.0) >= CRITICAL_OBSTACLE_THRESH + 20
                or scan_result.get("critical")
                or (white_wall and scan_result["front"] > OBSTACLE_THRESH * 0.9)
            )
            if critical_proximity:
                clearer = scan_result.get("clearer_turn", "turn_left_45")
                action = f"back_up_turn_{clearer.split('_')[1]}"
                reasoning = f"[SAFETY] critical proximity {scan_result['max']:.0f}, backing out"
                print(f"[ARIA] Critical safety override → {action}")

            elif action == "move_forward" and front_blocked:
                action = scan_result.get("clearer_turn", "turn_left_45")
                if approach_mode and target_found:
                    reasoning = (
                        f"[APPROACH] target visible but front blocked ({scan_result['front']:.0f}), "
                        "turning to clearer side"
                    )
                    print(f"[ARIA] Front-blocked approach override → {action}")
                else:
                    reasoning = f"[SAFETY] front blocked ({scan_result['front']:.0f}), turning to clearer side"
                    print(f"[ARIA] Front-blocked override → {action}")

        print(
            f"[ARIA] THINK: verifier[{perception_source}]={_summarize_vision_text(vision_summary)} "
            f"| planner={_summarize_vision_text(reasoning)} | action={action} "
            f"| mode={exploration_mode} "
            f"| memory={_summarize_vision_text(_vision_memory_summary(state.recent_vision), 90)}"
        )
        print(f"[ARIA] → ACTION: {action} | {reasoning}")
        t_llm = time.time()
        state.plan = reasoning
        state.reasoning_trace.append(
            f"step={step} pos=({pos_xy[0]:.1f},{pos_xy[1]:.1f}) "
            f"hdg={heading_deg:.0f}° blocked={front_blocked} "
            f"vision={_summarize_vision_text(vision_summary)} "
            f"action={action} reason={reasoning}"
        )

        _emit(
            event_callback,
            {
                "type": "reasoning",
                "step": step,
                "goal": goal,
                "action": action,
                "reasoning": reasoning,
                "planner": reasoning,
                "vision": vision_summary,
                "verifier": vision_summary,
                "vision_source": perception_source,
                "perception_mode": perception_mode,
                "target_found": target_found,
                "target_visible_confidence": target_visible_confidence,
                "target_direction": target_direction,
                "target_source": target_source,
            },
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
                "vision": vision_summary,
                "verifier": vision_summary,
                "vision_source": perception_source,
                "perception_mode": perception_mode,
                "vlm_retry_used": _LAST_VLM_RETRY_USED,
                "vlm_model": _ACTIVE_VISION_MODEL or OLLAMA_VISION_MODEL,
                "correction_count": state.correction_count,
                "recent_vision": state.recent_vision[-3:],
                "exploration_mode": exploration_mode,
                "frontier_count": frontier_count,
                "stuck": stuck_flag,
                "target_found": target_found,
                "target_visible_confidence": target_visible_confidence,
                "target_direction": target_direction,
                "target_source": target_source,
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
                    "vision_summary": vision_summary,
                    "vision_source": perception_source,
                    "perception_mode": perception_mode,
                    "graph_stats": graph_stats,
                    "map_stats": omap.stats(),
                    "frontier_count": frontier_count,
                    "exploration_mode": exploration_mode,
                    "stuck": stuck_flag,
                    "spatial_memory": spatial_mem.summary(),
                    "recent_vision": state.recent_vision[-3:],
                    "correction_count": state.correction_count,
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
            motion_fb = _execute_motion(
                action,
                approach_mode=approach_mode and (target_found or vlm_target_hint),
            ) or {}
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
        print(f"[ARIA] dt sense+perception={t_sense - cycle_start:.2f}s "
              f"plan={t_nav - t_sense:.2f}s think={t_llm - t_nav:.2f}s "
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
