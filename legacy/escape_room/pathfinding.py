"""Pathfinding utilities. BFS is sufficient for an unweighted grid."""

from __future__ import annotations

from collections import deque
from typing import Callable, Dict, List, Optional, Tuple

Position = Tuple[int, int]

MOVES: Dict[str, Position] = {
    "UP": (-1, 0),
    "DOWN": (1, 0),
    "LEFT": (0, -1),
    "RIGHT": (0, 1),
}

Walkable = Callable[[Position], bool]


def bfs(start: Position, goal: Position, walkable: Walkable) -> Optional[List[Position]]:
    """Return the shortest path (inclusive of start and goal) or None."""
    if start == goal:
        return [start]

    queue: deque[Position] = deque([start])
    came_from: dict[Position, Optional[Position]] = {start: None}

    while queue:
        current = queue.popleft()
        for dr, dc in MOVES.values():
            nxt = (current[0] + dr, current[1] + dc)
            if nxt in came_from:
                continue
            # The goal cell itself may not be 'walkable' under normal rules
            # (e.g. the door without the key) — allow stepping onto it explicitly.
            if nxt != goal and not walkable(nxt):
                continue
            if nxt == goal and not walkable(nxt):
                # Goal is unreachable under current rules.
                continue
            came_from[nxt] = current
            if nxt == goal:
                return _reconstruct(came_from, goal)
            queue.append(nxt)
    return None


def _reconstruct(came_from: dict[Position, Optional[Position]], goal: Position) -> List[Position]:
    path: List[Position] = []
    cur: Optional[Position] = goal
    while cur is not None:
        path.append(cur)
        cur = came_from[cur]
    path.reverse()
    return path


def path_to_directions(path: List[Position]) -> List[str]:
    """Convert a list of positions into cardinal direction strings."""
    inv = {v: k for k, v in MOVES.items()}
    dirs: List[str] = []
    for a, b in zip(path, path[1:]):
        delta = (b[0] - a[0], b[1] - a[1])
        dirs.append(inv[delta])
    return dirs
