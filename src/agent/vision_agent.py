"""Vision-aware agent that searches for objects using memory and spatial reasoning."""

from __future__ import annotations

import time
from typing import Optional, Callable

import cv2
import numpy as np

from src.common.types import AgentState, ActionType, Action
from src.mcp_server.server import call_tool
from src.perception.camera import get_camera_manager
from src.perception.object_detector import get_detector
from src.agent.visual_memory import get_visual_memory
from src.agent.environment_graph import get_environment_graph


EventCallback = Optional[Callable[[str, AgentState], None]]


def run_vision_aware_agent(
    goal: str,
    max_steps: int = 50,
    obstacle_threshold: float = 800.0,
    sleep_seconds: float = 0.1,
    event_callback: Optional[EventCallback] = None,
) -> AgentState:
    """Run vision-aware agent that searches for target objects.

    The agent:
    1. Captures camera frames
    2. Detects objects in frame
    3. Stores observations in visual memory
    4. Builds spatial graph of environment
    5. Plans path to target using memory + graph
    6. Navigates while avoiding obstacles

    Args:
        goal: Natural language goal (e.g., "find cup and approach it")
        max_steps: Maximum planning steps
        obstacle_threshold: Proximity sensor threshold for obstacle avoidance
        sleep_seconds: Sleep between steps
        event_callback: Function to emit events

    Returns:
        Final agent state
    """
    camera = get_camera_manager()
    detector = get_detector()
    memory = get_visual_memory()
    graph = get_environment_graph()

    # Parse goal to extract target object
    target_object = _extract_target_object(goal)

    state = AgentState(goal=goal, step_count=0, success=False, error=None)

    for step in range(max_steps):
        state.step_count = step + 1

        # === SENSE ===
        try:
            result = call_tool("get_state", {"include_camera": True})
            if result.get("error"):
                state.error = f"State read failed: {result.get('error')}"
                break

            state_data = result.get("state", {})
            pose = state_data.get("pose", {})
            proximity_sensors = state_data.get("proximity_sensors", {})

            # Get camera frame
            frame = camera.get_frame()
            if frame is None:
                state.reasoning_trace.append("sense: no camera frame available")
                continue

            # Run object detection
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            detections = detector.detect(frame_rgb)

            # Convert detections to dict format
            detection_dicts = [
                {
                    "class_name": d.class_name,
                    "confidence": float(d.confidence),
                    "bbox": d.bbox,
                    "center": d.center,
                }
                for d in detections
            ]

            # Store observation
            pose_tuple = (
                pose.get("x", 0.0),
                pose.get("y", 0.0),
                pose.get("z", 0.0),
                pose.get("roll", 0.0),
                pose.get("pitch", 0.0),
                pose.get("yaw", 0.0),
            )
            obs_id = memory.add_observation(
                frame, pose_tuple, timestamp=time.time(), detected_objects={}
            )

            # Add to graph
            pose_dict = {
                "x": pose.get("x", 0.0),
                "y": pose.get("y", 0.0),
                "z": pose.get("z", 0.0),
                "rotation": pose.get("yaw", 0.0),
            }
            node_id = graph.add_observation(
                pose=pose_dict,
                timestamp=time.time(),
                observation_id=obs_id,
                objects_detected=detection_dicts,
            )

            state.reasoning_trace.append(
                f"sense: frame captured, {len(detections)} objects detected, stored in node {node_id}"
            )

            # === PLAN ===
            plan_action = None
            plan_reason = ""

            # Check if target is visible in current frame
            target_detection = None
            if target_object:
                for det in detections:
                    if det.class_name.lower() == target_object.lower():
                        if target_detection is None or det.confidence > target_detection.confidence:
                            target_detection = det

            if target_detection:
                # Target visible - navigate towards it
                cx, cy = target_detection.center
                frame_center_x = frame.shape[1] / 2

                if abs(cx - frame_center_x) < 30:
                    # Centered - move forward
                    plan_action = ("move", 4.0)
                    plan_reason = f"target {target_object} visible and centered - move forward"
                elif cx < frame_center_x:
                    # Left of center - turn left
                    plan_action = ("turn", 0.5)
                    plan_reason = f"target {target_object} on left - turn left"
                else:
                    # Right of center - turn right
                    plan_action = ("turn", -0.5)
                    plan_reason = f"target {target_object} on right - turn right"

            elif target_object:
                # Target not visible - search memory
                object_locations = memory.find_object_locations(target_object)

                if object_locations:
                    # Seen before - navigate to nearest location
                    nearest_loc = min(
                        object_locations,
                        key=lambda l: (l["pose"][0] - pose.get("x", 0)) ** 2
                        + (l["pose"][1] - pose.get("y", 0)) ** 2,
                    )
                    plan_reason = f"remember seeing {target_object} at ({nearest_loc['pose'][0]:.1f}, {nearest_loc['pose'][1]:.1f}) - navigate there"
                    plan_action = ("move", 3.0)
                else:
                    # Never seen - explore
                    unexplored = graph.path_to_unexplored()
                    if unexplored:
                        plan_reason = "target not found yet - explore new area"
                        plan_action = ("move", 3.0)
                    else:
                        plan_reason = "no target found and area fully explored"
                        state.success = False
                        break

            else:
                # No target specified - default exploration
                plan_reason = "exploring environment"
                plan_action = ("move", 3.0)

            # Obstacle avoidance override
            if proximity_sensors:
                front_distance = proximity_sensors.get("front", float("inf"))
                if front_distance < obstacle_threshold:
                    plan_action = ("turn", 0.8)
                    plan_reason = f"obstacle detected at {front_distance:.0f}cm - turn away"

            if not plan_action:
                plan_action = ("stop", {})
                plan_reason = "no valid action"

            state.reasoning_trace.append(f"plan: {plan_reason}")

            # === ACT ===
            action_type, action_param = plan_action

            if action_type == "move":
                result = call_tool("execute_action", {"action_type": "move", "velocity": action_param})
            elif action_type == "turn":
                result = call_tool(
                    "execute_action", {"action_type": "turn", "angular_velocity": action_param}
                )
            elif action_type == "stop":
                result = call_tool("execute_action", {"action_type": "stop"})
            else:
                result = {"error": f"Unknown action: {action_type}"}

            if result.get("error"):
                state.error = f"Action failed: {result.get('error')}"
                break

            state.action = Action(type=ActionType(action_type), params={str(action_param)})
            state.reasoning_trace.append(f"act: executed {action_type}")

            # Emit event
            if event_callback:
                event_callback(
                    "plan",
                    {
                        "type": "plan",
                        "step": step + 1,
                        "plan": plan_reason,
                        "action": f"{action_type}({action_param})",
                        "detections": len(detections),
                    },
                )

        except Exception as e:
            state.error = str(e)
            break

        time.sleep(sleep_seconds)

    # Check success
    if target_object and target_detection:
        state.success = True
        state.reasoning_trace.append(f"SUCCESS: found target {target_object}")
    elif not target_object:
        state.success = True
        state.reasoning_trace.append("SUCCESS: exploration complete")

    return state


def _extract_target_object(goal: str) -> Optional[str]:
    """Extract target object name from goal string.

    Args:
        goal: Goal string like "find cup and approach it"

    Returns:
        Object name or None
    """
    goal_lower = goal.lower()

    # Simple keyword matching
    common_objects = [
        "cup",
        "bottle",
        "chair",
        "table",
        "cup",
        "plant",
        "bed",
        "laptop",
        "monitor",
        "door",
        "wall",
    ]

    for obj in common_objects:
        if obj in goal_lower:
            return obj

    return None
