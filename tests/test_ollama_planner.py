"""Tests for Ollama planner helpers."""

import json

from src.agent.llm import RobotActionDecision, _extract_json, build_user_prompt
from src.agent.nodes import action_from_decision, ollama_plan_node
from src.common.types import AgentState, ActionType, RobotState


def state_with_front(value: float) -> RobotState:
    return RobotState(
        position=(0.0, 0.0, 0.0),
        orientation=(0.0, 0.0, 0.0),
        proximity_sensors={f"so{i}": value for i in range(8)},
        wheel_velocities=(0.0, 0.0),
    )


def test_extract_json_strips_qwen_thinking():
    data = _extract_json('<think>private</think>{"action_type":"stop","thought":"wait"}')
    assert data["action_type"] == "stop"


def test_build_user_prompt_has_goal_and_state():
    prompt = build_user_prompt("explore", state_with_front(0), 2)
    data = json.loads(prompt)
    assert data["goal"] == "explore"
    assert data["step_count"] == 2
    assert "robot_state" in data


def test_action_from_decision_clamps_velocity():
    action = action_from_decision(
        RobotActionDecision(action_type="move", velocity=99, thought="go", reasoning="clear")
    )
    assert action.type == ActionType.MOVE
    assert action.params["velocity"] == 4.0


def test_ollama_plan_node_uses_fallback_on_error():
    state = AgentState(goal="explore", robot_state=state_with_front(0))

    def broken_planner(**_kwargs):
        raise RuntimeError("offline")

    result = ollama_plan_node(state, planner=broken_planner)
    assert result.action is not None
    assert result.action.type == ActionType.MOVE
    assert "Ollama fallback" in result.plan


def test_ollama_plan_node_safety_overrides_move():
    state = AgentState(goal="explore", robot_state=state_with_front(1000))

    def unsafe_planner(**_kwargs):
        return RobotActionDecision(action_type="move", velocity=4, thought="go", reasoning="move")

    result = ollama_plan_node(state, planner=unsafe_planner)
    assert result.action is not None
    assert result.action.type == ActionType.TURN
