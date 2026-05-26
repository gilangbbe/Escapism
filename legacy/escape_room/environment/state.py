"""World state: tiles, objects, agent bodies, inventories, and global flags.

`WorldState` is the source of truth. Agents do *not* mutate it directly;
they submit `Action` objects which the `ActionValidator` accepts or
rejects, after which `WorldState.apply` performs the mutation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .ontology import ObjectType, TileType, WorldObject

Position = Tuple[int, int]

DIRECTIONS: Dict[str, Position] = {
    "UP": (-1, 0),
    "DOWN": (1, 0),
    "LEFT": (0, -1),
    "RIGHT": (0, 1),
}


@dataclass
class Action:
    """A verb instance submitted by an agent for one turn."""

    actor_id: str
    verb: str
    args: Dict[str, object] = field(default_factory=dict)
    thought: str = ""
    say: str = ""


@dataclass
class AgentBody:
    """The world's view of an agent: position + inventory. Beliefs live on the agent."""

    agent_id: str
    position: Position
    inventory: List[str] = field(default_factory=list)  # object_ids
    escaped: bool = False


@dataclass
class WorldState:
    tiles: List[List[TileType]]
    objects: Dict[str, WorldObject] = field(default_factory=dict)
    bodies: Dict[str, AgentBody] = field(default_factory=dict)
    flags: Dict[str, bool] = field(default_factory=dict)

    # ---------- construction ----------

    @classmethod
    def from_ascii(cls, layout: str) -> "WorldState":
        rows = [ln for ln in layout.strip("\n").splitlines() if ln]
        width = max(len(r) for r in rows)
        tiles: List[List[TileType]] = []
        objects: Dict[str, WorldObject] = {}
        for r, line in enumerate(rows):
            row: List[TileType] = []
            for c, ch in enumerate(line.ljust(width)):
                if ch == "#":
                    row.append(TileType.WALL)
                elif ch == "K":
                    row.append(TileType.FLOOR)
                    objects["key-1"] = WorldObject("key-1", ObjectType.KEY, (r, c))
                elif ch == "D":
                    row.append(TileType.FLOOR)
                    objects["door-1"] = WorldObject(
                        "door-1", ObjectType.DOOR, (r, c), {"locked": True}
                    )
                else:
                    row.append(TileType.FLOOR)
            tiles.append(row)
        return cls(tiles=tiles, objects=objects)

    # ---------- queries ----------

    @property
    def height(self) -> int:
        return len(self.tiles)

    @property
    def width(self) -> int:
        return len(self.tiles[0]) if self.tiles else 0

    def in_bounds(self, pos: Position) -> bool:
        r, c = pos
        return 0 <= r < self.height and 0 <= c < self.width

    def tile_at(self, pos: Position) -> TileType:
        return self.tiles[pos[0]][pos[1]]

    def objects_at(self, pos: Position) -> List[WorldObject]:
        return [o for o in self.objects.values() if o.position == pos]

    def adjacent_positions(self, pos: Position) -> Dict[str, Position]:
        return {d: (pos[0] + dr, pos[1] + dc) for d, (dr, dc) in DIRECTIONS.items()}

    def is_passable(self, pos: Position) -> bool:
        """True if an agent can stand on this tile (walls block; locked doors block)."""
        if not self.in_bounds(pos):
            return False
        if self.tile_at(pos) == TileType.WALL:
            return False
        for obj in self.objects_at(pos):
            if obj.type == ObjectType.DOOR and obj.properties.get("locked", True):
                return False
        return True

    def perceive(self, agent_id: str, radius: int = 1) -> Dict[str, object]:
        """Build a structured perception for the given agent."""
        body = self.bodies[agent_id]
        r0, c0 = body.position
        visible_objects: List[Dict[str, object]] = []
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                p = (r0 + dr, c0 + dc)
                if not self.in_bounds(p):
                    continue
                for o in self.objects_at(p):
                    visible_objects.append(
                        {
                            "id": o.obj_id,
                            "type": o.type.value,
                            "position": list(p),
                            "properties": dict(o.properties),
                            "relative": [dr, dc],
                        }
                    )
        neighbours = {
            d: {
                "position": list(p),
                "tile": self.tile_at(p).value if self.in_bounds(p) else "out",
                "passable": self.is_passable(p),
            }
            for d, p in self.adjacent_positions(body.position).items()
        }
        return {
            "agent_id": agent_id,
            "position": list(body.position),
            "inventory": list(body.inventory),
            "tile_here": self.tile_at(body.position).value,
            "objects_here": [o.obj_id for o in self.objects_at(body.position)],
            "neighbours": neighbours,
            "visible_objects": visible_objects,
        }

    # ---------- mutations (called by validator after a successful check) ----------

    def add_body(self, agent_id: str, position: Position) -> None:
        if not self.is_passable(position):
            raise ValueError(f"Cannot place {agent_id} at {position}.")
        self.bodies[agent_id] = AgentBody(agent_id=agent_id, position=position)

    def move(self, agent_id: str, direction: str) -> None:
        dr, dc = DIRECTIONS[direction]
        body = self.bodies[agent_id]
        body.position = (body.position[0] + dr, body.position[1] + dc)

    def pickup(self, agent_id: str, obj_id: str) -> None:
        self.bodies[agent_id].inventory.append(obj_id)
        # Remove from world map by parking it at sentinel (-1, -1).
        self.objects[obj_id].position = (-1, -1)

    def unlock_door(self, door_id: str) -> None:
        self.objects[door_id].properties["locked"] = False

    def mark_escaped(self, agent_id: str) -> None:
        self.bodies[agent_id].escaped = True
