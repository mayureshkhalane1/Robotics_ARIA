from __future__ import annotations

from src.agent.aria_agent import _extract_robot_state


def test_extract_robot_state_handles_none() -> None:
    assert _extract_robot_state(None) == {}


def test_extract_robot_state_handles_empty_result() -> None:
    assert _extract_robot_state({}) == {}


def test_extract_robot_state_returns_nested_state() -> None:
    state = {"position": [1, 2, 3], "camera": {"data": "x"}}
    assert _extract_robot_state({"success": True, "state": state}) == state
