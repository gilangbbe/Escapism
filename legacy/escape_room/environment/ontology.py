"""World ontology: tile types, object types, and the action schemas the
world understands.

The ontology is data, not behaviour. It declares *what exists* and
*what verbs are legal*; the validator and state layers apply the rules.
This separation means adding a new puzzle piece (e.g. a pressure plate)
is a matter of registering a new `ObjectType` + an `ActionSpec`, not
patching the agent or the loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class TileType(str, Enum):
    FLOOR = "."
    WALL = "#"


class ObjectType(str, Enum):
    KEY = "key"
    DOOR = "door"


@dataclass
class WorldObject:
    """An instance of an `ObjectType` placed in the world."""

    obj_id: str
    type: ObjectType
    position: Tuple[int, int]
    properties: Dict[str, object] = field(default_factory=dict)

    @property
    def glyph(self) -> str:
        if self.type == ObjectType.KEY:
            return "K"
        if self.type == ObjectType.DOOR:
            return "D" if self.properties.get("locked", True) else "O"
        return "?"


@dataclass(frozen=True)
class ActionSpec:
    """Declarative description of a verb the world supports."""

    name: str                       # e.g. "MOVE", "PICKUP", "USE"
    args: Tuple[str, ...] = ()      # parameter names, e.g. ("direction",) or ("item", "target")
    description: str = ""


@dataclass
class Ontology:
    """Container for tile, object, and action vocabulary."""

    actions: Dict[str, ActionSpec] = field(default_factory=dict)
    object_types: List[ObjectType] = field(default_factory=lambda: list(ObjectType))

    @classmethod
    def default(cls) -> "Ontology":
        specs = [
            ActionSpec("MOVE", ("direction",), "Move one cell: UP, DOWN, LEFT, or RIGHT."),
            ActionSpec("PICKUP", ("object_id",), "Pick up an object on or adjacent to your cell."),
            ActionSpec("USE", ("item", "target"), "Use an item from your inventory on a target object."),
            ActionSpec("EXAMINE", ("object_id",), "Look closely at an object to learn its properties."),
            ActionSpec("SAY", ("text",), "Broadcast a message to the group chat."),
            ActionSpec("WAIT", (), "Do nothing this turn."),
        ]
        return cls(actions={s.name: s for s in specs})

    def describe_for_prompt(self) -> str:
        """Render the action vocabulary as a list for the LLM system prompt."""
        lines = []
        for spec in self.actions.values():
            arg_str = ", ".join(spec.args) if spec.args else "—"
            lines.append(f"- {spec.name}({arg_str}): {spec.description}")
        return "\n".join(lines)
