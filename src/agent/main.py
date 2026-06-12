"""Command-line entry point for the ARIA robot agent.

Headless counterpart to the browser dashboard — runs the same ARIA grid +
spatial-memory agent (`run_aria_agent`) without the UI.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from typing import Any

from src.agent.aria_agent import run_aria_agent
from src.common.config import OLLAMA_MODEL, PERCEPTION_MODE
from src.mcp_server.server import call_tool, list_tools


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "value"):
        return value.value
    return str(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ARIA robot agent")
    parser.add_argument("--goal", default="explore the room", help="Natural language robot goal")
    parser.add_argument("--steps", type=int, default=50, help="Maximum sense-decide-act steps")
    parser.add_argument("--model", default=OLLAMA_MODEL, help="Ollama model for the optional LLM layer")
    parser.add_argument("--perception-mode", default=PERCEPTION_MODE, help="Perception mode: vlm_first, vlm_only, yolo_vlm, sensor_only")
    parser.add_argument("--list-tools", action="store_true", help="Print available bridge tools and exit")
    parser.add_argument("--validate-only", action="store_true", help="Validate local tool registry without Webots")
    parser.add_argument("--json", action="store_true", help="Print final state as JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.list_tools:
        print(json.dumps(list_tools(), indent=2, default=_json_default))
        return 0

    if args.validate_only:
        result = call_tool("validate_action", {"action_type": "move", "velocity": 1.0})
        print(json.dumps(result, indent=2, default=_json_default))
        return 0 if result.get("valid") else 1

    state = run_aria_agent(
        goal=args.goal,
        max_steps=args.steps,
        model=args.model,
        perception_mode=args.perception_mode,
    )

    if args.json:
        print(json.dumps(state, indent=2, default=_json_default))
    else:
        print(f"Goal: {state.goal}")
        print(f"Steps: {state.step_count}/{args.steps}")
        print(f"Success: {state.success}")
        if state.error:
            print(f"Error: {state.error}")
        if state.action:
            print(f"Last action: {state.action.type.value} {state.action.params}")
        print("Recent reasoning:")
        for item in state.reasoning_trace[-8:]:
            print(f"- {item}")

    return 0 if state.success and not state.error else 1


if __name__ == "__main__":
    raise SystemExit(main())
