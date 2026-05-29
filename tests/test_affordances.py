"""Tests for the legal-action menu (affordances)."""
from __future__ import annotations

from pathlib import Path

import pytest

from server.world.affordances import (
    Affordance,
    _effects_already_realized,
    _preconditions_met,
    completed_keys_from_world,
    enumerate_menu,
    extract_operators,
    render_menu,
    synthesize_fallback_action,
    validate_action,
)
from tools.solver.state_search import Operator


# ----------------------------------------------------------------- helpers

def _op(
    op_id: str,
    *,
    verb="USE",
    target="",
    on="",
    pre=None,
    eff=None,
    kind="puzzle",
) -> Operator:
    return Operator(
        id=op_id, kind=kind, verb=verb, target=target, on=on,
        preconditions=pre or {}, effects=eff or {},
    )


def _action_event(verb: str, target: str = "", on: str = "", tick: int = 1) -> dict:
    args = {"on": on} if on else {}
    return {
        "tick": tick,
        "kind": "player_action",
        "payload": {"action": {"verb": verb, "target": target, "args": args}},
    }


# ----------------------------------------------------------------- extraction

def test_extract_operators_filters_docs_without_trigger_or_effects():
    docs = [
        {"id": "lore.note", "kind": "lore", "text": "just narrative"},
        {"id": "p1", "kind": "puzzle", "trigger": {"verb": "USE", "target": "x", "on": ""},
         "preconditions": {}, "effects": {"object_state": {"x": "open"}}},
        {"id": "broken", "kind": "puzzle", "trigger": {"verb": "USE"}},  # no effects
    ]
    ops = extract_operators(docs)
    assert [o.id for o in ops] == ["p1"]


# ----------------------------------------------------------------- predicates

def test_preconditions_met_checks_all_categories():
    world = {
        "inventory": ["key"],
        "object_state": {"door": "locked"},
        "npc_state": {"hal": "asleep"},
        "discovered_items": ["key"],
        "current_location": "brig",
    }
    op = _op("u", pre={
        "inventory_has": ["key"],
        "object_state": {"door": "locked"},
        "npc_state": {"hal": "asleep"},
        "discovered": ["key"],
        "current_location": "brig",
    }, eff={"object_state": {"door": "open"}})
    assert _preconditions_met(op, world)
    assert not _preconditions_met(_op("u", pre={"inventory_has": ["missing"]}), world)


def test_effects_already_realized_does_not_count_discovered_items():
    """An item visible (in discovered_items) does NOT mean its acquiring
    operator has fired; the operator must actually have put it in inventory."""
    world = {"inventory": [], "discovered_items": ["hal_keyring"]}
    op = _op("retrieve", eff={"inventory_add": ["hal_keyring"]})
    assert not _effects_already_realized(op, world)
    world["inventory"] = ["hal_keyring"]
    assert _effects_already_realized(op, world)


def test_effects_already_realized_handles_object_npc_loc():
    op = _op("rig", eff={"object_state": {"rope": "rigged"}})
    assert not _effects_already_realized(op, {"object_state": {"rope": "coiled"}})
    assert _effects_already_realized(op, {"object_state": {"rope": "rigged"}})


# ----------------------------------------------------------------- enumerate_menu

def test_menu_includes_fireable_operators_as_advance():
    world = {
        "current_location": "brig",
        "inventory": ["key"],
        "object_state": {"door": "locked"},
        "npc_state": {},
        "discovered_items": ["key", "door"],
    }
    op = _op("unlock", verb="USE", target="key", on="door",
             pre={"inventory_has": ["key"]},
             eff={"object_state": {"door": "open"}})
    menu = enumerate_menu(world, [op], history=[])
    advances = [a for a in menu if a.category == "advance"]
    assert len(advances) == 1
    assert advances[0].op_id == "unlock"
    assert advances[0].key() == ("USE", "key", "door")


def test_menu_filters_spent_operators_by_op_id():
    world = {
        "current_location": "brig",
        "inventory": [],
        "completed_actions": [{
            "verb": "SEARCH", "target": "crew", "on": "", "op_id": "discovery.search",
            "summary": "found stuff",
        }],
    }
    op = _op("discovery.search", kind="discovery", verb="SEARCH", target="crew",
             eff={"inventory_add": ["x"], "discovered_items": ["x"]})
    menu = enumerate_menu(world, [op], history=[])
    assert not any(a.op_id == "discovery.search" for a in menu)


def test_menu_filters_operators_whose_effects_already_hold():
    """Operators whose checkable effects are all true of the world are spent."""
    world = {
        "current_location": "brig",
        "inventory": [],
        "object_state": {"door": "open"},
    }
    op = _op("unlock", verb="USE", target="key", on="door",
             eff={"object_state": {"door": "open"}})
    menu = enumerate_menu(world, [op], history=[])
    assert not any(a.op_id == "unlock" for a in menu)


def test_menu_synthesises_examine_for_visible_things():
    world = {
        "current_location": "brig",
        "inventory": ["key"],
        "discovered_items": ["lantern"],
        "object_state": {"door": "locked"},
        "npc_state": {"hal": "asleep"},
    }
    menu = enumerate_menu(world, [], history=[])
    examines = {a.target for a in menu if a.verb == "EXAMINE"}
    assert {"brig", "key", "lantern", "door", "hal"}.issubset(examines)


def test_menu_includes_wait_and_say_floor():
    menu = enumerate_menu({"current_location": "x"}, [], history=[])
    verbs = {a.verb for a in menu}
    assert "WAIT" in verbs
    assert "SAY" in verbs


def test_menu_annotates_repeat_count_for_inspection():
    world = {"current_location": "brig", "discovered_items": ["lantern"]}
    history = [
        _action_event("EXAMINE", "lantern"),
        _action_event("EXAMINE", "lantern"),
    ]
    menu = enumerate_menu(world, [], history)
    lantern = next(a for a in menu if a.verb == "EXAMINE" and a.target == "lantern")
    assert lantern.repeat_count == 2
    assert lantern.last_was_no_op is True


def test_menu_skips_inspection_target_when_an_advance_operator_covers_it():
    world = {"current_location": "brig", "npc_state": {"crew": "down"}}
    op = _op("discovery.search", kind="discovery", verb="SEARCH", target="crew",
             eff={"inventory_add": ["x"], "discovered_items": ["x"]})
    menu = enumerate_menu(world, [op], history=[])
    # SEARCH crew is in advance; should NOT also appear in inspect category.
    searches = [a for a in menu if a.verb == "SEARCH" and a.target == "crew"]
    assert len(searches) == 1
    assert searches[0].category == "advance"


# ----------------------------------------------------------------- validator

def test_validate_action_strict_match():
    menu = [Affordance(verb="USE", target="key", on="door", category="advance")]
    assert validate_action(verb="USE", target="key", args={"on": "door"}, menu=menu) is not None
    assert validate_action(verb="USE", target="key", args={"on": "wrong"}, menu=menu) is None
    assert validate_action(verb="USE", target="hammer", args={"on": "door"}, menu=menu) is None


def test_validate_action_combine_is_symmetric_and_accepts_a_b_args():
    menu = [Affordance(verb="COMBINE", target="herb", on="vial", category="advance")]
    # canonical (target, on)
    assert validate_action(verb="COMBINE", target="herb", args={"on": "vial"}, menu=menu)
    # reversed (target, on)
    assert validate_action(verb="COMBINE", target="vial", args={"on": "herb"}, menu=menu)
    # args.a/b shape (forward)
    assert validate_action(verb="COMBINE", target="", args={"a": "herb", "b": "vial"}, menu=menu)
    # args.a/b shape (reversed)
    assert validate_action(verb="COMBINE", target="", args={"a": "vial", "b": "herb"}, menu=menu)
    # wrong pair fails
    assert validate_action(verb="COMBINE", target="other", args={"on": "vial"}, menu=menu) is None


def test_validate_action_move_to_accepts_args_location():
    menu = [Affordance(verb="MOVE_TO", target="", on="lower_decks", category="advance")]
    assert validate_action(verb="MOVE_TO", target="", args={"location": "lower_decks"}, menu=menu)


def test_validate_action_say_tolerates_any_target():
    menu = [Affordance(verb="SAY", target="", on="", category="communicate")]
    assert validate_action(verb="SAY", target="anything", args={}, menu=menu)


# ----------------------------------------------------------------- fallback

def test_fallback_prefers_advance_then_inspect_then_wait():
    menu = [
        Affordance(verb="SAY", target="", on="", category="communicate"),
        Affordance(verb="WAIT", target="", on="", category="wait"),
        Affordance(verb="EXAMINE", target="lantern", on="", category="inspect"),
        Affordance(verb="USE", target="key", on="door", category="advance"),
    ]
    fb = synthesize_fallback_action(menu)
    assert (fb["verb"], fb["target"], fb["args"].get("on", "")) == ("USE", "key", "door")
    # Drop advance.
    fb2 = synthesize_fallback_action(menu[:-1])
    assert fb2["verb"] == "EXAMINE"


# ----------------------------------------------------------------- render

def test_render_menu_groups_by_category_and_annotates_repeats():
    menu = [
        Affordance(verb="USE", target="key", on="door", category="advance",
                   op_id="unlock", why="op `unlock` ready"),
        Affordance(verb="EXAMINE", target="lantern", on="", category="inspect",
                   repeat_count=2, last_was_no_op=True),
        Affordance(verb="WAIT", target="", on="", category="wait"),
    ]
    text = render_menu(menu)
    assert "Advance the plot" in text
    assert "`USE key \u2192 door`" in text
    assert "tried 2x, no new info" in text
    assert "Wait" in text


# ----------------------------------------------------------------- bundle integration

ROOT = Path(__file__).resolve().parent.parent
BLACK_VESPER = ROOT / "scenarios" / "black_vesper"


def test_black_vesper_initial_menu_contains_only_starter_advances():
    """At tick 0 only operators whose preconditions hold on the initial world
    should appear as `advance`. For Black Vesper that's `discovery.search_crew`
    and `discovery.work_nail_free` (folding_knife is starter inventory)."""
    import json
    world = json.loads((BLACK_VESPER / "world_initial.json").read_text())
    docs = [json.loads(line) for line in (BLACK_VESPER / "game.jsonl").read_text().splitlines() if line.strip()]
    ops = extract_operators(docs)
    menu = enumerate_menu(world, ops, history=[])
    advance_ops = {a.op_id for a in menu if a.category == "advance"}
    assert "discovery.search_crew" in advance_ops
    assert "discovery.work_nail_free" in advance_ops
    # Operators with unmet preconditions must NOT be fireable yet.
    assert "puzzle.sedate_hal" not in advance_ops
    assert "puzzle.retrieve_keys" not in advance_ops
    assert "recipe.brew_draught" not in advance_ops


def test_black_vesper_retrieve_keys_appears_after_setup():
    """The pre-discovery of hal_keyring (visible on Hal's belt) must NOT mask
    `puzzle.retrieve_keys` once its preconditions are met."""
    import json
    world = json.loads((BLACK_VESPER / "world_initial.json").read_text())
    docs = [json.loads(line) for line in (BLACK_VESPER / "game.jsonl").read_text().splitlines() if line.strip()]
    ops = extract_operators(docs)
    # Hand-roll the post-tick-10 state: rope rigged, hal deeply asleep.
    world["object_state"]["rope_coil"] = "rigged"
    world["npc_state"]["hal"] = "drugged_deep_sleep"
    menu = enumerate_menu(world, ops, history=[])
    advance_ops = {a.op_id for a in menu if a.category == "advance"}
    assert "puzzle.retrieve_keys" in advance_ops


def test_completed_keys_from_world_extracts_keys_and_op_ids():
    world = {"completed_actions": [
        {"verb": "USE", "target": "key", "on": "door", "op_id": "unlock"},
        {"verb": "EXAMINE", "target": "bunk", "on": ""},
    ]}
    keys, op_ids = completed_keys_from_world(world)
    assert ("USE", "key", "door") in keys
    assert ("EXAMINE", "bunk", "") in keys
    assert op_ids == {"unlock"}
