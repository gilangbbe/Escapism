"""Top-level simulation harness.

Wires Environment + LLMAgent(s) + Renderer together and runs the
turn-based loop. Currently scaffolded for one agent but the scheduler
in `TurnTracker` already iterates a list, so adding more agents is a
matter of constructing more `LLMAgent` + `CognitiveLoop` pairs and
sharing the same `WorldState` + `chat_history`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from .environment import (
    ActionValidator,
    Ontology,
    PuzzleEngine,
    TurnTracker,
    WorldState,
)
from .model.cognition import CognitiveLoop, LLMAgent, TurnRecord
from .ui import GroupChatRenderer


@dataclass
class Simulation:
    world: WorldState
    ontology: Ontology
    validator: ActionValidator
    puzzles: PuzzleEngine
    turn_tracker: TurnTracker
    agents: List[LLMAgent]
    renderer: GroupChatRenderer = field(default_factory=GroupChatRenderer)
    max_ticks: int = 30
    delay: float = 0.0
    chat_history: List[Tuple[str, str]] = field(default_factory=list)
    on_frame: Optional[Callable[[str], None]] = None

    def __post_init__(self) -> None:
        for a in self.agents:
            a.seed_world_rules()
            self.turn_tracker.register_agent(a.agent_id)
        self._loops = {
            a.agent_id: CognitiveLoop(
                agent=a,
                world=self.world,
                ontology=self.ontology,
                validator=self.validator,
                puzzles=self.puzzles,
                chat_history=self.chat_history,
            )
            for a in self.agents
        }

    # ---------- main loop ----------

    def run(self) -> bool:
        self._emit(self.renderer.legend())
        self._emit(self.renderer.world_frame(self.world, tick=0))

        for _ in range(self.max_ticks):
            tick = self.turn_tracker.next_tick()
            for agent_id in self.turn_tracker.schedule():
                record = self._loops[agent_id].step(tick)
                self._record_chat(record)
                self._emit(self.renderer.agent_turn(record))
                self._emit(self.renderer.world_frame(self.world, tick=tick))

                newly = self.puzzles.update(self.world)
                for puzzle in newly:
                    self._emit(self.renderer.system_event(f"Puzzle solved: {puzzle.puzzle_id} — {puzzle.description}"))
                if self.puzzles.all_solved:
                    self._emit(self.renderer.system_event("All puzzles solved. Simulation complete."))
                    return True
            if self.delay:
                time.sleep(self.delay)

        self._emit(self.renderer.system_event(f"Max ticks ({self.max_ticks}) reached without escape."))
        return False

    # ---------- helpers ----------

    def _record_chat(self, record: TurnRecord) -> None:
        if record.say:
            self.chat_history.append((record.persona_name, record.say))

    def _emit(self, frame: str) -> None:
        if self.on_frame:
            self.on_frame(frame)
        else:
            print(frame + "\n")
