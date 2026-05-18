"""
Integration example: Visual Memory with ARIA Agent main loop.

This shows how to integrate VisualMemory into the agent's sense-plan-act cycle.
"""

from src.agent.visual_memory import VisualMemory
from src.common.types import RobotState
import numpy as np
import time
from typing import Optional


# Global visual memory instance
visual_memory = VisualMemory(max_observations=100, loop_closure_threshold=8)


def sense_with_visual_memory(robot_state: RobotState) -> dict:
    """
    Enhanced sense function that stores observations in visual memory.
    
    Args:
        robot_state: Current robot state from sensors
    
    Returns:
        Dictionary with sensor data and memory insights
    """
    # Extract data from robot state
    frame = robot_state.camera_frame
    position = robot_state.position
    orientation = robot_state.orientation
    timestamp = robot_state.timestamp or time.time()
    
    if frame is not None:
        # Store observation in visual memory
        obs_id = visual_memory.add_observation(
            frame=frame,
            pose=position + orientation,  # (x, y, z, roll, pitch, yaw)
            timestamp=timestamp,
            camera_id="webots_camera_0",
            detected_objects={},  # Will be filled by object detector
        )
        
        # Check for loop closure
        loop_closure = visual_memory.find_loop_closure(frame, position)
        
        return {
            "observation_id": obs_id,
            "loop_closure": loop_closure,
            "memory_stats": visual_memory.get_stats(),
        }
    
    return {"observation_id": None, "loop_closure": None}


def plan_with_memory(goal: str, sense_result: dict, robot_state: RobotState) -> str:
    """
    Enhanced planning that uses visual memory insights.
    
    Args:
        goal: Natural language goal
        sense_result: Result from sense_with_visual_memory
        robot_state: Current robot state
    
    Returns:
        Planning reasoning string
    """
    reasoning = f"Goal: {goal}\n"
    
    # Check if we've revisited a location
    if sense_result.get("loop_closure"):
        lc = sense_result["loop_closure"]
        reasoning += (
            f"Loop closure detected! Revisiting {lc.obs_id}\n"
            f"  - Similarity: {lc.similarity_score:.1%}\n"
            f"  - Last seen: {lc.frame_age_seconds:.1f}s ago\n"
            f"  - Pose estimate: {lc.pose_estimate}\n"
        )
    
    # Report memory status
    stats = sense_result.get("memory_stats", {})
    if stats.get("num_observations"):
        reasoning += (
            f"Memory: {stats['num_observations']} observations "
            f"(avg age: {stats.get('average_age_seconds', 0):.1f}s)\n"
        )
    
    # Standard planning logic based on goal
    if "find" in goal.lower():
        reasoning += "Goal: Find object - scanning environment...\n"
    elif "explore" in goal.lower():
        reasoning += "Goal: Explore - moving to unseen areas...\n"
    else:
        reasoning += "Goal: General navigation\n"
    
    return reasoning


def recall_observed_object(object_name: str) -> list:
    """
    Recall all observations where an object was seen.
    
    Args:
        object_name: Name of object to find
    
    Returns:
        List of (obs_id, observation) tuples where object was observed
    """
    return visual_memory.recall_object_location(object_name)


def get_observations_near_current_pose(
    position: tuple,
    search_radius: float = 5.0,
) -> list:
    """
    Get all stored observations within a spatial radius.
    
    Useful for checking if we've explored this area before.
    
    Args:
        position: Current (x, y, z) position
        search_radius: Search radius in meters
    
    Returns:
        List of nearby observations, sorted by distance
    """
    return visual_memory.get_observations_near(position, search_radius)


def export_visual_memory_summary() -> dict:
    """
    Export current visual memory state for debugging/visualization.
    
    Returns:
        Dictionary with memory contents and statistics
    """
    stats = visual_memory.get_stats()
    
    # Collect all observation metadata (without frames to save space)
    obs_summary = []
    for obs_id, obs in visual_memory.obs_by_id.items():
        obs_summary.append({
            "obs_id": obs_id,
            "timestamp": obs.timestamp,
            "pose": obs.pose,
            "detected_objects": list(obs.detected_objects.keys()),
            "frame_shape": obs.frame.shape if obs.frame is not None else None,
        })
    
    return {
        "stats": stats,
        "observations": obs_summary,
    }


# Example: Usage in agent main loop
if __name__ == "__main__":
    print("Visual Memory Integration Example")
    print("=" * 50)
    
    # Simulate robot observations
    for step in range(5):
        # Create synthetic robot state
        robot_state = RobotState(
            position=(float(step), 0.0, 0.0),
            orientation=(0.0, 0.0, float(step) * 0.1),
            proximity_sensors={"front": 1.0},
            wheel_velocities=(1.0, 1.0),
            camera_frame=np.zeros((480, 640, 3), dtype=np.uint8),
            timestamp=time.time() + step,
        )
        
        # Sense with memory
        sense_result = sense_with_visual_memory(robot_state)
        
        # Plan with memory
        plan_result = plan_with_memory(
            goal="explore and find objects",
            sense_result=sense_result,
            robot_state=robot_state,
        )
        
        print(f"\nStep {step + 1}:")
        print(plan_result)
        
        if sense_result.get("loop_closure"):
            print(f"  ⚠️  LOOP CLOSURE DETECTED!")
    
    # Export summary
    print("\n" + "=" * 50)
    print("Final Visual Memory Summary:")
    summary = export_visual_memory_summary()
    print(f"Total observations: {summary['stats']['num_observations']}")
    for obs in summary['observations']:
        print(f"  - {obs['obs_id']}: pose={obs['pose'][:3]}")
