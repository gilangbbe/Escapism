"""Tests for the Salty tiered hint provider."""
from __future__ import annotations

from dataclasses import dataclass, field

from server.agents.salty import Salty, SALTY_PREFIX


@dataclass
class _FakeClueStore:
    docs: list[dict] = field(default_factory=list)

    def query(self, prompt: str, *, k: int = 6, scope: str | None = None):
        # Match the real ClueStore signature; just return docs matching scope.
        out = [d for d in self.docs if not scope or scope in (d.get("scope") or [])]
        return out[:k]


def _world():
    return {
        "act": 1,
        "current_location": "brig",
        "objectives": {"escape_brig": "active", "wake_crew": "active"},
    }


def test_tier1_is_vague_and_names_objective():
    s = Salty(clues=_FakeClueStore())
    txt = s.hint_for(tier=1, world=_world(), action_key=("EXAMINE", "hal_keyring"))
    assert SALTY_PREFIX in txt
    assert "EXAMINE" in txt and "hal_keyring" in txt
    assert "escape_brig" in txt  # first active objective


def test_tier2_prefers_hint_kind_tier_le_2():
    docs = [
        {"id": "hint.compass", "title": "compass", "text": "use brass back as a lens",
         "kind": "hint", "tier": 1, "scope": ["act1"]},
        {"id": "hint.rope_hook", "title": "rope hook", "text": "lash rope through the ceiling hook",
         "kind": "hint", "tier": 2, "scope": ["act1"]},
        {"id": "hint.advanced", "title": "advanced", "text": "exact solution",
         "kind": "hint", "tier": 3, "scope": ["act1"]},
        {"id": "puzzle.x", "title": "puzzle", "text": "puzzle text",
         "kind": "puzzle", "scope": ["act1"]},
    ]
    s = Salty(clues=_FakeClueStore(docs=docs))
    txt = s.hint_for(tier=2, world=_world(), action_key=("EXAMINE", "hal_keyring"))
    assert SALTY_PREFIX in txt
    # Picks first tier<=2 hint doc.
    assert "compass" in txt or "rope hook" in txt
    assert "advanced" not in txt
    assert "puzzle text" not in txt


def test_tier3_prefers_high_tier_or_puzzle():
    docs = [
        {"id": "hint.low", "title": "low", "text": "vague nudge", "kind": "hint",
         "tier": 1, "scope": ["act1"]},
        {"id": "hint.advanced", "title": "advanced", "text": "very explicit hint",
         "kind": "hint", "tier": 3, "scope": ["act1"]},
        {"id": "puzzle.x", "title": "rope puzzle", "text": "exact puzzle text",
         "kind": "puzzle", "scope": ["act1"]},
    ]
    s = Salty(clues=_FakeClueStore(docs=docs))
    txt = s.hint_for(tier=3, world=_world(), action_key=("EXAMINE", "hal_keyring"))
    # Should pick the tier-3 hint or the puzzle doc, not the tier-1 vague one.
    assert "low" not in txt
    assert ("advanced" in txt) or ("rope puzzle" in txt)


def test_no_docs_returns_safe_fallback():
    s = Salty(clues=_FakeClueStore(docs=[]))
    txt = s.hint_for(tier=2, world=_world(), action_key=("EXAMINE", "hal_keyring"))
    assert SALTY_PREFIX in txt
    assert "hal_keyring" in txt
