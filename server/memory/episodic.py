"""Per-run episodic memory for the Player agent.

Distinct from :class:`ClueStore` (which is *semantic* — static lore loaded
from ``game.jsonl``). The episodic store accumulates lived experience from
the current voyage: GM narrations, state changes, hints, and reflections.

It deliberately stays in-memory and lightweight (no Chroma) — episodic
recall is small (one run) and benefits from cheap recency boosting more
than from embedding quality.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class Episode:
    tick: int
    kind: str           # "narration" | "delta" | "hint" | "reflection"
    text: str
    score_hint: float = 1.0   # relative weight (reflections > narration > delta)


@dataclass
class EpisodicMemory:
    """Tiny keyword + recency retriever scoped to a single run."""

    episodes: list[Episode] = field(default_factory=list)
    max_episodes: int = 200

    def add(self, tick: int, kind: str, text: str, score_hint: float = 1.0) -> None:
        text = (text or "").strip()
        if not text:
            return
        self.episodes.append(Episode(tick=tick, kind=kind, text=text, score_hint=score_hint))
        # Bound memory: keep the most recent N (reflections protected first).
        if len(self.episodes) > self.max_episodes:
            # Drop oldest non-reflection first.
            for i, e in enumerate(self.episodes):
                if e.kind != "reflection":
                    del self.episodes[i]
                    break
            else:
                del self.episodes[0]

    def compact(self, before_tick: int, replacement: Episode) -> int:
        """Drop all non-reflection episodes with tick < before_tick, then add a
        replacement summary episode. Returns the number of episodes dropped.
        """
        before = len(self.episodes)
        self.episodes = [
            e for e in self.episodes
            if e.kind == "reflection" or e.tick >= before_tick
        ]
        self.episodes.append(replacement)
        return before - len(self.episodes) + 1  # +1 for replacement added

    def query(self, prompt: str, *, k: int = 5, current_tick: int = 0) -> list[Episode]:
        """Score by keyword overlap + a mild recency bonus + kind weight."""
        tokens = _tokens(prompt)
        if not self.episodes:
            return []
        if not tokens:
            # No query terms: return most recent k.
            return list(self.episodes[-k:])
        scored: list[tuple[float, Episode]] = []
        for ep in self.episodes:
            ep_tokens = _tokens(ep.text)
            overlap = len(tokens & ep_tokens)
            if overlap == 0 and ep.kind != "reflection":
                continue
            # Recency in [0, 1]: events nearer the current tick rank higher.
            age = max(0, current_tick - ep.tick)
            recency = 1.0 / (1.0 + age * 0.15)
            score = overlap * ep.score_hint + recency * 0.5
            scored.append((score, ep))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [ep for _, ep in scored[:k]]

    def recent(self, k: int = 5) -> list[Episode]:
        return list(self.episodes[-k:])


def _tokens(text: str) -> set[str]:
    return {t.strip(".,'\"!?;:()[]").lower() for t in (text or "").split() if len(t) > 3}
