"""
Parse the Webots .wbt world file to extract room positions and object locations.

This gives the agent a "training map" of the known environment.
In a new (test) environment, this file is not available and the agent
falls back to pure exploration using YOLO + VLM.
"""

import re
from collections import defaultdict
from math import atan2, degrees, sqrt
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Map fragments in .wbt object names → YOLO/agent target names
_WBT_NAME_TO_TARGET: Dict[str, str] = {
    "chair":        "chair",
    "sofa":         "couch",
    "armchair":     "couch",
    "bottle":       "bottle",
    "cup":          "cup",
    "bed":          "bed",
    "table":        "table",
    "plant":        "plant",
    "sink":         "sink",
    "toilet":       "toilet",
    "clock":        "clock",
    "fridge":       "fridge",
    "refrigerator": "fridge",
    "laptop":       "laptop",
    "tv":           "tv",
    "television":   "tv",
    "monitor":      "tv",
}

# Webots PROTO node type names (line starts with "NodeType {") → target name.
# Used for objects that have no explicit name "..." field.
_WBT_NODE_TO_TARGET: Dict[str, str] = {
    "Sofa":          "couch",
    "Armchair":      "couch",
    "Bed":           "bed",
    "Sink":          "sink",
    "BathroomSink":  "sink",
    "Fridge":        "fridge",
    "Laptop":        "laptop",
    "Television":    "tv",
    "Monitor":       "tv",
    "PottedTree":    "plant",
    "BunchOfSunFlowers": "plant",
    "WaterBottle":   "bottle",
    "BeerBottle":    "bottle",
    "Toilet":        "toilet",
}

# DEF name fragments → canonical room name
_DEF_TO_ROOM: Dict[str, str] = {
    "living_room": "living room",
    "kitchen":     "kitchen",
    "corridor":    "corridor",
    "bathroom":    "bathroom",
    "room_1":      "bedroom",
    "room_2":      "bedroom 2",
    "garden":      "garden",
}

# Which room is most likely to contain each target type
_TARGET_IN_ROOM: Dict[str, str] = {
    "chair":   "kitchen",
    "couch":   "living_room",
    "bottle":  "kitchen",
    "cup":     "kitchen",
    "bed":     "room_1",
    "table":   "kitchen",
    "sink":    "bathroom",
    "toilet":  "bathroom",
    "fridge":  "kitchen",
    "laptop":  "living_room",
    "tv":      "living_room",
    "clock":   "living_room",
    "plant":   "living_room",
}


class WorldMap:
    """Spatial knowledge parsed from a Webots .wbt world file."""

    def __init__(self) -> None:
        self.rooms: Dict[str, List[float]] = {}         # room_key → [x, y]
        self.objects: Dict[str, List[List[float]]] = defaultdict(list)  # target → [[x,y], ...]
        self.available: bool = False

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_positions(self, target: str) -> List[List[float]]:
        """All known positions of target (objects + matching rooms)."""
        positions = list(self.objects.get(target, []))
        # Check if the target is a room name
        for room_key, room_name in _DEF_TO_ROOM.items():
            if target.lower() in room_name.lower():
                if room_key in self.rooms:
                    positions.append(self.rooms[room_key])
        return positions

    def nearest(self, target: str, current_xy: List[float]) -> Optional[List[float]]:
        """Return the closest known position of target to current_xy."""
        positions = self.get_positions(target)
        if not positions:
            # Fallback: if target's room is known, go there
            room_key = _TARGET_IN_ROOM.get(target)
            if room_key and room_key in self.rooms:
                positions = [self.rooms[room_key]]
        if not positions:
            return None
        cx, cy = current_xy[0], current_xy[1]
        return min(positions, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)

    def bearing_to(
        self,
        current_xy: List[float],
        target_xy: List[float],
        heading_deg: float,
    ) -> Tuple[float, float]:
        """
        Return (angle_diff_degrees, distance_meters).

        angle_diff > 0  → turn right to face target
        angle_diff < 0  → turn left to face target

        Convention (derived from Webots Pioneer 3-DX compass readings):
          heading = atan2(compass.bx, compass.bz)
          heading ≈  90° → robot faces world +Y (north)
          heading ≈ -90° → robot faces world -Y (south)
          heading ≈   0° → robot faces world +Z ... (calibrate if off)

        We use: target_bearing = atan2(dx, dy)  (bearing from +Y axis)
        """
        dx = target_xy[0] - current_xy[0]
        dy = target_xy[1] - current_xy[1]
        distance = sqrt(dx ** 2 + dy ** 2)
        if distance < 0.05:
            return 0.0, distance
        target_bearing = degrees(atan2(dx, dy))
        angle_diff = target_bearing - heading_deg
        # Normalise to [-180, 180]
        while angle_diff > 180:
            angle_diff -= 360
        while angle_diff < -180:
            angle_diff += 360
        return angle_diff, distance

    def to_context(self) -> dict:
        """Compact dict injected into the VLM prompt."""
        return {
            "rooms": {k: [round(v[0], 1), round(v[1], 1)] for k, v in self.rooms.items()},
            "objects": {
                k: [[round(p[0], 1), round(p[1], 1)] for p in v]
                for k, v in self.objects.items()
            },
        }


# ------------------------------------------------------------------
# Parser helpers
# ------------------------------------------------------------------

def _add_object(world: "WorldMap", target_name: str, pos: List[float]) -> None:
    """Add pos to world.objects[target_name] if not already close to an existing entry."""
    existing = world.objects[target_name]
    if not any(abs(p[0] - pos[0]) < 0.5 and abs(p[1] - pos[1]) < 0.5 for p in existing):
        world.objects[target_name].append(pos[:])


# ------------------------------------------------------------------
# Parser
# ------------------------------------------------------------------

def parse_world_file(wbt_path: str) -> WorldMap:
    """Parse .wbt file and return a WorldMap with rooms and object positions."""
    world = WorldMap()

    try:
        lines = Path(wbt_path).read_text().splitlines()
    except Exception as e:
        print(f"[WorldMap] Cannot read {wbt_path}: {e}")
        return world

    last_xy: Optional[List[float]] = None
    pending_room_key: Optional[str] = None    # DEF room seen, awaiting its translation
    pending_node_target: Optional[str] = None  # node-type object seen, awaiting its translation

    for line in lines:
        s = line.strip()

        # Track the most-recently-seen translation (x y)
        m = re.match(r"^translation\s+([-\d.eE+]+)\s+([-\d.eE+]+)", s)
        if m:
            last_xy = [float(m.group(1)), float(m.group(2))]
            # Resolve any pending deferred detections with this translation
            if pending_room_key is not None:
                world.rooms[pending_room_key] = last_xy[:]
                pending_room_key = None
            if pending_node_target is not None:
                _add_object(world, pending_node_target, last_xy)
                pending_node_target = None
            continue

        # Room: DEF ROOM_KEY Pose {  — defer position until we see its translation
        m = re.match(r"^DEF\s+([A-Z][A-Z0-9_]+)\s+Pose", s)
        if m:
            def_name = m.group(1).lower()
            pending_room_key = None
            for room_key in _DEF_TO_ROOM:
                if room_key in def_name:
                    pending_room_key = room_key
                    break

        # Node type: "NodeType {" at start of line — catches un-named objects.
        # Defer until the translation INSIDE the block is read.
        m = re.match(r"^([A-Z][A-Za-z0-9_]+)\s*\{", s)
        if m:
            node_type = m.group(1)
            target_name = _WBT_NODE_TO_TARGET.get(node_type)
            if target_name:
                pending_node_target = target_name

        # Named object: name "..."  (resolves pending node-type detection with exact name)
        m = re.match(r'^name\s+"([^"]+)"', s)
        if m and last_xy:
            pending_node_target = None  # name field supersedes the node-type guess
            obj_name = m.group(1).lower()
            for fragment, target_name in _WBT_NAME_TO_TARGET.items():
                if fragment in obj_name:
                    _add_object(world, target_name, last_xy)
                    break

    world.available = bool(world.rooms or world.objects)
    n_obj = sum(len(v) for v in world.objects.values())
    print(f"[WorldMap] Parsed: {len(world.rooms)} rooms, {n_obj} object positions")
    for room_key, pos in world.rooms.items():
        print(f"  room  {room_key:15s} @ {pos}")
    for target, positions in world.objects.items():
        print(f"  obj   {target:15s} @ {positions}")
    return world


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------

_world_map: Optional[WorldMap] = None


def get_world_map(wbt_path: Optional[str] = None) -> WorldMap:
    """Return the global WorldMap, parsing the .wbt file on first call."""
    global _world_map
    if _world_map is None:
        if wbt_path is None:
            from src.common.config import WEBOTS_WORLD_FILE
            wbt_path = WEBOTS_WORLD_FILE
        _world_map = parse_world_file(wbt_path)
    return _world_map
