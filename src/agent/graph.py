"""Simple ARIA agent loop.

This module provides a working sequential loop now and can later be swapped for
LangGraph StateGraph orchestration without changing node behavior.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Callable, Dict, Any, Optional

from src.common.types import AgentState
from src.agent.nodes import act_node, evaluate_node, ollama_plan_node, plan_node, sense_node


EventCallback = Callable[[Dict[str, Any]], None]


def _emit(callback: Optional[EventCallback], event_type: str, state: AgentState, **extra: Any) -> None:
    if not callback:
        return
    payload = {
        "type": event_type,
        "step": state.step_count,
        "goal": state.goal,
        "success": state.success,
        "error": state.error,
        "plan": state.plan,
        "action": asdict(state.action) if state.action else None,
        "robot_state": asdict(state.robot_state),
        "reasoning_tail": state.reasoning_trace[-8:],
        **extra,
    }
    callback(payload)


def run_reactive_agent(
    goal: str,
    max_steps: int,
    obstacle_threshold: float = 800.0,
    sleep_seconds: float = 0.1,
    get_state: Callable[[], Dict[str, Any]] | None = None,
    execute_action: Callable[..., Dict[str, Any]] | None = None,
    policy: str = "reactive",
    model: str | None = None,
    on_event: Optional[EventCallback] = None,
) -> AgentState:
    """Run the sense-plan-act-evaluate loop."""
    state = AgentState(goal=goal)
    _emit(on_event, "start", state)

    for _ in range(max_steps):
        state = sense_node(state, get_state=get_state) if get_state else sense_node(state)
        _emit(on_event, "sense", state)
        if state.error:
            break

        if policy in ("ollama", "langgraph"):
            state = ollama_plan_node(state, obstacle_threshold=obstacle_threshold, model=model)
        else:
            state = plan_node(state, obstacle_threshold=obstacle_threshold)
        _emit(on_event, "plan", state)

        state = act_node(state, execute_action=execute_action) if execute_action else act_node(state)
        _emit(on_event, "act", state)
        state = evaluate_node(state, max_steps=max_steps)
        _emit(on_event, "evaluate", state)

        if state.error or state.success:
            break
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    _emit(on_event, "done", state)
    return state
