"""
Grid-based systematic exploration (boustrophedon / lawnmower pattern).

Parses the Floor node from the active .wbt file to compute room bounds, then
lays a regular grid of waypoints across the room.  The robot visits each
waypoint in column order (reversing direction each column, like a vacuum) and
does a 360° YOLO sweep at every stop before moving on.
"""

import re
from math import atan2, degrees, sqrt
from pathlib import Path
from typing import List, Optional, Tuple


# -------------------------------------------------------------------------
# Floor-bounds parser
# -------------------------------------------------------------------------

def parse_floor_bounds(wbt_path: str) -> Tuple[float, float, float, float]:
    """
    Return (min_x, max_x, min_y, max_y) of the navigable area.

    Reads the Floor PROTO from the .wbt file (translation + rotation + size)
    and insets a wall-clearance margin so waypoints don't overlap with walls.
    Falls back to a generous default if parsing fails.
    """
    try:
        text = Path(wbt_path).read_text()

        # Locate the Floor block (greedy match up to closing brace)
        m_block = re.search(r'Floor\s*\{(.+?)\n\}', text, re.DOTALL)
        if not m_block:
            raise ValueError("No Floor node found")
        block = m_block.group(1)

        # translation X Y Z
        m = re.search(r'translation\s+([-\d.eE+]+)\s+([-\d.eE+]+)', block)
        cx, cy = (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)

        # size W H
        m = re.search(r'size\s+([\d.eE+]+)\s+([\d.eE+]+)', block)
        sw, sh = (float(m.group(1)), float(m.group(2))) if m else (6.0, 6.0)

        # rotation 0 0 1 ANGLE (Z-axis rotation)
        m = re.search(
            r'rotation\s+[-\d.eE+]+\s+[-\d.eE+]+\s+[-\d.eE+]+\s+([-\d.eE+]+)',
            block,
        )
        rot_z = abs(float(m.group(1))) if m else 0.0

        # A 90° rotation swaps the two size axes in world space
        if 1.4 < rot_z < 1.7:
            sw, sh = sh, sw

        margin = 0.9  # metres clearance from each wall
        min_x = cx - sw / 2 + margin
        max_x = cx + sw / 2 - margin
        min_y = cy - sh / 2 + margin
        max_y = cy + sh / 2 - margin

        print(
            f"[GridExplorer] Floor: centre=({cx:.1f},{cy:.1f}) "
            f"world_size=({sw:.1f}×{sh:.1f}) "
            f"navigable x=[{min_x:.1f},{max_x:.1f}] y=[{min_y:.1f},{max_y:.1f}]"
        )
        return min_x, max_x, min_y, max_y

    except Exception as e:
        print(f"[GridExplorer] Floor parse error: {e}  — using default bounds")
        return -5.0, 5.0, -2.0, 4.0


# -------------------------------------------------------------------------
# GridExplorer
# -------------------------------------------------------------------------

class GridExplorer:
    """
    Generates boustrophedon waypoints and tracks which have been visited.

    Usage in the agent loop
    -----------------------
    1. On each step, call ``next_waypoint(pos)`` to get the current target.
    2. Call ``get_nav_action(pos, waypoint, heading)`` → action string.
    3. When the action is "arrived", call ``start_scan()`` then repeatedly
       call ``scan_step()`` until ``scan_done()`` is True.
    4. After scan is done, call ``mark_current_visited()`` and loop.
    """

    ARRIVAL_RADIUS = 0.6   # metres — how close counts as "arrived"
    TURN_ANGLE_THRESHOLD = 40   # degrees — threshold to choose turn vs forward

    def __init__(self, wbt_path: str, grid_spacing: float = 1.5):
        min_x, max_x, min_y, max_y = parse_floor_bounds(wbt_path)
        self.waypoints: List[Tuple[float, float]] = self._boustrophedon(
            min_x, max_x, min_y, max_y, grid_spacing
        )
        self.visited: List[bool] = [False] * len(self.waypoints)
        self._active_idx: Optional[int] = None
        self._scan_turns_left: int = 0   # turns remaining for 360° sweep
        print(f"[GridExplorer] {len(self.waypoints)} waypoints across the room")
        for i, wp in enumerate(self.waypoints):
            print(f"  wp{i:02d} ({wp[0]:.1f},{wp[1]:.1f})")

    # ------------------------------------------------------------------
    # Waypoint generation
    # ------------------------------------------------------------------

    def _boustrophedon(
        self,
        min_x: float, max_x: float,
        min_y: float, max_y: float,
        spacing: float,
    ) -> List[Tuple[float, float]]:
        xs, x = [], min_x
        while x <= max_x + 0.01:
            xs.append(round(x, 2))
            x += spacing

        ys, y = [], min_y
        while y <= max_y + 0.01:
            ys.append(round(y, 2))
            y += spacing

        waypoints: List[Tuple[float, float]] = []
        for col_idx, col_x in enumerate(xs):
            col_ys = ys if col_idx % 2 == 0 else list(reversed(ys))
            for row_y in col_ys:
                waypoints.append((col_x, row_y))
        return waypoints

    # ------------------------------------------------------------------
    # Waypoint management
    # ------------------------------------------------------------------

    def nearest_unvisited(
        self, current_pos: Tuple[float, float]
    ) -> Optional[Tuple[int, Tuple[float, float]]]:
        """Return (index, waypoint) of the nearest unvisited waypoint."""
        cx, cy = current_pos
        best = None
        best_dist = float("inf")
        for i, (wx, wy) in enumerate(self.waypoints):
            if self.visited[i]:
                continue
            d = sqrt((wx - cx) ** 2 + (wy - cy) ** 2)
            if d < best_dist:
                best_dist = d
                best = (i, (wx, wy))
        return best

    def set_active(self, idx: int) -> None:
        self._active_idx = idx

    def mark_current_visited(self) -> None:
        if self._active_idx is not None:
            self.visited[self._active_idx] = True
            print(
                f"[GridExplorer] Waypoint {self._active_idx} visited. "
                f"{self.progress()}"
            )
            self._active_idx = None

    def all_visited(self) -> bool:
        return all(self.visited)

    def progress(self) -> str:
        done = sum(self.visited)
        return f"{done}/{len(self.waypoints)} waypoints visited"

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def get_nav_action(
        self,
        current_pos: Tuple[float, float],
        target_pos: Tuple[float, float],
        heading_deg: float,
    ) -> Tuple[str, float]:
        """
        Return (action, distance) toward target_pos.

        Heading convention (empirically derived from Webots Pioneer 3-DX):
          heading = atan2(compass.bx, compass.bz)
          heading =   0°  →  robot faces world +X (east)
          heading =  90°  →  robot faces world +Y (north)
          heading = -90°  →  robot faces world -Y (south)

        Bearing = standard math angle: atan2(dy, dx)
          bearing =   0°  →  target is due east  (+X)
          bearing =  90°  →  target is due north (+Y)

        Turn direction:
          angle_diff > 0  →  CCW / turn LEFT  (heading increases)
          angle_diff < 0  →  CW  / turn RIGHT (heading decreases)
        """
        dx = target_pos[0] - current_pos[0]
        dy = target_pos[1] - current_pos[1]
        dist = sqrt(dx ** 2 + dy ** 2)

        if dist <= self.ARRIVAL_RADIUS:
            return "arrived", dist

        target_bearing = degrees(atan2(dy, dx))
        angle_diff = target_bearing - heading_deg
        while angle_diff > 180:
            angle_diff -= 360
        while angle_diff < -180:
            angle_diff += 360

        if angle_diff > self.TURN_ANGLE_THRESHOLD:
            return "turn_left_90", dist
        elif angle_diff < -self.TURN_ANGLE_THRESHOLD:
            return "turn_right_90", dist
        else:
            return "move_forward", dist

    # ------------------------------------------------------------------
    # 360° scan state machine
    # ------------------------------------------------------------------

    def start_scan(self) -> None:
        """Begin a 360° sweep (3 additional 90° turns after first look)."""
        self._scan_turns_left = 3

    def scan_step(self) -> str:
        """Return the action for this scan step (always turn_right_90)."""
        if self._scan_turns_left > 0:
            self._scan_turns_left -= 1
        return "turn_right_90"

    def scan_done(self) -> bool:
        return self._scan_turns_left == 0

    def scanning(self) -> bool:
        return self._scan_turns_left > 0
