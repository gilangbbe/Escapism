"""Tests for WorldState.apply_delta, including auto fail-states."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.world.state import WorldState, _advance_clock


def _world(**overrides):
    base = {
        "tick": 0,
        "in_game_time": "04:30",
        "minutes_until_port_royal": 90,
        "current_location": "brig",
        "alarm_meter": 0,
        "alarm_max": 10,
        "inventory": [],
        "discovered_items": [],
        "known_facts": [],
        "npc_state": {},
        "object_state": {},
        "objectives": {"escape_brig": "active"},
        "act": 1,
        "scene_id": "brig:cold_open",
    }
    base.update(overrides)
    return WorldState(base)


# ------------------------------------------------------------- basic mutations
class TestBasicDelta:
    def test_empty_delta_no_op(self):
        w = _world()
        assert w.apply_delta({}) == []
        assert w.tick == 0

    def test_non_dict_delta_safe(self):
        w = _world()
        assert w.apply_delta("not a dict") == []  # type: ignore[arg-type]

    def test_set(self):
        w = _world()
        notes = w.apply_delta({"set": {"weather": "fog"}})
        assert w.data["weather"] == "fog"
        assert any("weather" in n for n in notes)

    def test_inventory_add_and_remove(self):
        w = _world()
        w.apply_delta({"inventory_add": ["knife", "rope"]})
        assert w.inventory == ["knife", "rope"]
        # idempotent
        w.apply_delta({"inventory_add": ["knife"]})
        assert w.inventory == ["knife", "rope"]
        w.apply_delta({"inventory_remove": ["knife", "ghost_item"]})
        assert w.inventory == ["rope"]

    def test_discovered_items_moves_from_hidden(self):
        w = _world(hidden_items=["secret_key"])
        w.apply_delta({"discovered_items": ["secret_key"]})
        assert "secret_key" in w.data["discovered_items"]
        assert "secret_key" not in w.data["hidden_items"]

    def test_known_facts_dedup(self):
        w = _world()
        w.apply_delta({"known_facts_add": ["the door is iron", "the door is iron"]})
        assert w.data["known_facts"].count("the door is iron") == 1

    def test_npc_and_object_state(self):
        w = _world()
        w.apply_delta({"npc_state": {"hal": "asleep"}, "object_state": {"door": "locked"}})
        assert w.data["npc_state"]["hal"] == "asleep"
        assert w.data["object_state"]["door"] == "locked"

    def test_objectives(self):
        w = _world()
        w.apply_delta({"objectives": {"escape_brig": "complete"}})
        assert w.data["objectives"]["escape_brig"] == "complete"


# ------------------------------------------------------------- alarm + time
class TestAlarmAndTime:
    def test_alarm_delta_increases(self):
        w = _world()
        w.apply_delta({"alarm_delta": 3})
        assert w.alarm == 3

    def test_alarm_floor_at_zero(self):
        w = _world(alarm_meter=2)
        w.apply_delta({"alarm_delta": -10})
        assert w.alarm == 0

    def test_time_advances_clock_and_decrements_countdown(self):
        w = _world()
        w.apply_delta({"time_advance_min": 15})
        assert w.data["in_game_time"] == "04:45"
        assert w.data["minutes_until_port_royal"] == 75

    def test_time_countdown_floor_at_zero(self):
        w = _world(minutes_until_port_royal=5)
        w.apply_delta({"time_advance_min": 10})
        assert w.data["minutes_until_port_royal"] == 0


# ------------------------------------------------------------- auto fail-states
class TestAutoFailStates:
    def test_alarm_at_max_triggers_game_over(self):
        w = _world(alarm_meter=8)
        notes = w.apply_delta({"alarm_delta": 2})
        assert w.game_over == "alarm_max"
        assert w.data.get("auto_game_over") == "alarm_max"
        assert any("alarm" in n.lower() and "hal" in n.lower() for n in notes)

    def test_alarm_above_max_still_triggers(self):
        w = _world(alarm_meter=0)
        w.apply_delta({"alarm_delta": 99})
        assert w.game_over == "alarm_max"

    def test_time_zero_triggers_port_royal_fail(self):
        w = _world(minutes_until_port_royal=10)
        w.apply_delta({"time_advance_min": 10})
        assert w.game_over == "port_royal_reached"
        assert w.data.get("auto_game_over") == "port_royal_reached"

    def test_explicit_game_over_wins_over_auto(self):
        w = _world(alarm_meter=10)  # would auto-fire
        w.apply_delta({"game_over": "poc_complete"})
        assert w.game_over == "poc_complete"
        assert "auto_game_over" not in w.data

    def test_no_auto_when_below_threshold(self):
        w = _world(alarm_meter=5, minutes_until_port_royal=30)
        w.apply_delta({"alarm_delta": 1, "time_advance_min": 5})
        assert w.game_over is None
        assert "auto_game_over" not in w.data


# ------------------------------------------------------------- clock helper
class TestAdvanceClock:
    def test_simple(self):
        assert _advance_clock("04:30", 15) == "04:45"

    def test_hour_rollover(self):
        assert _advance_clock("04:50", 20) == "05:10"

    def test_midnight_wrap(self):
        assert _advance_clock("23:50", 20) == "00:10"

    def test_malformed_returns_input(self):
        assert _advance_clock("not a time", 5) == "not a time"
