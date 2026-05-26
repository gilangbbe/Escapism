"""Deterministic mock LLM client.

Used as a zero-dependency stand-in for a real LLM:
- Lets the scaffold run with no network / no daemon.
- Gives a reproducible smoke test for the full Perceive → Act loop.

It parses authoritative location hints the cognitive loop embeds in
the user prompt (e.g. `Key 'key-1' location: (3, 4)`) plus the
`Inventory:` and `Objects on your tile:` lines, then runs BFS over the
ASCII map block to plan the next move. It always emits the same JSON
action schema a real LLM is expected to produce.
"""

from __future__ import annotations

import ast
import json
import re
from typing import List, Optional, Tuple

from ..pathfinding import bfs, path_to_directions
from .base import LLMClient, Message

Position = Tuple[int, int]

_MAP_RE = re.compile(r"<<<MAP>>>\s*\n(.*?)\n<<<END_MAP>>>", re.DOTALL)
_INV_RE = re.compile(r"Inventory:\s*\[(.*?)\]")
_HERE_RE = re.compile(r"Objects on your tile:\s*(\[.*?\])")
_KEY_LOC_RE = re.compile(r"Key '([^']+)' location:\s*(\(\d+,\s*\d+\)|in an agent's inventory)")
_DOOR_LOC_RE = re.compile(r"Door '([^']+)' location:\s*(\(\d+,\s*\d+\))(?:\s*\[(locked|unlocked)\])?")
_POS_RE = re.compile(r"Your position:\s*\((\d+),\s*(\d+)\)")


class MockLLMClient(LLMClient):
    name = "mock"

    def chat(self, messages: List[Message], *, json_mode: bool = False) -> str:
        blob = "\n".join(m.content for m in messages if m.role == "user")
        return json.dumps(self._plan(blob))

    # ---------- planning ----------

    def _plan(self, blob: str) -> dict:
        agent_pos = self._agent_pos(blob)
        grid = self._parse_map(blob)
        has_key, key_id, key_pos = self._key_state(blob)
        door_id, door_pos, door_locked = self._door_state(blob)
        here = self._objects_here(blob)

        if grid is None or agent_pos is None:
            return self._wait("Cannot read map / position.")

        # 1. Standing on the key → pick it up.
        if not has_key and key_id and key_id in here:
            return self._act("PICKUP", {"object_id": key_id}, "I'm on the key.", "Picking up the key.")

        # 2. Adjacent to (or on) a locked door with key → use it.
        if has_key and door_id and door_pos and door_locked and self._manhattan(agent_pos, door_pos) <= 1:
            return self._act(
                "USE",
                {"item": key_id or "key-1", "target": door_id},
                "Door's right here and I have the key.",
                "Unlocking the door.",
            )

        # 3. Otherwise plan a path to the active sub-goal.
        if not has_key:
            target = key_pos
            label = "the key"
        else:
            target = door_pos
            label = "the door"

        if target is None:
            return self._wait("Don't know where to go yet.")

        walkable = self._walkable_factory(grid, door_pos, door_locked, has_key)
        path = bfs(agent_pos, target, walkable)
        if not path or len(path) < 2:
            return self._wait(f"No path to {label}.")

        direction = path_to_directions(path)[0]
        return self._act(
            "MOVE",
            {"direction": direction},
            f"Heading {direction.lower()} toward {label}.",
            f"Moving {direction.lower()}.",
        )

    # ---------- helpers ----------

    @staticmethod
    def _act(verb: str, args: dict, thought: str, say: str) -> dict:
        return {"thought": thought, "say": say, "action": {"verb": verb, "args": args}}

    @staticmethod
    def _wait(reason: str) -> dict:
        return {"thought": reason, "say": "Hmm, thinking...", "action": {"verb": "WAIT", "args": {}}}

    @staticmethod
    def _manhattan(a: Position, b: Position) -> int:
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    @staticmethod
    def _agent_pos(blob: str) -> Optional[Position]:
        m = _POS_RE.search(blob)
        return (int(m.group(1)), int(m.group(2))) if m else None

    @staticmethod
    def _objects_here(blob: str) -> List[str]:
        m = _HERE_RE.search(blob)
        if not m:
            return []
        try:
            return list(ast.literal_eval(m.group(1)))
        except (ValueError, SyntaxError):
            return []

    @staticmethod
    def _key_state(blob: str) -> tuple[bool, Optional[str], Optional[Position]]:
        inv = _INV_RE.search(blob)
        inv_str = inv.group(1) if inv else ""
        m = _KEY_LOC_RE.search(blob)
        if not m:
            return ("key-1" in inv_str, "key-1" if "key-1" in inv_str else None, None)
        key_id = m.group(1)
        loc = m.group(2)
        if loc.startswith("("):
            pos = ast.literal_eval(loc)
            return (key_id in inv_str, key_id, (int(pos[0]), int(pos[1])))
        return (True, key_id, None)

    @staticmethod
    def _door_state(blob: str) -> tuple[Optional[str], Optional[Position], bool]:
        m = _DOOR_LOC_RE.search(blob)
        if not m:
            return (None, None, True)
        door_id = m.group(1)
        pos = ast.literal_eval(m.group(2))
        locked = (m.group(3) or "locked") == "locked"
        return (door_id, (int(pos[0]), int(pos[1])), locked)

    @staticmethod
    def _parse_map(blob: str) -> Optional[list[list[str]]]:
        m = _MAP_RE.search(blob)
        if not m:
            return None
        rows = [[c for c in line if c != " "] for line in m.group(1).splitlines() if line.strip()]
        return rows or None

    @staticmethod
    def _walkable_factory(grid, door_pos, door_locked, has_key):
        h = len(grid)
        w = len(grid[0]) if grid else 0

        def walkable(pos: Position) -> bool:
            r, c = pos
            if not (0 <= r < h and 0 <= c < w):
                return False
            if grid[r][c] == "#":
                return False
            if (r, c) == door_pos and door_locked and not has_key:
                return False
            return True

        return walkable
