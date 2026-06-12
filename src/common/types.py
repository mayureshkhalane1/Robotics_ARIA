"""
Shared data models for ARIA system.
Used across Webots, MCP, and Agent components.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


class ActionType(str, Enum):
    """Robot action types."""
    MOVE = "move"
    TURN = "turn"
    STOP = "stop"
    GRAB = "grab"


@dataclass
class RobotState:
    """Current sensor readings from the robot."""
    position: Tuple[float, float, float]  # (x, y, z) in world coordinates
    orientation: Tuple[float, float, float]  # (roll, pitch, yaw) in radians
    proximity_sensors: Dict[str, float]  # sensor_name -> distance in meters
    wheel_velocities: Tuple[float, float]  # (left, right) wheel velocities
    camera_frame: Optional[bytes] = None  # encoded image if available
    timestamp: float = 0.0  # simulation time
    gps_reading: Optional[Tuple[float, float, float]] = None  # raw GPS if available


@dataclass
class Action:
    """Action the robot will execute."""
    type: ActionType  # 'move', 'turn', 'stop', 'grab'
    params: Dict[str, float] = field(default_factory=dict)  # velocity, angle, duration, etc
    reasoning: str = ""  # LLM's explanation for this action


@dataclass
class AgentState:
    """State persisted across agent loop iterations."""
    goal: str  # Natural language goal
    robot_state: RobotState = field(default_factory=lambda: RobotState(
        position=(0, 0, 0),
        orientation=(0, 0, 0),
        proximity_sensors={},
        wheel_velocities=(0, 0)
    ))
    state_history: List[RobotState] = field(default_factory=list)  # Rolling window
    plan: str = ""  # LLM's current plan
    action: Optional[Action] = None  # Last executed action
    step_count: int = 0
    success: bool = False
    error: str = ""
    reasoning_trace: List[str] = field(default_factory=list)  # For debugging
    recent_vision: List[str] = field(default_factory=list)  # Short-term perception memory
    correction_count: int = 0  # How often we had to fall back / correct weak perception
