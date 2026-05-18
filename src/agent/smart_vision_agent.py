"""
Intelligent Vision Language Agent - Robot that sees, understands, and acts.

This agent:
1. Takes camera images
2. Describes what it sees using image analysis
3. Uses Qwen3 LLM to understand the scene and decide next action
4. Remembers past observations
5. Searches intelligently for target objects
6. Makes strategic movement decisions
"""

import cv2
import numpy as np
import time
import json
import urllib.request
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass

from src.perception.camera import get_camera_manager
from src.mcp_server.server import call_tool
from src.common.types import AgentState
from src.common.config import OLLAMA_BASE_URL, OLLAMA_MODEL


def analyze_image_simple(frame: np.ndarray) -> str:
    """Simple local image analysis - describe color distribution and shapes."""
    # Get image stats
    h, w = frame.shape[:2]
    
    # Analyze color
    avg_color = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).mean(axis=(0,1))
    
    # Detect edges for shapes
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    
    description = f"Image ({w}x{h}). Color avg: R{int(avg_color[0])},G{int(avg_color[1])},B{int(avg_color[2])}. "
    description += f"Found {len(contours)} shapes/edges. "
    
    # Describe brightness
    brightness = gray.mean()
    if brightness < 50:
        description += "Very dark. "
    elif brightness < 100:
        description += "Dark. "
    elif brightness > 200:
        description += "Very bright. "
    else:
        description += "Normal brightness. "
    
    return description


def query_qwen(prompt: str, temperature: float = 0.3) -> str:
    """Query Qwen3 via Ollama API."""
    try:
        url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
        payload = {
            "model": OLLAMA_MODEL,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a robot navigation AI. Answer concisely with specific actions. Think step-by-step about the task."
                },
                {"role": "user", "content": prompt},
            ],
            "options": {"temperature": temperature},
        }
        
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = json.loads(response.read().decode("utf-8"))
        
        return raw.get("message", {}).get("content", "")
    except Exception as e:
        print(f"[Qwen Error] {e}")
        return "Move forward"


class SmartVisionAgent:
    """Robot that uses vision + language understanding for intelligent navigation."""
    
    def __init__(self, goal: str, max_steps: int = 100):
        self.goal = goal
        self.max_steps = max_steps
        self.camera = get_camera_manager()
        self.observations: List[Dict[str, Any]] = []
        self.step_count = 0
        
        # Extract target
        self.target = self._extract_target(goal)
        print(f"\n[SmartVisionAgent] Goal: {goal}")
        print(f"[SmartVisionAgent] Target: {self.target}")
    
    def run(self) -> AgentState:
        """Run the agent."""
        state = AgentState(goal=self.goal, step_count=0, success=False)
        
        position_x, position_y, rotation = 0.0, 0.0, 0.0
        exploration_pattern = [0, 45, 90, 135, 180, -135, -90, -45]  # Rotation angles to try
        exploration_idx = 0
        
        for step in range(self.max_steps):
            self.step_count = step + 1
            state.step_count = self.step_count
            
            print(f"\n{'='*60}")
            print(f"[Step {self.step_count}/{self.max_steps}] Position: ({position_x:.1f}, {position_y:.1f}), Rotation: {rotation:.0f}°")
            print(f"{'='*60}")
            
            # === SENSE ===
            print("[SENSE] Capturing camera frame...")
            frame = self.camera.get_frame()
            if frame is None:
                print("✗ No frame")
                break
            print(f"✓ Frame: {frame.shape}")
            
            # === PERCEIVE ===
            print("[PERCEIVE] Analyzing what the robot sees...")
            image_desc = analyze_image_simple(frame)
            print(f"  Image analysis: {image_desc}")
            
            # === UNDERSTAND ===
            print("[UNDERSTAND] Asking Qwen: What do you see? Is the target here?")
            
            understand_prompt = f"""
You are analyzing a robot's camera view while searching for: {self.target}

Image properties: {image_desc}
Current position: ({position_x:.1f}, {position_y:.1f})
Facing direction: {rotation:.0f} degrees

Based on the image properties, what objects or features can be inferred?
Is there evidence of: {self.target}?

Answer in 1-2 sentences.
"""
            
            understanding = query_qwen(understand_prompt, temperature=0.2)
            print(f"  Understanding: {understanding[:150]}")
            state.reasoning_trace.append(f"step {self.step_count}: see - {understanding[:100]}")
            
            # Store observation
            self.observations.append({
                'step': self.step_count,
                'position': (position_x, position_y, rotation),
                'understanding': understanding,
                'image_shape': frame.shape
            })
            
            # Check if target found
            if self.target.lower() in understanding.lower():
                print(f"\n✅ FOUND '{self.target}'!")
                state.success = True
                state.reasoning_trace.append(f"Found target at step {self.step_count}")
                break
            
            # === PLAN ===
            print("[PLAN] Qwen deciding next action...")
            
            plan_prompt = f"""
Robot status:
- Searching for: {self.target}
- Current view: {image_desc}
- Last observation: {understanding[:100]}
- Position: ({position_x:.1f}, {position_y:.1f})
- Steps taken: {self.step_count}/{self.max_steps}

What should the robot do NEXT? Choose ONE:
1. Move forward to explore further
2. Turn left 45° to see more
3. Turn right 45° to see more  
4. Backup and try different direction

Be concise. Reply with the number (1-4) and brief reason.
"""
            
            decision = query_qwen(plan_prompt, temperature=0.3)
            print(f"  Decision: {decision[:100]}")
            state.reasoning_trace.append(f"step {self.step_count}: plan - {decision[:60]}")
            
            # === ACT ===
            print("[ACT] Executing action...")
            
            if "1" in decision or "forward" in decision.lower():
                print("  → Moving forward...")
                call_tool("execute_action", {"action_type": "move", "velocity": 2.0})
                position_x += 0.3
            elif "2" in decision or "left" in decision.lower():
                print("  ← Turning left...")
                call_tool("execute_action", {"action_type": "turn", "angular_velocity": 0.8})
                rotation += 45
            elif "3" in decision or "right" in decision.lower():
                print("  → Turning right...")
                call_tool("execute_action", {"action_type": "turn", "angular_velocity": -0.8})
                rotation -= 45
            else:
                print("  → Default: moving forward...")
                call_tool("execute_action", {"action_type": "move", "velocity": 2.0})
                position_x += 0.3
            
            # Log step
            print(f"✓ Step {self.step_count} complete")
            time.sleep(0.3)
        
        # === FINAL RESULT ===
        print(f"\n{'='*60}")
        if state.success:
            print(f"✅ SUCCESS! Found '{self.target}' in {self.step_count} steps")
        else:
            print(f"⏱️ Timeout - did not find '{self.target}' in {self.max_steps} steps")
            print(f"Observations made: {len(self.observations)}")
        print(f"{'='*60}\n")
        
        return state
    
    def _extract_target(self, goal: str) -> str:
        """Extract target from goal string."""
        targets = ['cup', 'chair', 'table', 'door', 'window', 'lamp', 'plant', 'person', 'bottle']
        goal_lower = goal.lower()
        for target in targets:
            if target in goal_lower:
                return target
        return 'target'


def run_smart_vision_agent(goal: str, max_steps: int = 50) -> AgentState:
    """Run smart vision agent."""
    agent = SmartVisionAgent(goal=goal, max_steps=max_steps)
    return agent.run()


if __name__ == "__main__":
    state = run_smart_vision_agent("find cup", max_steps=15)
    print(f"\nFinal result: {'SUCCESS' if state.success else 'FAILED'}")
