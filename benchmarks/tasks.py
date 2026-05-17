"""Benchmark task definitions for ARIA."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class BenchmarkTask:
    """A repeatable robot-control benchmark scenario."""

    name: str
    goal: str
    max_steps: int
    policy: str = "reactive"
    success_hint: str = "Completes without connection or control errors."


TASKS: Dict[str, BenchmarkTask] = {
    "avoid_obstacles": BenchmarkTask(
        name="avoid_obstacles",
        goal="avoid obstacles and keep exploring safely",
        max_steps=50,
        success_hint="Robot runs for all steps without collision or emergency stop.",
    ),
    "drive_forward": BenchmarkTask(
        name="drive_forward",
        goal="drive forward while monitoring sensors",
        max_steps=25,
        success_hint="Robot moves forward unless an obstacle is detected.",
    ),
    "turn_in_place": BenchmarkTask(
        name="turn_in_place",
        goal="rotate to scan the environment",
        max_steps=15,
        success_hint="Robot can repeatedly command turns.",
    ),
    "navigate_to_target": BenchmarkTask(
        name="navigate_to_target",
        goal="navigate to the visible target while avoiding obstacles",
        max_steps=100,
        success_hint="Future LLM/object-detection benchmark.",
    ),
}


def get_task(name: str) -> BenchmarkTask:
    """Return a task by name or raise a helpful error."""
    try:
        return TASKS[name]
    except KeyError as exc:
        available = ", ".join(sorted(TASKS))
        raise ValueError(f"Unknown benchmark task '{name}'. Available: {available}") from exc
