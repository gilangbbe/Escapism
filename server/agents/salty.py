"""Tiered hint provider — \"Salty the parrot\".

Watches the player's recent actions for stalls. When the same (verb, target)
repeats, escalates a hint through three tiers:

    Tier 1: vague nudge (just naming the active objective).
    Tier 2: pulls a `kind=hint, tier<=2` doc from the clue corpus scoped to
            the current act and ranked by overlap with the player's last
            action.
    Tier 3: pulls a `kind=hint, tier=3` or a `kind=puzzle` doc — explicit.

The hint is delivered as a `system_hint` event so the existing prompt
plumbing on the Player side (already added in Phase 3) surfaces it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..memory.clue_store import ClueStore


SALTY_PREFIX = "Salty squawks:"


@dataclass
class Salty:
    clues: ClueStore

    def hint_for(
        self,
        *,
        tier: int,
        world: dict[str, Any],
        action_key: tuple[str, str],
    ) -> str:
        verb, target = action_key
        scope = f"act{world.get('act', 1)}"
        active = [oid for oid, s in (world.get("objectives") or {}).items() if s == "active"]
        if tier <= 1:
            obj = active[0] if active else "find a way forward"
            return (
                f"{SALTY_PREFIX} you've tried {verb} {target} thrice. Forget that one. "
                f"Mind your objective: {obj}. Look at what you carry and what you've learned."
            )
        # Tier 2/3 pull from the corpus.
        query = f"{verb} {target} {world.get('current_location','')} {' '.join(active)}"
        docs = [
            d for d in self.clues.query(query, k=8, scope=scope)
            if d.get("kind") in ("hint", "puzzle")
        ]
        if tier == 2:
            tier_docs = [d for d in docs if int(d.get("tier") or 2) <= 2 and d.get("kind") == "hint"]
            chosen = tier_docs[0] if tier_docs else (docs[0] if docs else None)
        else:  # tier >= 3
            tier_docs = [d for d in docs if int(d.get("tier") or 3) >= 3 or d.get("kind") == "puzzle"]
            chosen = tier_docs[0] if tier_docs else (docs[0] if docs else None)

        if not chosen:
            return f"{SALTY_PREFIX} {verb} {target} won't help. Try a different verb on a different thing."
        title = chosen.get("title") or chosen["id"]
        text = chosen.get("text") or ""
        return f"{SALTY_PREFIX} {title} — {text}"
