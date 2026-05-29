"""Tests for the Layer-1 BFS solver."""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.solver.state_search import (
    Operator,
    Plan,
    Unsolvable,
    load_bundle,
    solve,
)

ROOT = Path(__file__).resolve().parent.parent
BLACK_VESPER = ROOT / "scenarios" / "black_vesper"


# --------------------------------------------------------------- unit: tiny puzzles

def _op(op_id: str, *, verb="USE", target="", on="", pre=None, eff=None) -> Operator:
    return Operator(
        id=op_id, kind="puzzle", verb=verb, target=target, on=on,
        preconditions=pre or {}, effects=eff or {},
    )


def test_solver_returns_zero_plan_when_initial_state_already_satisfies_goal():
    world = {"current_location": "exit"}
    result = solve(world, [_op("noop", eff={"object_state": {"x": "y"}})], {"current_location": "exit"})
    assert isinstance(result, Plan)
    assert result.length == 0
    assert result.operators == []


def test_solver_finds_single_step_plan():
    world = {"current_location": "start", "inventory": ["key"]}
    op = _op("unlock", verb="USE", target="key", on="door",
             pre={"inventory_has": ["key"]},
             eff={"object_state": {"door": "open"}})
    result = solve(world, [op], {"object_state": {"door": "open"}})
    assert isinstance(result, Plan)
    assert result.length == 1
    assert result.operators[0].id == "unlock"


def test_solver_chains_dependent_operators():
    world = {"inventory": ["a"]}
    forge = _op("forge", verb="USE", target="a",
                pre={"inventory_has": ["a"]},
                eff={"inventory_add": ["b"]})
    finish = _op("finish", verb="USE", target="b",
                 pre={"inventory_has": ["b"]},
                 eff={"objectives": {"done": "complete"}})
    result = solve(world, [forge, finish], {"objectives": {"done": "complete"}})
    assert isinstance(result, Plan)
    assert [op.id for op in result.operators] == ["forge", "finish"]


def test_solver_reports_unsolvable_when_preconditions_unreachable():
    world = {"inventory": []}
    op = _op("locked", pre={"inventory_has": ["magic"]},
             eff={"objectives": {"done": "complete"}})
    result = solve(world, [op], {"objectives": {"done": "complete"}})
    assert isinstance(result, Unsolvable)
    assert "objectives" in result.unmet_goal


def test_solver_reports_unsolvable_when_no_operators_declared():
    result = solve({"current_location": "a"}, [], {"current_location": "b"})
    assert isinstance(result, Unsolvable)
    assert "no operators" in result.reason


def test_solver_reports_unsolvable_when_no_goal_declared():
    result = solve({}, [_op("x")], {})
    assert isinstance(result, Unsolvable)
    assert "no goal" in result.reason


def test_solver_respects_max_states_cap():
    # 100 distinct-flag operators, none of which advance toward the goal.
    ops = [
        _op(f"flip_{i}", eff={"object_state": {f"f{i}": "on"}})
        for i in range(8)
    ]
    result = solve({}, ops, {"object_state": {"impossible": "yes"}}, max_states=50)
    assert isinstance(result, Unsolvable)


# --------------------------------------------------------------- integration: Black Vesper

def test_black_vesper_loads_with_operators():
    manifest, world, operators = load_bundle(BLACK_VESPER)
    assert manifest["id"] == "black_vesper"
    # Initial inventory comes through unchanged.
    assert "folding_knife" in world["inventory"]
    # We declare 4 puzzles + 1 (sedate) + 2 (retrieve/cell_lock) + 1 (exit) plus
    # the 7 we added in Phase B (search_crew, work_nail_free, focus_lantern,
    # prep_herbs, brew_draught, rig_rope, wait). 4 + 7 = 11.
    assert len(operators) == 11


def test_black_vesper_solves_at_optimal_length():
    manifest, world, operators = load_bundle(BLACK_VESPER)
    result = solve(world, operators, manifest["goal"])
    assert isinstance(result, Plan), f"unsolvable: {result}"
    assert result.length == manifest["optimal_solution_length"]


def test_black_vesper_plan_ends_with_exit_to_lower_decks():
    manifest, world, operators = load_bundle(BLACK_VESPER)
    result = solve(world, operators, manifest["goal"])
    assert isinstance(result, Plan)
    last = result.operators[-1]
    assert last.id == "puzzle.act1_exit"
    assert last.verb == "MOVE_TO"
    assert last.on == "lower_decks"


def test_black_vesper_solver_proof_matches_solver_output():
    """The committed solver_proof.json should be reproducible from the bundle."""
    import json
    manifest, world, operators = load_bundle(BLACK_VESPER)
    result = solve(world, operators, manifest["goal"])
    assert isinstance(result, Plan)
    proof_path = BLACK_VESPER / manifest.get("solver_proof", "solver_proof.json")
    proof = json.loads(proof_path.read_text())
    assert proof["optimal_solution_length"] == result.length
    assert [s["operator_id"] for s in proof["plan"]] == [op.id for op in result.operators]
