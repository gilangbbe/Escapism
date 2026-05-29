"""STRIPS-like BFS solver over a scenario bundle.

Treats every game-corpus doc with both ``trigger`` and ``effects`` as a
STRIPS operator with optional ``preconditions``. Search state is the
quintuple

    (current_location, inventory, object_state, npc_state, objectives,
     discovered_items)

Optimality: BFS, so the returned plan is of minimum length in terms of
operator applications. Note that the simulator's actual tick count may
be higher because the Player + GM may execute non-state-changing
information actions (EXAMINE, etc.) the solver elides.
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# --------------------------------------------------------------- types

@dataclass(frozen=True)
class Operator:
    """A STRIPS operator derived from a corpus doc."""

    id: str
    kind: str
    verb: str
    target: str
    on: str
    preconditions: dict[str, Any]
    effects: dict[str, Any]

    def action_label(self) -> str:
        bits = [self.verb or "?"]
        if self.target:
            bits.append(self.target)
        if self.on:
            bits.append(f"\u2192 {self.on}")
        return " ".join(bits)


@dataclass(frozen=True)
class _State:
    current_location: str
    inventory: frozenset[str]
    discovered: frozenset[str]
    object_state: tuple[tuple[str, str], ...]
    npc_state: tuple[tuple[str, str], ...]
    objectives: tuple[tuple[str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "current_location": self.current_location,
            "inventory": sorted(self.inventory),
            "discovered_items": sorted(self.discovered),
            "object_state": dict(self.object_state),
            "npc_state": dict(self.npc_state),
            "objectives": dict(self.objectives),
        }


@dataclass
class Plan:
    length: int
    operators: list[Operator]
    final_state: dict[str, Any]

    def to_proof(self, *, scenario_id: str, goal: dict[str, Any]) -> dict[str, Any]:
        return {
            "scenario_id": scenario_id,
            "solver": "tools.solver.state_search.bfs",
            "schema_version": 1,
            "goal": goal,
            "optimal_solution_length": self.length,
            "plan": [
                {
                    "step": i + 1,
                    "operator_id": op.id,
                    "kind": op.kind,
                    "verb": op.verb,
                    "target": op.target,
                    "on": op.on,
                }
                for i, op in enumerate(self.operators)
            ],
            "final_state": self.final_state,
        }


@dataclass
class Unsolvable:
    reason: str
    unmet_goal: dict[str, Any] = field(default_factory=dict)
    states_explored: int = 0

    def __bool__(self) -> bool:  # convenience: bool(result) is True iff solved
        return False


SolverResult = Plan | Unsolvable


# --------------------------------------------------------------- bundle loading

def load_bundle(bundle: Path) -> tuple[dict[str, Any], dict[str, Any], list[Operator]]:
    """Return (manifest, world_initial, operators) for the bundle."""
    manifest = json.loads((bundle / "manifest.json").read_text())
    world_path = bundle / manifest.get("world_initial", "world_initial.json")
    world = json.loads(world_path.read_text())
    corpus_path = bundle / manifest.get("game_corpus", "game.jsonl")

    operators: list[Operator] = []
    for line in corpus_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        doc = json.loads(line)
        trig = doc.get("trigger") or {}
        eff = doc.get("effects") or {}
        if not trig or not eff:
            continue
        operators.append(Operator(
            id=doc["id"],
            kind=doc.get("kind", "puzzle"),
            verb=str(trig.get("verb", "")).upper(),
            target=str(trig.get("target", "")),
            on=str(trig.get("on", "")),
            preconditions=doc.get("preconditions") or {},
            effects=eff,
        ))
    return manifest, world, operators


# --------------------------------------------------------------- state ops

def _initial_state(world: dict[str, Any]) -> _State:
    return _State(
        current_location=world.get("current_location", ""),
        inventory=frozenset(world.get("inventory") or []),
        discovered=frozenset(world.get("discovered_items") or []),
        object_state=tuple(sorted((world.get("object_state") or {}).items())),
        npc_state=tuple(sorted((world.get("npc_state") or {}).items())),
        objectives=tuple(sorted((world.get("objectives") or {}).items())),
    )


def _preconditions_met(op: Operator, state: _State) -> bool:
    pre = op.preconditions
    for item in pre.get("inventory_has") or []:
        if item not in state.inventory:
            return False
    object_state = dict(state.object_state)
    for k, v in (pre.get("object_state") or {}).items():
        if object_state.get(k) != v:
            return False
    npc_state = dict(state.npc_state)
    for k, v in (pre.get("npc_state") or {}).items():
        if npc_state.get(k) != v:
            return False
    for item in pre.get("discovered") or []:
        if item not in state.discovered:
            return False
    return True


def _apply(op: Operator, state: _State) -> _State:
    eff = op.effects
    inv = set(state.inventory)
    for item in eff.get("inventory_add") or []:
        inv.add(item)
    for item in eff.get("inventory_remove") or []:
        inv.discard(item)

    disc = set(state.discovered)
    for item in eff.get("discovered_items") or []:
        disc.add(item)
    # Newly added inventory is implicitly discovered too.
    for item in eff.get("inventory_add") or []:
        disc.add(item)

    objs = dict(state.object_state)
    for k, v in (eff.get("object_state") or {}).items():
        objs[k] = v

    npcs = dict(state.npc_state)
    for k, v in (eff.get("npc_state") or {}).items():
        npcs[k] = v

    goals = dict(state.objectives)
    for k, v in (eff.get("objectives") or {}).items():
        goals[k] = v

    loc = eff.get("current_location") or state.current_location

    return _State(
        current_location=loc,
        inventory=frozenset(inv),
        discovered=frozenset(disc),
        object_state=tuple(sorted(objs.items())),
        npc_state=tuple(sorted(npcs.items())),
        objectives=tuple(sorted(goals.items())),
    )


def _is_goal(state: _State, goal: dict[str, Any]) -> bool:
    if not goal:
        return False
    if "current_location" in goal and state.current_location != goal["current_location"]:
        return False
    inv = state.inventory
    for item in goal.get("inventory_has") or []:
        if item not in inv:
            return False
    object_state = dict(state.object_state)
    for k, v in (goal.get("object_state") or {}).items():
        if object_state.get(k) != v:
            return False
    npc_state = dict(state.npc_state)
    for k, v in (goal.get("npc_state") or {}).items():
        if npc_state.get(k) != v:
            return False
    objs = dict(state.objectives)
    for k, v in (goal.get("objectives") or {}).items():
        if objs.get(k) != v:
            return False
    return True


def _unmet_goal(state: _State, goal: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "current_location" in goal and state.current_location != goal["current_location"]:
        out["current_location"] = {"want": goal["current_location"], "got": state.current_location}
    object_state = dict(state.object_state)
    bad = {k: {"want": v, "got": object_state.get(k)} for k, v in (goal.get("object_state") or {}).items() if object_state.get(k) != v}
    if bad:
        out["object_state"] = bad
    npc_state = dict(state.npc_state)
    bad = {k: {"want": v, "got": npc_state.get(k)} for k, v in (goal.get("npc_state") or {}).items() if npc_state.get(k) != v}
    if bad:
        out["npc_state"] = bad
    objs = dict(state.objectives)
    bad = {k: {"want": v, "got": objs.get(k)} for k, v in (goal.get("objectives") or {}).items() if objs.get(k) != v}
    if bad:
        out["objectives"] = bad
    missing_inv = [i for i in (goal.get("inventory_has") or []) if i not in state.inventory]
    if missing_inv:
        out["inventory_missing"] = missing_inv
    return out


# --------------------------------------------------------------- search

def solve(
    world: dict[str, Any],
    operators: list[Operator],
    goal: dict[str, Any],
    *,
    max_states: int = 200_000,
) -> SolverResult:
    """BFS for the shortest plan from ``world`` to ``goal``."""
    if not goal:
        return Unsolvable(reason="manifest declares no goal predicate")
    if not operators:
        return Unsolvable(reason="bundle declares no operators (puzzle / recipe / discovery)")

    start = _initial_state(world)
    if _is_goal(start, goal):
        return Plan(length=0, operators=[], final_state=start.as_dict())

    visited: set[_State] = {start}
    # Parent pointers for plan reconstruction.
    parent: dict[_State, tuple[_State, Operator]] = {}
    queue: deque[_State] = deque([start])

    best_state = start
    best_unmet_count = len(_unmet_goal(start, goal))

    while queue and len(visited) < max_states:
        state = queue.popleft()
        for op in operators:
            if not _preconditions_met(op, state):
                continue
            nxt = _apply(op, state)
            if nxt in visited:
                continue
            visited.add(nxt)
            parent[nxt] = (state, op)
            if _is_goal(nxt, goal):
                return _reconstruct(nxt, parent)
            unmet_count = len(_unmet_goal(nxt, goal))
            if unmet_count < best_unmet_count:
                best_unmet_count = unmet_count
                best_state = nxt
            queue.append(nxt)

    reason = (
        f"exhausted {len(visited)} states without reaching goal"
        if len(visited) < max_states else
        f"hit max_states cap ({max_states}); search aborted"
    )
    return Unsolvable(
        reason=reason,
        unmet_goal=_unmet_goal(best_state, goal),
        states_explored=len(visited),
    )


def _reconstruct(
    end: _State, parent: dict[_State, tuple[_State, Operator]]
) -> Plan:
    ops: list[Operator] = []
    cur = end
    while cur in parent:
        prev, op = parent[cur]
        ops.append(op)
        cur = prev
    ops.reverse()
    return Plan(length=len(ops), operators=ops, final_state=end.as_dict())
