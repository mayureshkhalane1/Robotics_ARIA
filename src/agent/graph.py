"""Simple ARIA agent loop.

This module provides a working sequential loop now and can later be swapped for
LangGraph StateGraph orchestration without changing node behavior.
"""

from __future__ import annotations

import time
from typing import Callable, Dict, Any

from src.common.types import AgentState
from src.agent.nodes import act_node, evaluate_node, plan_node, sense_node


def run_reactive_agent(
    goal: str,
    max_steps: int,
    obstacle_threshold: float = 800.0,
    sleep_seconds: float = 0.1,
    get_state: Callable[[], Dict[str, Any]] | None = None,
    execute_action: Callable[..., Dict[str, Any]] | None = None,
) -> AgentState:
    """Run the baseline sense-plan-act-evaluate loop."""
    state = AgentState(goal=goal)

    for _ in range(max_steps):
        state = sense_node(state, get_state=get_state) if get_state else sense_node(state)
        if state.error:
            break

        state = plan_node(state, obstacle_threshold=obstacle_threshold)
        state = act_node(state, execute_action=execute_action) if execute_action else act_node(state)
        state = evaluate_node(state, max_steps=max_steps)

        if state.error or state.success:
            break
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return state
