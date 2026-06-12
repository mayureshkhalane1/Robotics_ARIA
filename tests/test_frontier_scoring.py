from __future__ import annotations

from src.agent.online_map import OnlineOccupancyGrid


def _make_grid() -> OnlineOccupancyGrid:
    grid = OnlineOccupancyGrid(-1.0, 2.0, -1.0, 2.0, resolution=1.0, robot_radius=0.1)
    for i in range(grid.nx):
        for j in range(grid.ny):
            grid.known[i][j] = True
            grid.score[i][j] = 0
            grid._trav[i][j] = False
    return grid


def test_best_frontier_prefers_more_unknown_space() -> None:
    grid = _make_grid()

    # Two candidate frontiers, both reachable.
    # Front cell at (1.5, 0.5) borders three unknown cells.
    grid.known[2][1] = True
    grid._trav[2][1] = True
    grid.known[1][1] = True
    grid._trav[1][1] = True
    grid.known[2][0] = True
    grid._trav[2][0] = True
    grid.known[3][1] = False
    grid.known[2][2] = False
    grid.known[1][2] = False

    # Side cell at (0.5, 0.5) borders only one unknown cell.
    grid.known[1][2] = False

    front_score = grid.frontier_score(0.0, 0.0, (1.5, 0.5), heading_deg=0.0)
    side_score = grid.frontier_score(0.0, 0.0, (0.5, 0.5), heading_deg=0.0)

    assert front_score > side_score
    assert grid.best_frontier(0.0, 0.0, heading_deg=0.0) == (1.5, 0.5)


def test_frontier_count_counts_reachable_frontiers() -> None:
    grid = _make_grid()
    grid.known[2][2] = True
    grid._trav[2][2] = True
    grid.known[3][2] = False
    grid.known[2][3] = False
    assert grid.frontier_count() >= 1
