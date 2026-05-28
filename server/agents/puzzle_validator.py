"""Puzzle precondition / effect validator.

Reads puzzle docs from :class:`ClueStore` and validates a player action +
GM delta against the declared ``preconditions`` / ``effects`` of any
matching ``puzzle`` document.

Two responsibilities:

1. :func:`find_triggered_puzzle` \u2014 given a player action, find the puzzle
   whose ``trigger`` matches. Used to surface preconditions in the GM
   prompt as an unmissable instruction.

2. :func:`check_preconditions` \u2014 given a triggered puzzle and the current
   world, return a list of unmet-precondition strings. Used by the
   simulation to reject GM responses that grant the puzzle's declared
   effects when preconditions are unmet (e.g. the GM hands out a keyring
   when Hal is still awake).
"""
from __future__ import annotations

from typing import Any

from ..memory import ClueStore


def _on_from_args(args: dict[str, Any] | None) -> str:
    if not isinstance(args, dict):
        return ""
    return str(args.get("on") or args.get("b") or args.get("location") or "").strip()


def find_triggered_puzzle(
    clues: ClueStore,
    *,
    verb: str,
    target: str,
    args: dict[str, Any] | None,
    scope: str | None = None,
) -> dict[str, Any] | None:
    """Return the puzzle doc whose ``trigger`` matches this action, else None."""
    on = _on_from_args(args)
    verb_u = (verb or "").upper()
    for doc in clues.docs:
        if doc.get("kind") != "puzzle":
            continue
        if scope and scope not in (doc.get("scope") or []):
            continue
        trig = doc.get("trigger") or {}
        if not trig:
            continue
        if str(trig.get("verb", "")).upper() != verb_u:
            continue
        if str(trig.get("target", "")) != (target or ""):
            continue
        if str(trig.get("on", "")) != on:
            continue
        return doc
    return None


def check_preconditions(puzzle: dict[str, Any], world: dict[str, Any]) -> list[str]:
    """Return human-readable list of unmet preconditions. Empty = all met."""
    pre = puzzle.get("preconditions") or {}
    unmet: list[str] = []

    for item in pre.get("inventory_has") or []:
        if item not in (world.get("inventory") or []):
            unmet.append(f"missing inventory item `{item}`")

    for name, required in (pre.get("object_state") or {}).items():
        actual = (world.get("object_state") or {}).get(name)
        if actual != required:
            unmet.append(f"object `{name}` must be `{required}` (currently `{actual}`)")

    for name, required in (pre.get("npc_state") or {}).items():
        actual = (world.get("npc_state") or {}).get(name)
        if actual != required:
            unmet.append(f"npc `{name}` must be `{required}` (currently `{actual}`)")

    for item in pre.get("discovered") or []:
        if item not in (world.get("discovered_items") or []):
            unmet.append(f"item `{item}` must be discovered first")

    return unmet


def delta_grants_effect(delta: dict[str, Any], puzzle: dict[str, Any]) -> bool:
    """True if the delta would grant ANY of the puzzle's declared effects.

    Used to detect when the GM is trying to award a puzzle outcome even
    though preconditions are unmet.
    """
    eff = puzzle.get("effects") or {}
    if not isinstance(delta, dict):
        return False
    for item in eff.get("inventory_add") or []:
        if item in (delta.get("inventory_add") or []):
            return True
    for name, state in (eff.get("object_state") or {}).items():
        if (delta.get("object_state") or {}).get(name) == state:
            return True
    for name, state in (eff.get("npc_state") or {}).items():
        if (delta.get("npc_state") or {}).get(name) == state:
            return True
    for oid, status in (eff.get("objectives") or {}).items():
        if (delta.get("objectives") or {}).get(oid) == status:
            return True
    if eff.get("current_location") and delta.get("current_location") == eff["current_location"]:
        return True
    return False


def format_precondition_brief(puzzle: dict[str, Any]) -> str:
    """One-paragraph human-readable summary for inclusion in the GM prompt."""
    pre = puzzle.get("preconditions") or {}
    eff = puzzle.get("effects") or {}
    bits: list[str] = []
    if pre.get("inventory_has"):
        bits.append("requires inventory: " + ", ".join(pre["inventory_has"]))
    if pre.get("object_state"):
        bits.append("requires object state: " + ", ".join(
            f"{k}={v}" for k, v in pre["object_state"].items()
        ))
    if pre.get("npc_state"):
        bits.append("requires npc state: " + ", ".join(
            f"{k}={v}" for k, v in pre["npc_state"].items()
        ))
    if pre.get("discovered"):
        bits.append("requires discovered: " + ", ".join(pre["discovered"]))
    pre_line = "; ".join(bits) if bits else "no preconditions"
    eff_bits: list[str] = []
    if eff.get("inventory_add"):
        eff_bits.append("grants inventory " + ", ".join(eff["inventory_add"]))
    if eff.get("object_state"):
        eff_bits.append("sets object " + ", ".join(f"{k}={v}" for k, v in eff["object_state"].items()))
    if eff.get("npc_state"):
        eff_bits.append("sets npc " + ", ".join(f"{k}={v}" for k, v in eff["npc_state"].items()))
    if eff.get("objectives"):
        eff_bits.append("objectives " + ", ".join(f"{k}={v}" for k, v in eff["objectives"].items()))
    if eff.get("current_location"):
        eff_bits.append(f"moves to {eff['current_location']}")
    eff_line = "; ".join(eff_bits) if eff_bits else "no declared effects"
    return f"{pre_line} \u2192 on success {eff_line}"
