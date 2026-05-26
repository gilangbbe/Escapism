"""Environment layer: world state, ontology, action validation, puzzles, turn tracking."""

from .ontology import ActionSpec, ObjectType, Ontology, TileType, WorldObject
from .puzzles import Puzzle, PuzzleEngine
from .state import Action, AgentBody, WorldState
from .turn import TurnTracker
from .validator import ActionResult, ActionValidator

__all__ = [
    "Action",
    "ActionResult",
    "ActionSpec",
    "ActionValidator",
    "AgentBody",
    "ObjectType",
    "Ontology",
    "Puzzle",
    "PuzzleEngine",
    "TileType",
    "TurnTracker",
    "WorldObject",
    "WorldState",
]
