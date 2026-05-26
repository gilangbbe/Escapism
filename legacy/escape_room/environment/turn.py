"""Turn / time tracking.

Owns the canonical tick counter and an event log. Multi-agent scheduling
can later plug in here (round-robin, priority queue, simultaneous).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, List, Tuple


@dataclass
class TurnTracker:
    tick: int = 0
    agent_order: List[str] = field(default_factory=list)
    event_log: List[Tuple[int, str, str]] = field(default_factory=list)  # (tick, source, text)

    def register_agent(self, agent_id: str) -> None:
        if agent_id not in self.agent_order:
            self.agent_order.append(agent_id)

    def next_tick(self) -> int:
        self.tick += 1
        return self.tick

    def schedule(self) -> Iterator[str]:
        """Yield agent ids for the current tick (round-robin, one each)."""
        yield from list(self.agent_order)

    def log(self, source: str, text: str) -> None:
        self.event_log.append((self.tick, source, text))
