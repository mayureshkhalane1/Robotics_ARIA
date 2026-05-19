"""
Movement Primitives with Completion Tracking

These are high-level movement functions that ensure:
1. Motor commands are executed (not just sent)
2. Movement is verified using GPS/compass feedback
3. Actions complete or timeout gracefully
4. Detailed logging of all movements

Each primitive blocks until the movement completes or a watchdog timer fires.
"""

import math
import time
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class MovementResult:
    """Result of a movement primitive execution."""
    success: bool
    action_type: str  # "move_forward", "turn_left", etc.
    distance_traveled: float = 0.0  # meters
    angle_turned: float = 0.0  # degrees
    duration_seconds: float = 0.0
    start_position: Optional[Tuple[float, float]] = None
    end_position: Optional[Tuple[float, float]] = None
    start_heading: Optional[Tuple[float, float, float]] = None
    end_heading: Optional[Tuple[float, float, float]] = None
    error_message: Optional[str] = None
    
    def __repr__(self) -> str:
        if self.success:
            if self.distance_traveled > 0:
                return f"MovementResult(success=True, moved={self.distance_traveled:.2f}m, time={self.duration_seconds:.1f}s)"
            elif self.angle_turned != 0:
                return f"MovementResult(success=True, turned={self.angle_turned:.1f}°, time={self.duration_seconds:.1f}s)"
            else:
                return f"MovementResult(success=True, time={self.duration_seconds:.1f}s)"
        else:
            return f"MovementResult(success=False, error={self.error_message})"


def calculate_distance(pos1: Tuple[float, float], pos2: Tuple[float, float]) -> float:
    """Calculate Euclidean distance between two (x, y) positions."""
    dx = pos2[0] - pos1[0]
    dy = pos2[1] - pos1[1]
    return math.sqrt(dx * dx + dy * dy)


def calculate_heading(compass_reading: Tuple[float, float, float]) -> float:
    """
    Calculate heading in degrees from compass reading.
    Compass gives (x, y, z) components of magnetic field.
    Heading is angle in the x-y plane, where 0° is +X, 90° is +Y.
    """
    x, y, z = compass_reading[:3]
    heading_rad = math.atan2(y, x)
    heading_deg = math.degrees(heading_rad)
    return heading_deg % 360.0


def normalize_angle(angle_deg: float) -> float:
    """Normalize angle to [-180, 180] range."""
    while angle_deg > 180:
        angle_deg -= 360
    while angle_deg < -180:
        angle_deg += 360
    return angle_deg


def get_current_state(get_state_fn) -> Optional[Dict[str, Any]]:
    """Helper to fetch current robot state."""
    try:
        result = get_state_fn(include_camera=False)
        if result.get("success"):
            return result.get("state")
    except Exception as e:
        logger.error(f"Failed to get robot state: {e}")
    return None


def move_forward(distance_m: float, speed: float = 1.0, get_state_fn=None, 
                 execute_action_fn=None, timeout_seconds: float = 30.0) -> MovementResult:
    """
    Move the robot forward by the specified distance.
    
    Args:
        distance_m: Target distance in meters
        speed: Linear velocity in m/s (default 1.0, max ~4.0 for Pioneer 3-DX)
        get_state_fn: Function to call for getting robot state
        execute_action_fn: Function to call for executing motor commands
        timeout_seconds: Max time to wait for movement (default 30s)
    
    Returns:
        MovementResult with success/failure and movement details
        
    Behavior:
        - Records starting GPS position
        - Executes move command with given speed
        - Waits for GPS position to change by target distance
        - Times out if movement doesn't complete in timeout_seconds
        - Returns detailed result with start/end positions
    """
    start_time = time.time()
    
    if get_state_fn is None or execute_action_fn is None:
        return MovementResult(
            success=False,
            action_type="move_forward",
            error_message="get_state_fn and execute_action_fn are required"
        )
    
    if distance_m <= 0:
        return MovementResult(
            success=False,
            action_type="move_forward",
            error_message=f"distance_m must be positive, got {distance_m}"
        )
    
    if speed <= 0 or speed > 4.0:
        return MovementResult(
            success=False,
            action_type="move_forward",
            error_message=f"speed must be in (0, 4.0], got {speed}"
        )
    
    # Get starting position
    state = get_current_state(get_state_fn)
    if not state or not state.get("position"):
        return MovementResult(
            success=False,
            action_type="move_forward",
            error_message="Cannot read starting position from GPS"
        )
    
    start_pos = tuple(state["position"][:2])
    logger.info(f"move_forward: starting at {start_pos}, target distance={distance_m}m, speed={speed}m/s")
    
    # Execute move command
    result = execute_action_fn(action_type="move", velocity=speed)
    if not result.get("success"):
        return MovementResult(
            success=False,
            action_type="move_forward",
            start_position=start_pos,
            error_message=f"Failed to execute move command: {result.get('message', 'unknown error')}"
        )
    
    # Wait for movement to complete (target distance reached OR timeout)
    distance_traveled = 0.0
    end_pos = start_pos
    max_iterations = int(timeout_seconds * 10)  # Check every 100ms
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        time.sleep(0.1)  # Poll every 100ms
        
        state = get_current_state(get_state_fn)
        if not state or not state.get("position"):
            logger.warning("Lost GPS reading during movement")
            continue
        
        end_pos = tuple(state["position"][:2])
        distance_traveled = calculate_distance(start_pos, end_pos)
        
        # Check if we've reached target distance with some tolerance
        if distance_traveled >= distance_m * 0.95:  # 95% is good enough
            logger.info(f"move_forward: reached target distance {distance_traveled:.2f}m >= {distance_m}m")
            break
        
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            logger.warning(f"move_forward: timeout after {elapsed:.1f}s, distance={distance_traveled:.2f}m")
            break
    
    # Stop the robot
    try:
        execute_action_fn(action_type="stop")
    except:
        pass
    
    elapsed = time.time() - start_time
    success = distance_traveled >= distance_m * 0.9  # Success if within 10% of target
    
    result = MovementResult(
        success=success,
        action_type="move_forward",
        distance_traveled=distance_traveled,
        duration_seconds=elapsed,
        start_position=start_pos,
        end_position=end_pos,
    )
    
    if not success:
        result.error_message = f"Moved {distance_traveled:.2f}m but target was {distance_m}m"
    
    logger.info(f"move_forward: {result}")
    return result


def turn_left(angle_deg: float, speed: float = 0.5, get_state_fn=None,
              execute_action_fn=None, timeout_seconds: float = 30.0) -> MovementResult:
    """
    Rotate the robot left (counter-clockwise) by the specified angle.
    
    Args:
        angle_deg: Target rotation angle in degrees (positive = counter-clockwise)
        speed: Angular velocity in rad/s (default 0.5)
        get_state_fn: Function to call for getting robot state
        execute_action_fn: Function to call for executing motor commands
        timeout_seconds: Max time to wait for rotation (default 30s)
    
    Returns:
        MovementResult with success/failure and rotation details
    """
    return _turn_impl("left", angle_deg, speed, get_state_fn, execute_action_fn, timeout_seconds)


def turn_right(angle_deg: float, speed: float = 0.5, get_state_fn=None,
               execute_action_fn=None, timeout_seconds: float = 30.0) -> MovementResult:
    """
    Rotate the robot right (clockwise) by the specified angle.
    
    Args:
        angle_deg: Target rotation angle in degrees (positive = clockwise)
        speed: Angular velocity in rad/s (default 0.5)
        get_state_fn: Function to call for getting robot state
        execute_action_fn: Function to call for executing motor commands
        timeout_seconds: Max time to wait for rotation (default 30s)
    
    Returns:
        MovementResult with success/failure and rotation details
    """
    return _turn_impl("right", angle_deg, speed, get_state_fn, execute_action_fn, timeout_seconds)


def _turn_impl(direction: str, angle_deg: float, speed: float,
               get_state_fn, execute_action_fn, timeout_seconds: float) -> MovementResult:
    """Internal implementation for turn_left and turn_right."""
    start_time = time.time()
    action_type = f"turn_{direction}"
    
    if get_state_fn is None or execute_action_fn is None:
        return MovementResult(
            success=False,
            action_type=action_type,
            error_message="get_state_fn and execute_action_fn are required"
        )
    
    if angle_deg <= 0:
        return MovementResult(
            success=False,
            action_type=action_type,
            error_message=f"angle_deg must be positive, got {angle_deg}"
        )
    
    if speed <= 0:
        return MovementResult(
            success=False,
            action_type=action_type,
            error_message=f"speed must be positive, got {speed}"
        )
    
    # Get starting heading
    state = get_current_state(get_state_fn)
    if not state or not state.get("orientation"):
        return MovementResult(
            success=False,
            action_type=action_type,
            error_message="Cannot read starting heading from compass"
        )
    
    start_heading = state["orientation"]
    start_heading_deg = calculate_heading(start_heading)
    
    # Target heading
    if direction == "left":
        target_heading_deg = (start_heading_deg + angle_deg) % 360.0
        angular_velocity = speed
    else:  # right
        target_heading_deg = (start_heading_deg - angle_deg) % 360.0
        angular_velocity = -speed
    
    logger.info(f"{action_type}: starting at heading={start_heading_deg:.1f}°, "
                f"target={target_heading_deg:.1f}°, speed={speed}rad/s")
    
    # Execute turn command
    result = execute_action_fn(action_type="turn", angular_velocity=angular_velocity)
    if not result.get("success"):
        return MovementResult(
            success=False,
            action_type=action_type,
            start_heading=start_heading,
            error_message=f"Failed to execute turn command: {result.get('message', 'unknown error')}"
        )
    
    # Wait for rotation to complete
    angle_turned = 0.0
    end_heading = start_heading
    max_iterations = int(timeout_seconds * 10)
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        time.sleep(0.1)
        
        state = get_current_state(get_state_fn)
        if not state or not state.get("orientation"):
            logger.warning("Lost compass reading during rotation")
            continue
        
        end_heading = state["orientation"]
        current_heading_deg = calculate_heading(end_heading)
        
        # Calculate angle difference (shortest path)
        angle_diff = normalize_angle(target_heading_deg - current_heading_deg)
        angle_turned_abs = abs(angle_diff)
        
        # Check if we've reached target heading with tolerance
        if angle_turned_abs <= 5.0:  # Within 5 degrees
            logger.info(f"{action_type}: reached target heading {current_heading_deg:.1f}°")
            angle_turned = angle_deg  # Report full requested angle
            break
        
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            logger.warning(f"{action_type}: timeout after {elapsed:.1f}s, heading={current_heading_deg:.1f}°")
            angle_turned = abs(normalize_angle(current_heading_deg - start_heading_deg))
            break
    
    # Stop the robot
    try:
        execute_action_fn(action_type="stop")
    except:
        pass
    
    elapsed = time.time() - start_time
    success = angle_turned >= angle_deg * 0.9  # Success if within 10% of target
    
    result = MovementResult(
        success=success,
        action_type=action_type,
        angle_turned=angle_turned,
        duration_seconds=elapsed,
        start_heading=start_heading,
        end_heading=end_heading,
    )
    
    if not success:
        result.error_message = f"Turned {angle_turned:.1f}° but target was {angle_deg}°"
    
    logger.info(f"{action_type}: {result}")
    return result


def backup(distance_m: float, speed: float = 1.0, get_state_fn=None,
           execute_action_fn=None, timeout_seconds: float = 30.0) -> MovementResult:
    """
    Move the robot backward by the specified distance.
    
    Args:
        distance_m: Target distance in meters (always positive)
        speed: Linear velocity in m/s (default 1.0, max ~4.0)
        get_state_fn: Function to call for getting robot state
        execute_action_fn: Function to call for executing motor commands
        timeout_seconds: Max time to wait for movement (default 30s)
    
    Returns:
        MovementResult with success/failure and movement details
    """
    start_time = time.time()
    
    if get_state_fn is None or execute_action_fn is None:
        return MovementResult(
            success=False,
            action_type="backup",
            error_message="get_state_fn and execute_action_fn are required"
        )
    
    if distance_m <= 0:
        return MovementResult(
            success=False,
            action_type="backup",
            error_message=f"distance_m must be positive, got {distance_m}"
        )
    
    # Get starting position
    state = get_current_state(get_state_fn)
    if not state or not state.get("position"):
        return MovementResult(
            success=False,
            action_type="backup",
            error_message="Cannot read starting position from GPS"
        )
    
    start_pos = tuple(state["position"][:2])
    logger.info(f"backup: starting at {start_pos}, target distance={distance_m}m, speed={speed}m/s")
    
    # Execute move command with negative velocity (backward)
    result = execute_action_fn(action_type="move", velocity=-speed)
    if not result.get("success"):
        return MovementResult(
            success=False,
            action_type="backup",
            start_position=start_pos,
            error_message=f"Failed to execute backup command: {result.get('message', 'unknown error')}"
        )
    
    # Wait for movement to complete
    distance_traveled = 0.0
    end_pos = start_pos
    max_iterations = int(timeout_seconds * 10)
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        time.sleep(0.1)
        
        state = get_current_state(get_state_fn)
        if not state or not state.get("position"):
            logger.warning("Lost GPS reading during backup")
            continue
        
        end_pos = tuple(state["position"][:2])
        distance_traveled = calculate_distance(start_pos, end_pos)
        
        if distance_traveled >= distance_m * 0.95:
            logger.info(f"backup: reached target distance {distance_traveled:.2f}m >= {distance_m}m")
            break
        
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            logger.warning(f"backup: timeout after {elapsed:.1f}s, distance={distance_traveled:.2f}m")
            break
    
    # Stop the robot
    try:
        execute_action_fn(action_type="stop")
    except:
        pass
    
    elapsed = time.time() - start_time
    success = distance_traveled >= distance_m * 0.9
    
    result = MovementResult(
        success=success,
        action_type="backup",
        distance_traveled=distance_traveled,
        duration_seconds=elapsed,
        start_position=start_pos,
        end_position=end_pos,
    )
    
    if not success:
        result.error_message = f"Backed up {distance_traveled:.2f}m but target was {distance_m}m"
    
    logger.info(f"backup: {result}")
    return result
