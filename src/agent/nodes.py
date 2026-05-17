"""Agent node functions for ARIA.

These functions are intentionally usable without LangGraph so the project has a
working baseline before adding a full graph runtime.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from src.common.types import Action, ActionType, AgentState, RobotState
from src.mcp_server.server import tool_execute_action, tool_get_state


# Webots distance sensors usually report larger values when objects are closer
# for common infrared sensors. This threshold is conservative and configurable
# through CLI options in main.py.
DEFAULT_OBSTACLE_THRESHOLD = 800.0
DEFAULT_MOVE_VELOCITY = 1.0
DEFAULT_TURN_VELOCITY = 0.8


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def robot_state_from_response(response: Mapping[str, Any]) -> RobotState:
    """Convert a Webots TCP state dictionary into RobotState."""
    position = response.get("position") or (0.0, 0.0, 0.0)
    orientation = response.get("orientation") or (0.0, 0.0, 0.0)
    proximity = response.get("proximity") or response.get("proximity_sensors") or {}
    wheels = response.get("wheel_velocities") or (0.0, 0.0)

    return RobotState(
        position=tuple(position),
        orientation=tuple(orientation),
        proximity_sensors={str(k): _as_float(v) for k, v in proximity.items()},
        wheel_velocities=tuple(wheels),
        timestamp=_as_float(response.get("timestamp")),
        gps_reading=tuple(position) if position else None,
    )


def sense_node(state: AgentState, get_state: Callable[[], Dict[str, Any]] = tool_get_state) -> AgentState:
    """Read robot sensors and update agent state."""
    result = get_state()
    if not result.get("success"):
        state.error = result.get("message", "Failed to read robot state")
        state.reasoning_trace.append(f"sense failed: {state.error}")
        return state

    raw_state = result.get("state") or {}
    state.robot_state = robot_state_from_response(raw_state)
    state.state_history.append(state.robot_state)
    state.reasoning_trace.append("sense: state updated")
    return state


def front_proximity_values(proximity: Mapping[str, float]) -> list[float]:
    """Return likely front-facing sensor values.

    The controller names sensors as distance_0 ... distance_7. The setup docs
    define 0-2 as front left/center/right.
    """
    preferred_names = ("distance_0", "distance_1", "distance_2")
    values = [_as_float(proximity[name]) for name in preferred_names if name in proximity]
    if values:
        return values
    return [_as_float(v) for _, v in sorted(proximity.items())[:3]]


def choose_reactive_action(
    robot_state: RobotState,
    obstacle_threshold: float = DEFAULT_OBSTACLE_THRESHOLD,
    move_velocity: float = DEFAULT_MOVE_VELOCITY,
    turn_velocity: float = DEFAULT_TURN_VELOCITY,
) -> Action:
    """Choose a simple obstacle-avoidance action."""
    front_values = front_proximity_values(robot_state.proximity_sensors)
    obstacle_detected = bool(front_values) and max(front_values) >= obstacle_threshold

    if obstacle_detected:
        return Action(
            type=ActionType.TURN,
            params={"angular_velocity": turn_velocity},
            reasoning=f"Front obstacle detected from sensors {front_values}; turning away.",
        )

    return Action(
        type=ActionType.MOVE,
        params={"velocity": move_velocity},
        reasoning=f"Path appears clear from front sensors {front_values}; moving forward.",
    )


def plan_node(state: AgentState, obstacle_threshold: float = DEFAULT_OBSTACLE_THRESHOLD) -> AgentState:
    """Plan the next action using the baseline reactive policy."""
    state.action = choose_reactive_action(state.robot_state, obstacle_threshold=obstacle_threshold)
    state.plan = state.action.reasoning
    state.reasoning_trace.append(f"plan: {state.action.type.value} - {state.action.reasoning}")
    return state


def act_node(
    state: AgentState,
    execute_action: Callable[..., Dict[str, Any]] = tool_execute_action,
) -> AgentState:
    """Execute the planned action through the Webots bridge."""
    if state.action is None:
        state.error = "No action planned"
        state.reasoning_trace.append("act failed: no action planned")
        return state

    result = execute_action(action_type=state.action.type.value, **state.action.params)
    if not result.get("success"):
        state.error = result.get("message", "Action failed")
        state.reasoning_trace.append(f"act failed: {state.error}")
        return state

    state.step_count += 1
    state.reasoning_trace.append(f"act: executed {state.action.type.value}")
    return state


def evaluate_node(state: AgentState, max_steps: int) -> AgentState:
    """Evaluate whether the agent loop should stop."""
    if state.error:
        state.success = False
        state.reasoning_trace.append("evaluate: stopping due to error")
    elif state.step_count >= max_steps:
        state.success = True
        state.reasoning_trace.append("evaluate: reached step budget")
    return state
