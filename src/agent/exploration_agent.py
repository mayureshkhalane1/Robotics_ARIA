"""
Exploration Agent: Manages room exploration and target search strategy.
Uses sub-agents to plan room-by-room exploration.
"""

import json
from typing import Dict, List, Any, Optional, Tuple

# Room mapping for apartment
ROOM_ZONES = {
    "hallway": {"priority": 1, "actions": ["move_forward", "turn_left_90", "turn_right_90"]},
    "living_room": {"priority": 2, "actions": ["move_forward", "turn_left_90", "turn_right_90"]},
    "bedroom_1": {"priority": 3, "actions": ["move_forward", "turn_left_90", "turn_right_90"]},
    "bedroom_2": {"priority": 4, "actions": ["move_forward", "turn_left_90", "turn_right_90"]},
    "kitchen": {"priority": 5, "actions": ["move_forward", "turn_left_90", "turn_right_90"]},
    "bathroom": {"priority": 6, "actions": ["move_forward", "turn_left_90", "turn_right_90"]},
}

# Room-specific object locations (heuristic)
ROOM_OBJECT_HINTS = {
    "kitchen": ["table", "chair", "cup", "bottle", "refrigerator", "oven", "sink"],
    "living_room": ["sofa", "couch", "chair", "table", "lamp", "tv", "plant", "flower", "vase"],
    "bedroom_1": ["bed", "mirror", "nightstand", "lamp", "closet"],
    "bedroom_2": ["bed", "mirror", "nightstand", "lamp", "closet"],
    "bathroom": ["mirror", "sink", "toilet", "bathtub", "radiator"],
    "hallway": ["door", "fire extinguisher", "wall"],
}

# Target to room mapping
TARGET_ROOM_MAP = {
    "flower": "living_room",
    "flower pot": "living_room",
    "vase": "living_room",
    "plant": "living_room",
    "potted plant": "living_room",
    "sofa": "living_room",
    "couch": "living_room",
    "tv": "living_room",
    "lamp": "living_room",
    "table": "kitchen",
    "cup": "kitchen",
    "bottle": "kitchen",
    "bed": "bedroom_1",
    "mirror": "bathroom",
    "sink": "bathroom",
    "toilet": "toilet",
    "refrigerator": "kitchen",
    "oven": "kitchen",
}


class RoomMapper:
    """Tracks which rooms have been visited and explored."""
    
    def __init__(self):
        self.visited_rooms: Dict[str, bool] = {room: False for room in ROOM_ZONES.keys()}
        self.current_room: Optional[str] = "hallway"
        self.room_history: List[str] = ["hallway"]
    
    def mark_visited(self, room: str):
        """Mark a room as visited."""
        if room in self.visited_rooms:
            self.visited_rooms[room] = True
            if room not in self.room_history:
                self.room_history.append(room)
    
    def get_next_room_to_explore(self) -> Optional[str]:
        """Get the next unvisited room based on priority."""
        unvisited = [r for r, visited in self.visited_rooms.items() if not visited]
        if not unvisited:
            return None
        # Sort by priority
        unvisited.sort(key=lambda r: ROOM_ZONES[r]["priority"])
        return unvisited[0]
    
    def get_exploration_status(self) -> str:
        """Get status of room exploration."""
        visited = sum(1 for v in self.visited_rooms.values() if v)
        total = len(self.visited_rooms)
        return f"{visited}/{total} rooms explored"


class ExplorationPlanner:
    """Plans exploration strategy based on goal and current state."""
    
    def __init__(self, goal: str, target: str):
        self.goal = goal
        self.target = target.lower()
        self.target_room = self._estimate_target_room()
        self.mapper = RoomMapper()
        self.stuck_count = 0
        self.last_positions: List[Tuple[float, float]] = []
    
    def _estimate_target_room(self) -> Optional[str]:
        """Estimate which room the target is likely in."""
        for pattern, room in TARGET_ROOM_MAP.items():
            if pattern in self.target:
                return room
        return None
    
    def detect_stuck(self, position: Tuple[float, float], threshold: int = 3) -> bool:
        """Detect if robot is stuck in a location."""
        self.last_positions.append(position)
        if len(self.last_positions) > threshold:
            self.last_positions.pop(0)
            # Check if all recent positions are similar (within 0.5m)
            diffs = [abs(self.last_positions[i][0] - self.last_positions[i+1][0]) + 
                    abs(self.last_positions[i][1] - self.last_positions[i+1][1])
                    for i in range(len(self.last_positions)-1)]
            if all(d < 0.5 for d in diffs):
                self.stuck_count += 1
                return True
        return False
    
    def get_exploration_prompt(self, current_room: str, vision_desc: str) -> str:
        """Generate detailed exploration prompt based on strategy."""
        target_room_hint = ""
        if self.target_room:
            target_room_hint = f"\nTarget '{self.target}' is likely in: {self.target_room.replace('_', ' ')}"
        
        unexplored = self.mapper.get_next_room_to_explore()
        next_room_hint = ""
        if unexplored:
            next_room_hint = f"\nNext room to explore: {unexplored.replace('_', ' ')}"
        
        prompt = f"""You are exploring a furnished apartment to find '{self.target}'.

CURRENT ROOM: {current_room.replace('_', ' ')}
CURRENT VISION: {vision_desc}

EXPLORATION STRATEGY:
1. If target visible in current room → approach it and stop
2. If target not visible → explore this room fully:
   - Scan left (turn_left_90)
   - Scan right (turn_right_90)
   - Move forward into the room
3. After exploring current room → move to next room
4. If stuck (same position repeatedly) → try different direction

{target_room_hint}
{next_room_hint}

PRIORITY: Explore rooms, move between rooms, find target. Don't rotate in corners!"""
        return prompt
    
    def should_change_room(self, current_room: str, visited_positions: List[str]) -> bool:
        """Decide if robot should exit current room and explore next one."""
        # If stuck in same room for too long, try to change rooms
        if self.stuck_count > 2:
            return True
        
        # If target is in a specific room, prioritize that room
        if self.target_room and current_room != self.target_room:
            return True
        
        return False
