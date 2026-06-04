"""
Persistent spatial memory — records where objects were seen across sessions.

After each run the agent saves every YOLO-confirmed detection (target class +
GPS position) to logs/spatial_memory.json.  On the next run it loads that file
so the robot can navigate directly to a previously-seen object instead of
re-exploring the whole room.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from src.common.config import LOGS_PATH, WEBOTS_WORLD_FILE

_DEDUP_RADIUS = 0.5   # metres — closer detections are merged


class SpatialMemory:
    """Persistent map of where objects were seen in each world."""

    def __init__(self, path: Optional[str] = None, world: Optional[str] = None):
        self._path = Path(path) if path else LOGS_PATH / "spatial_memory.json"
        # Prefer the world the simulator actually reported (via the TCP
        # controller).  Fall back to the configured world file only when the
        # controller could not detect it, so memory is never keyed to the wrong
        # world when several worlds share one spatial_memory.json.
        self._world_key = (world or "").strip() or Path(WEBOTS_WORLD_FILE).stem
        # {world_key: {target: [{"x":…, "y":…, "conf":…, "ts":…}]}}
        self._data: Dict[str, Dict[str, List[dict]]] = {}
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        try:
            if self._path.exists():
                self._data = json.loads(self._path.read_text())
                world = self._data.get(self._world_key, {})
                n = sum(len(v) for v in world.values())
                print(f"[SpatialMemory] Loaded {n} discoveries for '{self._world_key}'")
                for target, entries in world.items():
                    print(f"  {target}: {[[round(e['x'],1), round(e['y'],1)] for e in entries]}")
        except Exception as e:
            print(f"[SpatialMemory] Load error: {e}")
            self._data = {}

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2))
        except Exception as e:
            print(f"[SpatialMemory] Save error: {e}")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(self, target: str, x: float, y: float, confidence: float) -> bool:
        """
        Record a detection.  Returns True if this is a new entry (not a dedup).
        Existing entries within _DEDUP_RADIUS are updated if new confidence is higher.
        """
        world_data = self._data.setdefault(self._world_key, {})
        entries = world_data.setdefault(target, [])
        for entry in entries:
            if abs(entry["x"] - x) < _DEDUP_RADIUS and abs(entry["y"] - y) < _DEDUP_RADIUS:
                if confidence > entry["conf"]:
                    entry["conf"] = round(confidence, 3)
                    entry["ts"] = int(time.time())
                return False  # duplicate, not new
        entries.append({
            "x": round(x, 2),
            "y": round(y, 2),
            "conf": round(confidence, 3),
            "ts": int(time.time()),
        })
        print(f"[SpatialMemory] NEW discovery: '{target}' @ ({x:.2f},{y:.2f}) conf={confidence:.2f}")
        self.save()
        return True

    def clear_world(self) -> None:
        """Wipe all memories for the current world file."""
        self._data.pop(self._world_key, None)
        self.save()
        print(f"[SpatialMemory] Cleared memories for '{self._world_key}'")

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_positions(self, target: str) -> List[List[float]]:
        """Return all known [x, y] positions for target in the current world."""
        entries = self._data.get(self._world_key, {}).get(target, [])
        return [[e["x"], e["y"]] for e in entries]

    def nearest(
        self, target: str, current_xy: List[float]
    ) -> Optional[List[float]]:
        """Return the closest known [x, y] for target, or None."""
        positions = self.get_positions(target)
        if not positions:
            return None
        cx, cy = current_xy[0], current_xy[1]
        return min(positions, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)

    def has_target(self, target: str) -> bool:
        return bool(self.get_positions(target))

    def summary(self) -> Dict[str, int]:
        return {t: len(v) for t, v in self._data.get(self._world_key, {}).items()}
