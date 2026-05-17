"""Tests for ARIA benchmark definitions."""

import pytest

from benchmarks.tasks import TASKS, get_task


def test_expected_benchmark_tasks_exist():
    assert {"avoid_obstacles", "drive_forward", "turn_in_place", "navigate_to_target"}.issubset(TASKS)


def test_get_task_returns_task():
    task = get_task("avoid_obstacles")
    assert task.name == "avoid_obstacles"
    assert task.max_steps > 0
    assert task.goal


def test_get_task_rejects_unknown_task():
    with pytest.raises(ValueError, match="Unknown benchmark task"):
        get_task("missing")
