"""Puzzle engine.

Each `Puzzle` watches the world for a completion condition. The engine
is intentionally minimal for the PoC — one puzzle ("escape via locked
door"), but the structure supports adding more (combination locks,
pressure plates, multi-agent puzzles) without touching the agent loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List

from .state import WorldState


@dataclass
class Puzzle:
    puzzle_id: str
    description: str
    is_solved: Callable[[WorldState], bool]
    hint: str = ""
    solved: bool = False


@dataclass
class PuzzleEngine:
    puzzles: List[Puzzle] = field(default_factory=list)

    def register(self, puzzle: Puzzle) -> None:
        self.puzzles.append(puzzle)

    def update(self, world: WorldState) -> List[Puzzle]:
        """Re-check every puzzle. Returns the list newly solved this tick."""
        newly_solved: List[Puzzle] = []
        for p in self.puzzles:
            if not p.solved and p.is_solved(world):
                p.solved = True
                newly_solved.append(p)
        return newly_solved

    @property
    def all_solved(self) -> bool:
        return all(p.solved for p in self.puzzles)

    def describe_for_prompt(self) -> str:
        if not self.puzzles:
            return "No active puzzles."
        return "\n".join(
            f"- {p.puzzle_id}: {p.description}"
            + (f" Hint: {p.hint}" if p.hint else "")
            + (" [SOLVED]" if p.solved else "")
            for p in self.puzzles
        )


def default_escape_puzzle() -> Puzzle:
    """The one puzzle the PoC ships with: any agent must escape."""

    def solved(world: WorldState) -> bool:
        return any(b.escaped for b in world.bodies.values())

    return Puzzle(
        puzzle_id="escape",
        description="Find a way out of the room.",
        is_solved=solved,
        hint="Locked doors usually need keys.",
    )
