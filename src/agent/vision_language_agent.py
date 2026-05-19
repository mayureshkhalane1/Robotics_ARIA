"""
Vision Language Agent - Uses LLM to understand scenes and make intelligent decisions.

The agent:
1. Takes camera images as the robot rotates
2. Converts images to descriptions (visual scene text)
3. Asks Qwen: "What do you see? Where are objects? What should I do next?"
4. Remembers past observations
5. Makes smart movement decisions
6. Searches for target objects intelligently
"""

import cv2
import numpy as np
import time
import base64
import json
import urllib.request
import urllib.error
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from src.perception.camera import get_camera_manager
from src.mcp_server.server import call_tool
from src.common.types import AgentState
from src.common.config import OLLAMA_BASE_URL, OLLAMA_MODEL


@dataclass
class SceneObservation:
    """A scene observation with VLM analysis."""
    timestamp: float
    position: tuple  # (x, y, rotation)
    frame: np.ndarray
    frame_description: str  # What VLM sees
    objects_found: List[str]  # Objects mentioned
    obstacles: List[str]  # Obstacles mentioned
    recommendations: str  # What VLM recommends


class VisionLanguageAgent:
    """Agent that understands scenes using vision + language."""
    
    def __init__(self, goal: str, max_steps: int = 100):
        """Initialize the vision language agent.
        
        Args:
            goal: Target object to find (e.g., "cup")
            max_steps: Maximum steps before giving up
        """
        self.goal = goal
        self.max_steps = max_steps
        self.camera = get_camera_manager()
        self.observations: List[SceneObservation] = []
        self.visited_positions: List[tuple] = []
        
        # Extract target object from goal
        self.target_object = self._extract_target(goal)
        print(f"[VLM Agent] Goal: Find '{self.target_object}'")
    
    def run(self) -> AgentState:
        """Run the vision language agent."""
        state = AgentState(goal=self.goal, step_count=0, success=False)
        
        current_x, current_y, current_rotation = 0.0, 0.0, 0.0
        
        for step in range(self.max_steps):
            state.step_count = step + 1
            
            print(f"\n[Step {step + 1}/{self.max_steps}]")
            
            # === SENSE ===
            print("[SENSE] Taking image...")
            frame = self.camera.get_frame()
            if frame is None:
                print("✗ No camera frame")
                break
            
            print(f"✓ Got frame: {frame.shape}")
            
            # === UNDERSTAND ===
            print("[UNDERSTAND] Analyzing scene with vision language model...")
            scene_desc = self._analyze_scene_with_vlm(frame, self.visited_positions)
            print(f"VLM says: {scene_desc['analysis'][:100]}...")
            
            # Store observation
            obs = SceneObservation(
                timestamp=time.time(),
                position=(current_x, current_y, current_rotation),
                frame=frame.copy(),
                frame_description=scene_desc['analysis'],
                objects_found=scene_desc.get('objects', []),
                obstacles=scene_desc.get('obstacles', []),
                recommendations=scene_desc.get('recommendation', '')
            )
            self.observations.append(obs)
            
            # === PLAN ===
            print("[PLAN] Deciding next action...")
            
            # Check if target is in current view
            if self.target_object.lower() in scene_desc['analysis'].lower():
                print(f"✓ FOUND '{self.target_object}'!")
                state.success = True
                state.reasoning_trace.append(f"Found target '{self.target_object}' at step {step + 1}")
                break
            
            # Ask VLM what to do
            action_plan = self._get_next_action(obs, self.observations)
            print(f"Recommendation: {action_plan}")
            
            # === ACT ===
            print("[ACT] Executing action...")
            
            if "forward" in action_plan.lower():
                print("→ Moving forward")
                call_tool("execute_action", {"action_type": "move", "velocity": 3.0})
                current_x += 0.5
            elif "turn left" in action_plan.lower() or "rotate left" in action_plan.lower():
                print("← Turning left")
                call_tool("execute_action", {"action_type": "turn", "angular_velocity": 0.5})
                current_rotation += 45
            elif "turn right" in action_plan.lower() or "rotate right" in action_plan.lower():
                print("→ Turning right")
                call_tool("execute_action", {"action_type": "turn", "angular_velocity": -0.5})
                current_rotation -= 45
            elif "back" in action_plan.lower():
                print("← Backing up")
                call_tool("execute_action", {"action_type": "move", "velocity": -2.0})
                current_x -= 0.3
            else:
                print("→ Moving forward (default)")
                call_tool("execute_action", {"action_type": "move", "velocity": 3.0})
                current_x += 0.5
            
            state.reasoning_trace.append(f"step {step + 1}: {action_plan}")
            
            # Small delay
            time.sleep(0.5)
        
        # Final status
        if state.success:
            print(f"\n✅ SUCCESS! Found '{self.target_object}' in {state.step_count} steps")
        else:
            print(f"\n❌ Did not find '{self.target_object}' in {state.step_count} steps")
        
        return state
    
    def _analyze_scene_with_vlm(self, frame: np.ndarray, past_positions: List[tuple]) -> Dict[str, Any]:
        """Use Qwen3-VL to analyze the scene with vision-language understanding.
        
        Args:
            frame: Camera frame (BGR numpy array)
            past_positions: Previously visited positions
            
        Returns:
            Scene analysis dictionary with objects, obstacles, and recommendations
        """
        # Convert frame to base64 for encoding to LLM
        _, buffer = cv2.imencode('.jpg', frame)
        frame_b64 = base64.b64encode(buffer).decode('utf-8')
        
        # Create a detailed prompt for Qwen3-VL
        scene_prompt = f"""
You are analyzing a robot's camera view. The robot is searching for: {self.target_object}

IMPORTANT: Analyze the image data provided and answer these questions:

1. What objects do you see in the image? List them with colors and positions.
2. Is there a {self.target_object}? If yes, describe its location (left, center, right, near, far).
3. What obstacles do you see? (Walls, furniture, clutter, other objects blocking the path)
4. What should the robot do next to find the {self.target_object}?
   - Move forward to explore
   - Turn left to see more
   - Turn right to see more
   - Back up if stuck

Provide a concise but detailed analysis.
Previously visited: {len(past_positions)} locations.

Be specific and actionable. End with a single action recommendation.
"""
        
        try:
            # Call Qwen3-VL with the image
            response = self._ask_qwen_vision_about_scene(frame_b64, scene_prompt)
            
            return {
                'analysis': response,
                'objects': self._extract_objects(response),
                'obstacles': self._extract_obstacles(response),
                'recommendation': self._extract_recommendation(response)
            }
        except Exception as e:
            print(f"VLM error: {e}")
            return {
                'analysis': 'Unable to analyze scene. The robot sees objects in the room.',
                'objects': [],
                'obstacles': [],
                'recommendation': 'Move forward'
            }
    
    def _ask_qwen_about_strategy(self, prompt: str) -> str:
        """Ask Qwen a strategic question about navigation."""
        try:
            url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
            payload = {
                "model": OLLAMA_MODEL,
                "stream": False,
                "messages": [
                    {"role": "system", "content": "You are a helpful robot navigation assistant. Answer concisely."},
                    {"role": "user", "content": prompt},
                ],
                "options": {"temperature": 0.3},
            }
            
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = json.loads(response.read().decode("utf-8"))
            
            content = raw.get("message", {}).get("content", "")
            return content
        except Exception as e:
            print(f"Qwen query error: {e}")
            return "The robot sees objects in the room. It should explore systematically."
    
    def _ask_qwen_vision_about_scene(self, frame_b64: str, prompt: str) -> str:
        """Ask Qwen3-VL to analyze a scene with vision-language understanding.
        
        This method passes the base64-encoded image to the VLM for analysis.
        
        Args:
            frame_b64: Base64-encoded JPEG image
            prompt: Text prompt for the VLM
            
        Returns:
            VLM analysis as text
        """
        try:
            url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
            
            # Ollama API format for qwen3-vl:8b with images
            # Images are passed as base64 data URLs
            payload = {
                "model": OLLAMA_MODEL,
                "stream": False,
                "messages": [
                    {
                        "role": "system", 
                        "content": "You are a robot vision assistant. Analyze images carefully and provide actionable navigation advice."
                    },
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [frame_b64]  # Ollama supports images in messages
                    },
                ],
                "options": {"temperature": 0.3},
            }
            
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = json.loads(response.read().decode("utf-8"))
            
            content = raw.get("message", {}).get("content", "")
            return content
        except Exception as e:
            print(f"Qwen3-VL query error: {e}")
            # Fallback to text-only if VL fails
            return self._ask_qwen_about_strategy(prompt)

    
    def _extract_objects(self, text: str) -> List[str]:
        """Extract mentioned objects from response."""
        objects = []
        keywords = ['see', 'notice', 'observe', 'there is', 'there are']
        
        for keyword in keywords:
            if keyword in text.lower():
                # Simple extraction - in production would be more sophisticated
                pass
        
        return objects
    
    def _extract_obstacles(self, text: str) -> List[str]:
        """Extract mentioned obstacles."""
        obstacles = []
        if 'wall' in text.lower():
            obstacles.append('wall')
        if 'furniture' in text.lower():
            obstacles.append('furniture')
        if 'obstacle' in text.lower():
            obstacles.append('obstacle')
        
        return obstacles
    
    def _extract_recommendation(self, text: str) -> str:
        """Extract recommended next action."""
        if 'forward' in text.lower():
            return 'move forward'
        elif 'turn' in text.lower() or 'rotate' in text.lower():
            if 'left' in text.lower():
                return 'turn left'
            else:
                return 'turn right'
        elif 'back' in text.lower():
            return 'move backward'
        else:
            return 'move forward'
    
    def _get_next_action(self, current_obs: SceneObservation, 
                        past_obs: List[SceneObservation]) -> str:
        """Decide next action based on current and past observations."""
        
        prompt = f"""
Based on robot's observations:

Current scene: {current_obs.frame_description[:200]}
Target object: {self.target_object}

Previous observations: {len(past_obs)} so far

What should the robot do NEXT? Choose one:
- Move forward to explore
- Turn left to see more
- Turn right to see more
- Back up if stuck

Answer with ONE action only.
"""
        
        try:
            url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
            payload = {
                "model": OLLAMA_MODEL,
                "stream": False,
                "messages": [
                    {"role": "system", "content": "You are a robot navigation assistant. Give one word action."},
                    {"role": "user", "content": prompt},
                ],
                "options": {"temperature": 0.1},
            }
            
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = json.loads(response.read().decode("utf-8"))
            
            content = raw.get("message", {}).get("content", "")
            return content[:100]  # First 100 chars as action
        except Exception as e:
            print(f"Error getting next action: {e}")
            return "move forward"
    
    def _extract_target(self, goal: str) -> str:
        """Extract target object from goal string."""
        keywords = ['cup', 'chair', 'table', 'door', 'window', 'lamp', 'plant']
        for keyword in keywords:
            if keyword in goal.lower():
                return keyword
        return 'target object'


def run_vision_language_agent(goal: str, max_steps: int = 100) -> AgentState:
    """Run the vision language agent."""
    agent = VisionLanguageAgent(goal=goal, max_steps=max_steps)
    return agent.run()


if __name__ == "__main__":
    state = run_vision_language_agent("find cup", max_steps=20)
    print(f"\nFinal state: {state.success}")
