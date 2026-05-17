"""Local Ollama/Qwen planner for ARIA."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import asdict
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from src.agent.prompts import LLM_SYSTEM_PROMPT
from src.common.config import OLLAMA_BASE_URL, OLLAMA_MODEL, STEP_TIMEOUT
from src.common.types import RobotState


class RobotActionDecision(BaseModel):
    """Structured decision returned by the local model."""

    thought: str = Field(default="")
    action_type: Literal["move", "turn", "stop", "grab"]
    velocity: Optional[float] = None
    angular_velocity: Optional[float] = None
    duration: Optional[float] = None
    reasoning: str = Field(default="")
    done: bool = False


def _strip_thinking(text: str) -> str:
    """Remove Qwen-style hidden thinking tags when present."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()


def _extract_json(text: str) -> Dict[str, Any]:
    """Extract the first JSON object from a model response."""
    cleaned = _strip_thinking(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def build_user_prompt(goal: str, robot_state: RobotState, step_count: int) -> str:
    """Build compact zero-shot observation prompt with no examples."""
    state = asdict(robot_state)
    if state.get("camera_frame"):
        state["camera_frame"] = "present"
    return json.dumps(
        {
            "goal": goal,
            "step_count": step_count,
            "robot_state": state,
            "instruction": "Observe, reason briefly, choose one safe robot action, and keep pursuing the goal until complete.",
        },
        default=str,
    )


def call_ollama_decision(
    goal: str,
    robot_state: RobotState,
    step_count: int,
    model: str = OLLAMA_MODEL,
    base_url: str = OLLAMA_BASE_URL,
    timeout: int = STEP_TIMEOUT,
) -> RobotActionDecision:
    """Call local Ollama chat API and parse a structured robot decision."""
    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": LLM_SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(goal, robot_state, step_count)},
        ],
        "options": {"temperature": 0.1},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama is not reachable at {base_url}: {exc}") from exc

    content = raw.get("message", {}).get("content", "")
    try:
        return RobotActionDecision.model_validate(_extract_json(content))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise RuntimeError(f"Ollama returned invalid action JSON: {content[:300]}") from exc
