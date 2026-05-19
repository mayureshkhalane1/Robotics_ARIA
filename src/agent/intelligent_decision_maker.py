"""
ARIA Multi-Agent Planning System

Sub-Agents:
1. SemanticNavigator: Understands "living room ahead" vs "wall"
2. PathPlanner: Maintains map of explored rooms and corridors
3. ConfidenceScorer: Evaluates if proximity reading is real obstacle
4. DecisionMaker: Final action selection with conflict resolution
"""

import json
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum

class RoomType(Enum):
    HALLWAY = "hallway"
    LIVING_ROOM = "living_room"
    KITCHEN = "kitchen"
    BEDROOM = "bedroom"
    BATHROOM = "bathroom"
    UNKNOWN = "unknown"

class ObstacleConfidence(Enum):
    NO_OBSTACLE = 0.0
    LOW = 0.3  # Far wall, might be passable
    MEDIUM = 0.6  # Obstacle nearby
    HIGH = 0.9  # Definite obstacle (wall or furniture)
    CRITICAL = 1.0  # Collision risk

class SemanticNavigator:
    """Understands room types and semantic navigation from vision."""
    
    ROOM_KEYWORDS = {
        "living room": RoomType.LIVING_ROOM,
        "living space": RoomType.LIVING_ROOM,
        "lounge": RoomType.LIVING_ROOM,
        "couch": RoomType.LIVING_ROOM,
        "sofa": RoomType.LIVING_ROOM,
        "coffee table": RoomType.LIVING_ROOM,
        "kitchen": RoomType.KITCHEN,
        "dining": RoomType.KITCHEN,
        "counter": RoomType.KITCHEN,
        "bedroom": RoomType.BEDROOM,
        "bed": RoomType.BEDROOM,
        "bathroom": RoomType.BATHROOM,
        "toilet": RoomType.BATHROOM,
        "sink": RoomType.BATHROOM,
        "hallway": RoomType.HALLWAY,
        "corridor": RoomType.HALLWAY,
        "entryway": RoomType.HALLWAY,
        "entry": RoomType.HALLWAY,
    }
    
    def __init__(self):
        self.current_room: RoomType = RoomType.HALLWAY
        self.room_history: List[RoomType] = [RoomType.HALLWAY]
    
    def identify_room(self, vision_text: str) -> RoomType:
        """Identify room type from vision description."""
        text = vision_text.lower()
        
        # Strong signals (first match wins)
        for keyword, room_type in self.ROOM_KEYWORDS.items():
            if keyword in text:
                if room_type != self.current_room:
                    self.room_history.append(room_type)
                    self.current_room = room_type
                return room_type
        
        return RoomType.UNKNOWN
    
    def get_semantic_direction(self, vision_text: str) -> Optional[str]:
        """Extract semantic direction from vision."""
        text = vision_text.lower()
        
        directions = {
            "left": ["left", "to the left", "on left side"],
            "right": ["right", "to the right", "on right side"],
            "ahead": ["ahead", "in front", "straight", "forward"],
            "behind": ["behind", "back", "rear"],
        }
        
        for direction, keywords in directions.items():
            for keyword in keywords:
                if keyword in text:
                    return direction
        
        return None


class PathPlanner:
    """Maintains map of explored areas and plan optimal paths."""
    
    def __init__(self):
        self.explored_rooms: Dict[RoomType, int] = {room: 0 for room in RoomType}
        self.room_connectivity: Dict[RoomType, List[RoomType]] = {}
        self.dead_ends: List[Tuple[float, float]] = []
        self.open_passages: List[Tuple[float, float]] = []
    
    def mark_room_explored(self, room: RoomType):
        """Mark room as explored."""
        self.explored_rooms[room] += 1
    
    def add_dead_end(self, position: Tuple[float, float]):
        """Mark a dead end position."""
        if position not in self.dead_ends:
            self.dead_ends.append(position)
    
    def get_next_room_to_explore(self, target_room: Optional[RoomType], 
                                  current_room: RoomType) -> Optional[RoomType]:
        """Get prioritized next room to explore."""
        # Priority 1: Target room
        if target_room and self.explored_rooms[target_room] == 0:
            return target_room
        
        # Priority 2: Adjacent unexplored rooms
        if current_room in self.room_connectivity:
            for adjacent in self.room_connectivity[current_room]:
                if self.explored_rooms[adjacent] == 0:
                    return adjacent
        
        # Priority 3: Least explored room
        unexplored = [r for r, count in self.explored_rooms.items() if count == 0]
        if unexplored:
            return unexplored[0]
        
        return None
    
    def is_dead_end(self, position: Tuple[float, float], threshold: float = 0.5) -> bool:
        """Check if current position is a known dead end."""
        for dead_end in self.dead_ends:
            dist = ((position[0] - dead_end[0])**2 + (position[1] - dead_end[1])**2)**0.5
            if dist < threshold:
                return True
        return False


class ConfidenceScorer:
    """Evaluates obstacle confidence based on sensor + semantic data."""
    
    def __init__(self):
        self.sensor_history: List[float] = []
        self.max_history = 5
    
    def score_obstacle(self, 
                      proximity_front: float, 
                      vision_text: str,
                      is_doorway: bool = False) -> ObstacleConfidence:
        """Score how confident we are there's an obstacle."""
        
        # Record history
        self.sensor_history.append(proximity_front)
        if len(self.sensor_history) > self.max_history:
            self.sensor_history.pop(0)
        
        # If vision says "living room ahead" or "doorway", lower confidence
        vision_lower = vision_text.lower()
        semantic_keywords = ["room ahead", "doorway", "open", "entrance", "passage"]
        has_semantic_signal = any(kw in vision_lower for kw in semantic_keywords)
        
        # Sensor-only scoring (relaxed thresholds)
        if proximity_front < 300:  # Very close = obstacle
            confidence = ObstacleConfidence.CRITICAL
        elif proximity_front < 500:  # Close = likely obstacle
            confidence = ObstacleConfidence.HIGH
        elif proximity_front < 700:  # Medium = uncertain
            confidence = ObstacleConfidence.MEDIUM
        elif proximity_front < 900:  # Far = low confidence
            confidence = ObstacleConfidence.LOW
        else:  # Very far = probably wall way ahead
            confidence = ObstacleConfidence.NO_OBSTACLE
        
        # Adjust if we have semantic signal
        if has_semantic_signal and confidence in [ObstacleConfidence.LOW, ObstacleConfidence.NO_OBSTACLE]:
            # Vision says path is open → override sensor
            confidence = ObstacleConfidence.NO_OBSTACLE
        
        return confidence
    
    def is_stable_obstacle(self) -> bool:
        """Check if obstacle reading is consistent."""
        if len(self.sensor_history) < 3:
            return False
        # Obstacle is stable if readings are similar
        variance = max(self.sensor_history) - min(self.sensor_history)
        return variance < 100  # Small variance = stable reading


class IntelligentDecisionMaker:
    """Final decision layer with semantic + sensor fusion."""
    
    def __init__(self):
        self.navigator = SemanticNavigator()
        self.planner = PathPlanner()
        self.scorer = ConfidenceScorer()
        self.target_room: Optional[RoomType] = None
        self.failed_attempts = 0
    
    def set_target(self, target: str):
        """Set target object and infer target room."""
        target_lower = target.lower()
        
        TARGET_ROOM_MAP = {
            "bottle": RoomType.KITCHEN,
            "cup": RoomType.KITCHEN,
            "table": RoomType.KITCHEN,
            "kitchen": RoomType.KITCHEN,
            "bed": RoomType.BEDROOM,
            "bedroom": RoomType.BEDROOM,
            "bathroom": RoomType.BATHROOM,
            "toilet": RoomType.BATHROOM,
            "flower": RoomType.LIVING_ROOM,
            "vase": RoomType.LIVING_ROOM,
            "couch": RoomType.LIVING_ROOM,
            "sofa": RoomType.LIVING_ROOM,
        }
        
        for keyword, room in TARGET_ROOM_MAP.items():
            if keyword in target_lower:
                self.target_room = room
                break
    
    def decide_action(self,
                     proximity_front: float,
                     vision_text: str,
                     current_heading: float,
                     is_stuck: bool,
                     stuck_count: int) -> Dict[str, Any]:
        """Make intelligent decision based on all signals."""
        
        # Identify current room
        current_room = self.navigator.identify_room(vision_text)
        
        # Score obstacle confidence
        obstacle_conf = self.scorer.score_obstacle(proximity_front, vision_text)
        
        # Check for dead end
        is_dead_end = False  # Would need position tracking
        
        decision = {
            "action": "move_forward",
            "reasoning": "Unknown",
            "confidence": 0.5,
            "sensor_value": proximity_front,
            "obstacle_confidence": obstacle_conf.name,
            "current_room": current_room.value,
            "target_room": self.target_room.value if self.target_room else None,
        }
        
        # Decision logic
        if is_stuck:
            # Escape pattern
            if stuck_count == 1:
                decision["action"] = "turn_left_90"
                decision["reasoning"] = "Stuck: explore left"
            elif stuck_count == 2:
                decision["action"] = "turn_right_90"
                decision["reasoning"] = "Stuck: explore right"
            else:
                decision["action"] = "back_up"
                decision["reasoning"] = "Stuck: backup and reset"
            decision["confidence"] = 0.95
        
        # Semantic navigation: if vision says room is ahead, GO
        elif vision_text and "living room" in vision_text.lower() and proximity_front > 300:
            decision["action"] = "move_forward"
            decision["reasoning"] = "Vision says living room ahead - move despite sensor"
            decision["confidence"] = 0.9
        
        elif vision_text and ("kitchen" in vision_text.lower() or "dining" in vision_text.lower()) and proximity_front > 300:
            decision["action"] = "move_forward"
            decision["reasoning"] = "Vision says kitchen ahead - move despite sensor"
            decision["confidence"] = 0.9
        
        # Sensor-based decisions (only when obstacle_conf is HIGH)
        elif obstacle_conf == ObstacleConfidence.CRITICAL:
            decision["action"] = "back_up"
            decision["reasoning"] = "Critical obstacle - backup"
            decision["confidence"] = 0.99
        
        elif obstacle_conf == ObstacleConfidence.HIGH:
            decision["action"] = "turn_left_90"
            decision["reasoning"] = "Obstacle nearby - turn to explore"
            decision["confidence"] = 0.85
        
        elif obstacle_conf in [ObstacleConfidence.NO_OBSTACLE, ObstacleConfidence.LOW]:
            decision["action"] = "move_forward"
            decision["reasoning"] = "Path appears clear - move forward"
            decision["confidence"] = 0.8
        
        # If in target room, look for target
        if current_room == self.target_room and not is_stuck:
            decision["action"] = "move_forward"
            decision["reasoning"] = f"In target room ({self.target_room.value}) - explore"
            decision["confidence"] = 0.95
        
        return decision
