"""Run ARIA benchmark tasks.

Requires Webots for real robot execution. Use `--dry-run` to verify benchmark
configuration without connecting to Webots.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

from benchmarks.tasks import TASKS, get_task
from src.agent.aria_agent import run_aria_agent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run ARIA benchmarks")
    parser.add_argument("--task", choices=sorted(TASKS), default="avoid_obstacles")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--policy", choices=("reactive",), default="reactive")
    parser.add_argument("--output", default="benchmark_results/results.csv")
    parser.add_argument("--dry-run", action="store_true", help="Print benchmark config without Webots")
    return parser


def run_once(task_name: str, policy: str) -> Dict[str, Any]:
    task = get_task(task_name)
    started = time.time()

    if policy != "reactive":
        raise ValueError(f"Unsupported policy: {policy}")

    state = run_aria_agent(goal=task.goal, max_steps=task.max_steps)
    elapsed = time.time() - started
    return {
        "task": task.name,
        "policy": policy,
        "success": state.success and not state.error,
        "steps": state.step_count,
        "max_steps": task.max_steps,
        "elapsed_seconds": round(elapsed, 3),
        "error": state.error,
        "last_action": state.action.type.value if state.action else "",
    }


def write_results(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["task", "policy", "success", "steps", "max_steps", "elapsed_seconds", "error", "last_action"]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = build_parser().parse_args()
    task = get_task(args.task)

    if args.dry_run:
        print(json.dumps(asdict(task), indent=2))
        return 0

    rows = [run_once(args.task, args.policy) for _ in range(args.runs)]
    write_results(Path(args.output), rows)
    print(json.dumps(rows, indent=2))
    print(f"Wrote results to {args.output}")
    return 0 if all(row["success"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
