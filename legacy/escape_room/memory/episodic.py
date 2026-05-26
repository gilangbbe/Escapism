"""Episodic memory: an append-only timeline of what happened.

Each entry is tagged with the turn it occurred on plus simple
keyword tags so we can do recency- or keyword-weighted recall without
needing an embedding store for the PoC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence


@dataclass
class EpisodicEvent:
    tick: int
    kind: str            # "perceive" | "action" | "observation" | "chat"
    content: str
    tags: List[str] = field(default_factory=list)


@dataclass
class EpisodicMemory:
    events: List[EpisodicEvent] = field(default_factory=list)

    def record(self, tick: int, kind: str, content: str, tags: Sequence[str] = ()) -> None:
        self.events.append(EpisodicEvent(tick=tick, kind=kind, content=content, tags=list(tags)))

    def recall_recent(self, k: int = 8) -> List[EpisodicEvent]:
        return self.events[-k:]

    def recall_by_tag(self, tag: str, k: int = 5) -> List[EpisodicEvent]:
        hits = [e for e in self.events if tag in e.tags]
        return hits[-k:]

    def recall_keyword(self, keyword: str, k: int = 5) -> List[EpisodicEvent]:
        kw = keyword.lower()
        hits = [e for e in self.events if kw in e.content.lower()]
        return hits[-k:]
