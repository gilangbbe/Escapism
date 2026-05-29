"""Affordance enumeration: the legal-action menu for the Player agent.

Every tick the simulator builds a bounded menu of `(verb, target, on)`
tuples that are valid given the current world state plus the corpus
operators. The Player must pick one of these; off-menu actions are
rejected and resampled. This is the structural fix for the
target-id-hallucination class of bugs.

Three sources contribute to the menu:

1. **Fireable operators** — any corpus doc with `trigger` + `effects`
   whose `preconditions` are satisfied. These are the canonical
   "advance" moves and share the operator model with
   `tools.solver.state_search`. Spent operators (whose effects are
   already realized in the world, or whose `op_id` is in
   `completed_actions`) are hard-filtered.
2. **Inspection** — EXAMINE / SEARCH on every visible item, object,
   or NPC. These never mutate state. Already-tried entries stay
   visible but are annotated `tried Nx, no new info`.
3. **Free verbs** — WAIT and SAY are always available.

The menu is generator-agnostic: it derives everything from the bundle
schema, never hard-coding scenario-specific verbs or targets.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from tools.solver.state_search import Operator


# ---------------------------------------------------------------------------
# data model

@dataclass(frozen=True)
class Affordance:
    """One legal `(verb, target, on)` choice for this turn."""

    verb: str
    target: str
    on: str
    category: str  # "advance" | "inspect" | "communicate" | "wait"
    op_id: str = ""
    title: str = ""
    why: str = ""
    repeat_count: int = 0
    last_was_no_op: bool = False

    def key(self) -> tuple[str, str, str]:
        return (self.verb.upper(), self.target, self.on)

    def action_label(self) -> str:
        if self.on:
            return f"{self.verb} {self.target} \u2192 {self.on}"
        if self.target:
            return f"{self.verb} {self.target}"
        return self.verb


# ---------------------------------------------------------------------------
# operator extraction (shared shape with the solver)

def extract_operators(docs: Iterable[dict[str, Any]]) -> list[Operator]:
    """Return all corpus docs that act as STRIPS-like operators."""
    ops: list[Operator] = []
    for doc in docs:
        trig = doc.get("trigger") or {}
        eff = doc.get("effects") or {}
        if not trig or not eff:
            continue
        ops.append(Operator(
            id=str(doc.get("id", "")),
            kind=str(doc.get("kind", "")),
            verb=str(trig.get("verb", "")).upper(),
            target=str(trig.get("target", "")),
            on=str(trig.get("on", "")),
            preconditions=doc.get("preconditions") or {},
            effects=eff,
        ))
    return ops


# ---------------------------------------------------------------------------
# precondition / effect predicates (kept local; mirror solver semantics on a
# dict-shaped world rather than a frozen _State).

def _preconditions_met(op: Operator, world: dict[str, Any]) -> bool:
    pre = op.preconditions or {}
    inv = set(world.get("inventory") or [])
    obj = world.get("object_state") or {}
    npc = world.get("npc_state") or {}
    disc = set(world.get("discovered_items") or [])
    objs = world.get("objectives") or {}

    for item in pre.get("inventory_has") or []:
        if item not in inv:
            return False
    for name, required in (pre.get("object_state") or {}).items():
        if obj.get(name) != required:
            return False
    for name, required in (pre.get("npc_state") or {}).items():
        if npc.get(name) != required:
            return False
    for item in pre.get("discovered") or []:
        if item not in disc:
            return False
    for oid, status in (pre.get("objectives") or {}).items():
        if objs.get(oid) != status:
            return False
    if pre.get("current_location") and pre["current_location"] != world.get("current_location"):
        return False
    return True


def _effects_already_realized(op: Operator, world: dict[str, Any]) -> bool:
    """True if every checkable effect of `op` is already true of `world`.

    Used to hard-filter spent operators (so puzzles/recipes cannot fire
    twice). Effects without an obvious idempotency key (e.g. a discovery
    that only adds to `discovered_items`) fall through to the
    `completed_actions` check upstream.
    """
    eff = op.effects or {}
    inv = set(world.get("inventory") or [])
    obj = world.get("object_state") or {}
    npc = world.get("npc_state") or {}
    objs = world.get("objectives") or {}

    checkable = False

    for item in eff.get("inventory_add") or []:
        checkable = True
        # `inventory_add` is realized iff the item is currently in inventory.
        # We deliberately do NOT consult `discovered_items`: an item can be
        # visible (e.g. hal_keyring sitting on Hal's belt) long before the
        # operator that places it in inventory ever fires.
        if item not in inv:
            return False
    for name, state in (eff.get("object_state") or {}).items():
        checkable = True
        if obj.get(name) != state:
            return False
    for name, state in (eff.get("npc_state") or {}).items():
        checkable = True
        if npc.get(name) != state:
            return False
    for oid, status in (eff.get("objectives") or {}).items():
        checkable = True
        if objs.get(oid) != status:
            return False
    if eff.get("current_location"):
        checkable = True
        if world.get("current_location") != eff["current_location"]:
            return False
    return checkable


# ---------------------------------------------------------------------------
# history scan

def _attempts_from_history(
    history: list[dict[str, Any]], *, lookback: int = 12,
) -> dict[tuple[str, str, str], int]:
    counts: dict[tuple[str, str, str], int] = {}
    recent = [ev for ev in history if ev.get("kind") == "player_action"][-lookback:]
    for ev in recent:
        a = (ev.get("payload") or {}).get("action") or {}
        verb = str(a.get("verb") or "").upper()
        target = str(a.get("target") or "")
        on = ""
        args = a.get("args")
        if isinstance(args, dict):
            on = str(args.get("on") or args.get("b") or args.get("location") or "")
        key = (verb, target, on)
        counts[key] = counts.get(key, 0) + 1
    return counts


def completed_keys_from_world(
    world: dict[str, Any],
) -> tuple[set[tuple[str, str, str]], set[str]]:
    """Pull (verb, target, on) keys and op_ids from the completed_actions ledger."""
    keys: set[tuple[str, str, str]] = set()
    op_ids: set[str] = set()
    for entry in world.get("completed_actions") or []:
        keys.add((
            str(entry.get("verb", "")).upper(),
            str(entry.get("target", "")),
            str(entry.get("on", "")),
        ))
        op_id = entry.get("op_id")
        if op_id:
            op_ids.add(str(op_id))
    return keys, op_ids


# ---------------------------------------------------------------------------
# the menu

def enumerate_menu(
    world: dict[str, Any],
    operators: Sequence[Operator],
    history: list[dict[str, Any]],
) -> list[Affordance]:
    """Build this turn's legal-action menu.

    Ordering: fireable operators (advance) first, then inspection
    (EXAMINE / SEARCH), then WAIT, then SAY. Within each category,
    untried entries precede already-tried entries.
    """
    completed_keys, completed_op_ids = completed_keys_from_world(world)
    attempts = _attempts_from_history(history)

    affs: list[Affordance] = []
    op_keys_emitted: set[tuple[str, str, str]] = set()

    # ---- 1. fireable operators ----
    for op in operators:
        if op.id and op.id in completed_op_ids:
            continue
        if _effects_already_realized(op, world):
            continue
        if not _preconditions_met(op, world):
            continue
        key = (op.verb, op.target, op.on)
        n = attempts.get(key, 0)
        no_op = n > 0 and key not in completed_keys
        affs.append(Affordance(
            verb=op.verb, target=op.target, on=op.on,
            category="advance",
            op_id=op.id,
            title=op.id,
            why=f"corpus operator `{op.id}` — preconditions met",
            repeat_count=n,
            last_was_no_op=no_op,
        ))
        op_keys_emitted.add(key)

    # ---- 2. inspection (EXAMINE) ----
    visible: list[str] = []
    seen: set[str] = set()
    # Allow examining the current location itself ("look around").
    cur_loc = world.get("current_location")
    if cur_loc:
        seen.add(cur_loc)
        visible.append(cur_loc)
    for src in (
        world.get("inventory") or [],
        world.get("discovered_items") or [],
        list((world.get("object_state") or {}).keys()),
        list((world.get("npc_state") or {}).keys()),
    ):
        for x in src:
            if x and x not in seen:
                seen.add(x)
                visible.append(x)

    for tgt in visible:
        key = ("EXAMINE", tgt, "")
        if key in op_keys_emitted:
            continue
        n = attempts.get(key, 0)
        affs.append(Affordance(
            verb="EXAMINE", target=tgt, on="",
            category="inspect",
            why="visible in current scene",
            repeat_count=n,
            last_was_no_op=n > 0,  # EXAMINE never populates the ledger
        ))

    # ---- 3. SEARCH on objects/NPCs (skip if duplicated by an op) ----
    searchables: list[str] = []
    s_seen: set[str] = set()
    for src in (
        list((world.get("object_state") or {}).keys()),
        list((world.get("npc_state") or {}).keys()),
    ):
        for x in src:
            if x and x not in s_seen:
                s_seen.add(x)
                searchables.append(x)
    for tgt in searchables:
        key = ("SEARCH", tgt, "")
        if key in op_keys_emitted:
            continue
        n = attempts.get(key, 0)
        affs.append(Affordance(
            verb="SEARCH", target=tgt, on="",
            category="inspect",
            why="object/npc in scene",
            repeat_count=n,
            last_was_no_op=n > 0,
        ))

    # ---- 4. WAIT (skip if a WAIT operator already covers it) ----
    if not any(a.verb == "WAIT" for a in affs):
        n = attempts.get(("WAIT", "", ""), 0)
        affs.append(Affordance(
            verb="WAIT", target="", on="",
            category="wait",
            why="let time pass",
            repeat_count=n,
        ))

    # ---- 5. SAY (always available; free utterance) ----
    affs.append(Affordance(
        verb="SAY", target="", on="",
        category="communicate",
        why="speak aloud — does not change state",
    ))

    return affs


# ---------------------------------------------------------------------------
# validation + rendering

def validate_action(
    *,
    verb: str,
    target: str,
    args: dict[str, Any] | None,
    menu: Sequence[Affordance],
) -> Affordance | None:
    """Return the matching menu entry, or None if the action is off-menu.

    Matching is case-insensitive on `verb` and exact on `target`/`on`. Two
    tolerances:

    * **COMBINE is symmetric.** A menu entry `COMBINE A \u2192 B` accepts any
      of `(target=A, args.on=B)`, `(target=B, args.on=A)`,
      `(target="", args={a:A, b:B})`, or `(target="", args={a:B, b:A})`.
    * **SAY is free.** Any target/args matches a SAY menu entry.
    """
    verb_u = (verb or "").upper()
    target = (target or "").strip()
    on = ""
    a_arg = ""
    b_arg = ""
    if isinstance(args, dict):
        on = str(args.get("on") or args.get("location") or "").strip()
        a_arg = str(args.get("a") or "").strip()
        b_arg = str(args.get("b") or "").strip()
        if not on and b_arg:
            on = b_arg

    key = (verb_u, target, on)

    for aff in menu:
        if aff.key() == key:
            return aff

    if verb_u == "COMBINE":
        pair = {target, on, a_arg, b_arg} - {""}
        for aff in menu:
            if aff.verb != "COMBINE":
                continue
            if {aff.target, aff.on} == pair:
                return aff

    if verb_u == "SAY":
        for aff in menu:
            if aff.verb == "SAY":
                return aff
    return None


def render_menu(menu: Sequence[Affordance], *, max_per_category: int = 14) -> str:
    """Render a numbered, human-readable menu for embedding in a prompt."""
    headers = [
        ("advance", "Advance the plot (these change the world)"),
        ("inspect", "Investigate / gather info (no state change)"),
        ("communicate", "Speak"),
        ("wait", "Wait"),
    ]
    by_cat: dict[str, list[Affordance]] = {}
    for a in menu:
        by_cat.setdefault(a.category, []).append(a)

    lines: list[str] = []
    n = 0
    for cat_key, label in headers:
        items = by_cat.get(cat_key) or []
        if not items:
            continue
        lines.append(f"### {label}")
        for a in items[:max_per_category]:
            n += 1
            if a.last_was_no_op and a.repeat_count > 0:
                tag = f"  \u26a0 tried {a.repeat_count}x, no new info"
            elif a.repeat_count > 0:
                tag = f"  (tried {a.repeat_count}x)"
            else:
                tag = ""
            why = f" — {a.why}" if a.why else ""
            lines.append(f"{n}. `{a.action_label()}`{why}{tag}")
    return "\n".join(lines)


def synthesize_fallback_action(
    menu: Sequence[Affordance],
) -> dict[str, Any]:
    """Pick the highest-priority menu entry and return an action payload.

    Used when the player resamples twice and still emits an off-menu action.
    Prefers an `advance` entry; falls back to inspection, then WAIT, then SAY.
    """
    for cat in ("advance", "inspect", "wait", "communicate"):
        for a in menu:
            if a.category == cat:
                return {
                    "verb": a.verb,
                    "target": a.target,
                    "args": {"on": a.on} if a.on else {},
                    "_synthesized_from_menu": True,
                    "_menu_op_id": a.op_id,
                }
    return {"verb": "WAIT", "target": "", "args": {}, "_synthesized_from_menu": True}
