"""
Online occupancy grid + frontier exploration — built from the robot's own
sensors, NOT from the .wbt file.

The robot starts knowing nothing about the room.  Every step it ray-casts its
sonar ring into a grid of {unknown, free, occupied} cells using only its
GPS+compass pose.  Exploration is driven by *frontiers* — free cells that touch
unknown space — so the robot autonomously drives toward whatever it hasn't seen
yet, flowing through any opening/gap/ramp it discovers without ever being told
where the walls are.

Nothing here depends on wall colour, object identity, or the world layout.

Sonar model
-----------
Pioneer 3-DX has up to 16 sonars ("so0".."so15") in a ring.  Webots returns a
lookup-table value where HIGHER ≈ CLOSER.  With the default Pioneer table
(0 m → ~1024, max_range → 0) the distance is ``d ≈ max_range * (1 - v/1024)``.
A near-zero reading means "no echo" → free out to max range.  ``VALUE_MAX`` and
``MAX_RANGE`` are the only calibration constants; tune them if a verification
run shows obstacles mapped at the wrong distance.
"""

from __future__ import annotations

import re
from collections import deque
from math import cos, sin, radians, degrees, hypot, ceil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

Point = Tuple[float, float]


def parse_floor_extent(wbt_path: str) -> Tuple[float, float, float, float]:
    """Full floor extent (min_x, max_x, min_y, max_y) — used ONLY to size the
    grid's coordinate frame.  This is the room's bounding box (a dimension), not
    knowledge of where the obstacles are; every cell still starts UNKNOWN and is
    discovered by the sensors."""
    try:
        text = Path(wbt_path).read_text()
        m = re.search(r'Floor\s*\{(.*?)\n\}', text, re.DOTALL)
        cx = cy = 0.0
        sw, sh = 14.0, 14.0
        if m:
            b = m.group(1)
            t = re.search(r'translation\s+([-\d.eE+]+)\s+([-\d.eE+]+)', b)
            if t:
                cx, cy = float(t.group(1)), float(t.group(2))
            s = re.search(r'size\s+([\d.eE+]+)\s+([\d.eE+]+)', b)
            if s:
                sw, sh = float(s.group(1)), float(s.group(2))
            r = re.search(r'rotation\s+[-\d.eE+]+\s+[-\d.eE+]+\s+[-\d.eE+]+\s+([-\d.eE+]+)', b)
            if r and 1.4 < abs(float(r.group(1))) < 1.7:
                sw, sh = sh, sw
        margin = 0.5
        return cx - sw / 2 - margin, cx + sw / 2 + margin, cy - sh / 2 - margin, cy + sh / 2 + margin
    except Exception:
        return -8.0, 8.0, -8.0, 8.0

# Pioneer 3-DX sonar bearings (degrees from robot forward +X, CCW positive).
SONAR_ANGLES_DEG: Dict[int, float] = {
    0: 90, 1: 50, 2: 30, 3: 10, 4: -10, 5: -30, 6: -50, 7: -90,
    8: -90, 9: -130, 10: -150, 11: -170, 12: 170, 13: 150, 14: 130, 15: 90,
}

UNKNOWN, FREE, OCC = -1, 0, 1


def _sonar_index(name: str) -> Optional[int]:
    m = re.search(r"(\d+)$", name)
    return int(m.group(1)) if m else None


class OnlineOccupancyGrid:
    VALUE_MAX = 1024.0      # sonar value at distance 0
    MAX_RANGE = 5.0         # metres — sonar max range
    NO_ECHO_VALUE = 40.0    # readings below this → "nothing there", free to max range

    def __init__(
        self,
        min_x: float, max_x: float, min_y: float, max_y: float,
        resolution: float = 0.15,
        robot_radius: float = 0.22,
    ):
        self.min_x, self.max_x = min_x, max_x
        self.min_y, self.max_y = min_y, max_y
        self.res = resolution
        self.robot_radius = robot_radius
        self.nx = max(1, int((max_x - min_x) / resolution) + 1)
        self.ny = max(1, int((max_y - min_y) / resolution) + 1)
        self._infl_cells = max(1, ceil(robot_radius / resolution))

        # log-odds-ish score per cell + whether it's been observed at all
        self.known = [[False] * self.ny for _ in range(self.nx)]
        self.score = [[0] * self.ny for _ in range(self.nx)]
        self.visited = [[False] * self.ny for _ in range(self.nx)]
        self.blocked: set = set()        # frontier cells we gave up reaching

    # --- transforms ---
    def _to_cell(self, x: float, y: float) -> Tuple[int, int]:
        return int((x - self.min_x) / self.res), int((y - self.min_y) / self.res)

    def _to_world(self, i: int, j: int) -> Point:
        return self.min_x + (i + 0.5) * self.res, self.min_y + (j + 0.5) * self.res

    def _in_bounds(self, i: int, j: int) -> bool:
        return 0 <= i < self.nx and 0 <= j < self.ny

    # --- cell classification ---
    def _cls(self, i: int, j: int) -> int:
        if not self._in_bounds(i, j) or not self.known[i][j]:
            return UNKNOWN
        return OCC if self.score[i][j] > 0 else FREE

    def is_free(self, x: float, y: float) -> bool:
        return self._cls(*self._to_cell(x, y)) == FREE

    # --- sensor update ---
    def _obs_free(self, i: int, j: int) -> None:
        if self._in_bounds(i, j):
            self.known[i][j] = True
            self.score[i][j] = max(-5, self.score[i][j] - 1)

    def _obs_occ(self, i: int, j: int) -> None:
        if self._in_bounds(i, j):
            self.known[i][j] = True
            self.score[i][j] = min(5, self.score[i][j] + 2)

    # Sonar beam is wide, so sweep a cone of sub-rays per sensor to fill the
    # wedges between the 16 beams (otherwise they look like frontiers).  FREE is
    # marked across the whole cone; OCCUPIED only on the centre ray, so a real
    # doorway is never blurred shut by a wide cone.  The live sonar safety
    # override is the actual collision backstop, so the map only has to *guide*
    # exploration — it need not be metrically perfect.
    _CONE_HALF_DEG = 16.0
    _CONE_STEP_DEG = 4.0

    def update(self, x: float, y: float, heading_deg: float, proximity: Dict[str, float]) -> None:
        """Fuse one sonar scan taken at world pose (x, y, heading_deg)."""
        ci, cj = self._to_cell(x, y)
        if self._in_bounds(ci, cj):
            self.visited[ci][cj] = True
            self._obs_free(ci, cj)

        sub = []
        s = -self._CONE_HALF_DEG
        while s <= self._CONE_HALF_DEG + 1e-6:
            sub.append(s)
            s += self._CONE_STEP_DEG

        for name, raw in proximity.items():
            idx = _sonar_index(name)
            if idx is None or idx not in SONAR_ANGLES_DEG:
                continue
            try:
                v = float(raw)
            except (TypeError, ValueError):
                continue
            if v < 0:
                continue

            v = min(v, self.VALUE_MAX)
            if v <= self.NO_ECHO_VALUE:
                d, hit = self.MAX_RANGE, False
            else:
                d = self.MAX_RANGE * (1.0 - v / self.VALUE_MAX)
                hit = True

            base = heading_deg + SONAR_ANGLES_DEG[idx]
            free_to = max(0.0, d - self.res)
            n = int(free_to / self.res)
            for ds in sub:
                a = radians(base + ds)
                ca, sa = cos(a), sin(a)
                for k in range(n):                       # free across whole cone
                    r = k * self.res
                    self._obs_free(*self._to_cell(x + ca * r, y + sa * r))
                if hit and abs(ds) < self._CONE_STEP_DEG / 2:   # occ on centre ray only
                    self._obs_occ(*self._to_cell(x + ca * d, y + sa * d))

    def update_lidar(self, x: float, y: float, heading_deg: float, lidar: Dict) -> None:
        """Fuse one dense Lidar scan.  ``lidar`` = {ranges, fov, resolution,
        max_range} as sent by the controller.  Each ray is cast independently —
        with hundreds of rays the walls come out solid and any doorway/gap shows
        up as a long ray between short ones, so openings are preserved with no
        cone tuning.

        Webots range image: index 0 = +fov/2 (robot's left), increasing index
        sweeps clockwise to -fov/2.  If a verification run shows the map
        mirrored/rotated, flip the sign of ``rel`` below (single line).
        """
        ranges = lidar.get("ranges") or []
        if not ranges:
            return
        n = len(ranges)
        fov = float(lidar.get("fov", 6.2831853))
        max_range = float(lidar.get("max_range", self.MAX_RANGE))
        step = fov / n

        ci, cj = self._to_cell(x, y)
        if self._in_bounds(ci, cj):
            self.visited[ci][cj] = True
            self._obs_free(ci, cj)

        for i, r in enumerate(ranges):
            rel = fov * 0.5 - (i + 0.5) * step          # ray bearing rel. to robot
            a = radians(heading_deg + degrees(rel))
            ca, sa = cos(a), sin(a)
            if r is None or r < 0 or r != r or r >= max_range * 0.98:
                d, hit = max_range, False               # no return → free to max
            else:
                d, hit = float(r), True
            m = int(max(0.0, d - self.res) / self.res)
            for k in range(m):                          # free along the ray
                rr = k * self.res
                self._obs_free(*self._to_cell(x + ca * rr, y + sa * rr))
            if hit:
                self._obs_occ(*self._to_cell(x + ca * d, y + sa * d))

    # --- traversability (free + clearance from obstacles) ---
    def _traversable(self, i: int, j: int) -> bool:
        if self._cls(i, j) != FREE:
            return False
        r = self._infl_cells
        for di in range(-r, r + 1):
            for dj in range(-r, r + 1):
                if self._cls(i + di, j + dj) == OCC:
                    return False
        return True

    def _nearest_traversable(self, i: int, j: int, max_r: int = 6) -> Optional[Tuple[int, int]]:
        if self._traversable(i, j):
            return (i, j)
        for r in range(1, max_r + 1):
            for di in range(-r, r + 1):
                for dj in range(-r, r + 1):
                    if max(abs(di), abs(dj)) != r:
                        continue
                    if self._traversable(i + di, j + dj):
                        return (i + di, j + dj)
        return None

    # --- BFS over traversable cells ---
    _NBRS = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]

    def _bfs(self, start_cell, goal_cell=None):
        """BFS from start over traversable cells.  If goal_cell given, returns
        the path (list of cells) to it; else returns (came_from, order)."""
        came = {start_cell: None}
        q = deque([start_cell])
        order = [start_cell]
        while q:
            cur = q.popleft()
            if goal_cell is not None and cur == goal_cell:
                path = []
                while cur is not None:
                    path.append(cur)
                    cur = came[cur]
                return path[::-1]
            ci, cj = cur
            for di, dj in self._NBRS:
                ni, nj = ci + di, cj + dj
                if (ni, nj) in came or not self._traversable(ni, nj):
                    continue
                if di != 0 and dj != 0:  # no diagonal corner-cutting
                    if not (self._traversable(ci + di, cj) and self._traversable(ci, cj + dj)):
                        continue
                came[(ni, nj)] = cur
                q.append((ni, nj))
                order.append((ni, nj))
        return (came, order) if goal_cell is None else None

    def _is_frontier(self, i: int, j: int) -> bool:
        """A traversable cell that touches unknown space = worth exploring."""
        if (i, j) in self.blocked or self._cls(i, j) != FREE:
            return False
        for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            if self._cls(i + di, j + dj) == UNKNOWN:
                return True
        return False

    def blacklist(self, x: float, y: float, radius: float = 0.4) -> None:
        """Give up on the area around (x, y) as an exploration target — it
        could not be reached (e.g. blocked by furniture the Lidar missed)."""
        ci, cj = self._to_cell(x, y)
        r = max(1, int(radius / self.res))
        for di in range(-r, r + 1):
            for dj in range(-r, r + 1):
                self.blocked.add((ci + di, cj + dj))

    # --- public planning API ---
    def nearest_frontier(self, x: float, y: float, min_dist: float = 0.45) -> Optional[Point]:
        """Nearest reachable frontier cell, in world coords (or None if the
        whole reachable area has been explored)."""
        start = self._nearest_traversable(*self._to_cell(x, y))
        if start is None:
            return None
        came, order = self._bfs(start)
        for cell in order:                      # BFS order == nearest first
            if self._is_frontier(*cell):
                wx, wy = self._to_world(*cell)
                if hypot(wx - x, wy - y) >= min_dist:
                    return (wx, wy)
        # fall back to the closest frontier even if very near
        for cell in order:
            if self._is_frontier(*cell):
                return self._to_world(*cell)
        return None

    def next_step_toward(self, x: float, y: float, goal: Point, lookahead: float = 0.6) -> Optional[Point]:
        start = self._nearest_traversable(*self._to_cell(x, y))
        goal_c = self._nearest_traversable(*self._to_cell(*goal))
        if start is None or goal_c is None:
            return None
        path = self._bfs(start, goal_c)
        if not path:
            return None
        cells = [self._to_world(i, j) for i, j in path]
        acc, prev = 0.0, cells[0]
        for p in cells[1:]:
            acc += hypot(p[0] - prev[0], p[1] - prev[1])
            prev = p
            if acc >= lookahead:
                return p
        return cells[-1]

    def reachable(self, x: float, y: float, goal: Point) -> bool:
        start = self._nearest_traversable(*self._to_cell(x, y))
        goal_c = self._nearest_traversable(*self._to_cell(*goal))
        if start is None or goal_c is None:
            return False
        return self._bfs(start, goal_c) is not None

    def open_direction_target(self, x: float, y: float, heading_deg: float,
                              proximity: Dict[str, float], reach: float = 1.0) -> Point:
        """Reactive fallback when there are no frontiers yet (e.g. first steps):
        head toward the most-open sonar bearing."""
        best_ang, best_d = heading_deg, -1.0
        for name, raw in proximity.items():
            idx = _sonar_index(name)
            if idx is None or idx not in SONAR_ANGLES_DEG:
                continue
            try:
                v = min(float(raw), self.VALUE_MAX)
            except (TypeError, ValueError):
                continue
            d = self.MAX_RANGE if v <= self.NO_ECHO_VALUE else self.MAX_RANGE * (1 - v / self.VALUE_MAX)
            if d > best_d:
                best_d, best_ang = d, heading_deg + SONAR_ANGLES_DEG[idx]
        a = radians(best_ang)
        return (x + cos(a) * reach, y + sin(a) * reach)

    # --- stats / debug ---
    def stats(self) -> Dict[str, int]:
        free = occ = unk = 0
        for i in range(self.nx):
            for j in range(self.ny):
                c = self._cls(i, j)
                free += c == FREE
                occ += c == OCC
                unk += c == UNKNOWN
        return {"free": free, "occupied": occ, "unknown": unk}

    def ascii_art(self, marks: Optional[List[Tuple[Point, str]]] = None) -> str:
        ch = {UNKNOWN: " ", FREE: ".", OCC: "#"}
        grid = [[ch[self._cls(i, j)] for i in range(self.nx)] for j in range(self.ny)]
        for (x, y), c in (marks or []):
            i, j = self._to_cell(x, y)
            if self._in_bounds(i, j):
                grid[j][i] = c
        return "\n".join("".join(r) for r in reversed(grid))
