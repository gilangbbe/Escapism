"""Tests for the puzzle precondition / effect validator."""
from __future__ import annotations

from dataclasses import dataclass, field

from server.agents.puzzle_validator import (
    check_preconditions,
    delta_grants_effect,
    find_triggered_puzzle,
    format_precondition_brief,
)


@dataclass
class _FakeClueStore:
    docs: list[dict] = field(default_factory=list)


_PUZZLE = {
    "id": "puzzle.sedate_hal",
    "kind": "puzzle",
    "scope": ["act1"],
    "title": "Sedate Hal",
    "trigger": {"verb": "USE", "target": "sleeping_draught", "on": "hal_mug"},
    "preconditions": {
        "inventory_has": ["sleeping_draught"],
        "object_state": {"rope_coil": "rigged"},
    },
    "effects": {
        "object_state": {"hal_mug": "tainted_drunk"},
        "npc_state": {"hal": "drinking_tainted"},
        "inventory_remove": ["sleeping_draught"],
    },
}

_PUZZLE_KEYS = {
    "id": "puzzle.act1_exit",
    "kind": "puzzle",
    "scope": ["act1"],
    "trigger": {"verb": "USE", "target": "hal_keyring", "on": "cell_door"},
    "preconditions": {
        "inventory_has": ["hal_keyring"],
        "object_state": {"cell_door": "locked"},
    },
    "effects": {
        "object_state": {"cell_door": "open"},
        "objectives": {"escape_brig": "complete"},
    },
}


# --------------------------------------------------------------- find_triggered_puzzle

def test_find_triggered_puzzle_matches_verb_target_on():
    store = _FakeClueStore(docs=[_PUZZLE, _PUZZLE_KEYS])
    found = find_triggered_puzzle(
        store, verb="USE", target="sleeping_draught", args={"on": "hal_mug"}, scope="act1",
    )
    assert found is not None
    assert found["id"] == "puzzle.sedate_hal"


def test_find_triggered_puzzle_returns_none_for_no_match():
    store = _FakeClueStore(docs=[_PUZZLE])
    assert find_triggered_puzzle(
        store, verb="EXAMINE", target="hal", args={}, scope="act1",
    ) is None


def test_find_triggered_puzzle_respects_scope():
    store = _FakeClueStore(docs=[_PUZZLE])
    assert find_triggered_puzzle(
        store, verb="USE", target="sleeping_draught", args={"on": "hal_mug"}, scope="act2",
    ) is None


def test_find_triggered_puzzle_case_insensitive_verb():
    store = _FakeClueStore(docs=[_PUZZLE])
    found = find_triggered_puzzle(
        store, verb="use", target="sleeping_draught", args={"on": "hal_mug"}, scope="act1",
    )
    assert found is not None


# --------------------------------------------------------------- check_preconditions

def test_check_preconditions_all_met():
    world = {
        "inventory": ["sleeping_draught"],
        "object_state": {"rope_coil": "rigged"},
    }
    assert check_preconditions(_PUZZLE, world) == []


def test_check_preconditions_missing_inventory():
    world = {"inventory": [], "object_state": {"rope_coil": "rigged"}}
    unmet = check_preconditions(_PUZZLE, world)
    assert len(unmet) == 1
    assert "sleeping_draught" in unmet[0]


def test_check_preconditions_wrong_object_state():
    world = {
        "inventory": ["sleeping_draught"],
        "object_state": {"rope_coil": "unrigged"},
    }
    unmet = check_preconditions(_PUZZLE, world)
    assert len(unmet) == 1
    assert "rope_coil" in unmet[0]


def test_check_preconditions_multiple_unmet():
    world = {"inventory": [], "object_state": {}}
    unmet = check_preconditions(_PUZZLE, world)
    assert len(unmet) == 2


def test_check_preconditions_npc_state():
    puzzle = {
        "preconditions": {"npc_state": {"hal": "drugged_deep_sleep"}},
    }
    world = {"npc_state": {"hal": "asleep_drunk"}}
    unmet = check_preconditions(puzzle, world)
    assert "hal" in unmet[0]


# --------------------------------------------------------------- delta_grants_effect

def test_delta_grants_effect_object_state():
    delta = {"object_state": {"hal_mug": "tainted_drunk"}}
    assert delta_grants_effect(delta, _PUZZLE) is True


def test_delta_grants_effect_unrelated_delta():
    delta = {"inventory_add": ["random_thing"], "time_advance_min": 2}
    assert delta_grants_effect(delta, _PUZZLE) is False


def test_delta_grants_effect_objective_complete():
    delta = {"objectives": {"escape_brig": "complete"}}
    assert delta_grants_effect(delta, _PUZZLE_KEYS) is True


def test_delta_grants_effect_empty_delta():
    assert delta_grants_effect({}, _PUZZLE) is False


# --------------------------------------------------------------- format_precondition_brief

def test_format_precondition_brief_includes_requirements_and_effects():
    brief = format_precondition_brief(_PUZZLE)
    assert "sleeping_draught" in brief
    assert "rope_coil=rigged" in brief
    assert "hal_mug=tainted_drunk" in brief
