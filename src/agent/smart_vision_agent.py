"""Smart vision policy entrypoint.

The previous implementation used text-only image heuristics and declared success
whenever the word "target" appeared in the LLM response, which caused false
positives such as "no target visible". Smart vision now delegates to the robust
ARIA vision-language loop:

1. Sense Webots camera/proximity/GPS.
2. Run YOLO all-class detections with class names, confidence, centers, bboxes.
3. Ask Qwen3-VL to verify the requested target and choose the next action.
4. Execute a bounded motion, stop, then analyze the next frame.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from src.agent.aria_agent import run_aria_agent
from src.common.config import OLLAMA_MODEL
from src.common.types import AgentState


def run_smart_vision_agent(
    goal: str,
    max_steps: int = 50,
    model: str = OLLAMA_MODEL,
    event_callback: Optional[Callable[[Dict], None]] = None,
) -> AgentState:
    """Run the smart vision-language agent using the default VLM model."""
    return run_aria_agent(goal=goal, max_steps=max_steps, model=model, event_callback=event_callback)


if __name__ == "__main__":
    state = run_smart_vision_agent("find cup", max_steps=15)
    print(f"\nFinal result: {'SUCCESS' if state.success else 'FAILED'}")
