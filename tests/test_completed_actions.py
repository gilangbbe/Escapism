"""Tests for the completed-actions ledger and narration\u2194delta consistency guard."""
from __future__ import annotations

from server.world.state import WorldState, delta_is_substantive


def _world():
    return WorldState(data={"tick": 5, "inventory": [], "alarm_meter": 0,
                            "minutes_until_port_royal": 60, "alarm_max": 10})


# --------------------------------------------------------------- delta_is_substantive

class TestDeltaIsSubstantive:
    def test_empty_is_not_substantive(self):
        assert delta_is_substantive({}) is False

    def test_none_is_not_substantive(self):
        assert delta_is_substantive(None) is False

    def test_time_only_is_not_substantive(self):
        assert delta_is_substantive({"time_advance_min": 5}) is False

    def test_alarm_only_is_not_substantive(self):
        assert delta_is_substantive({"alarm_delta": 1, "time_advance_min": 2}) is False

    def test_inventory_add_is_substantive(self):
        assert delta_is_substantive({"inventory_add": ["nail"]}) is True

    def test_object_state_is_substantive(self):
        assert delta_is_substantive({"object_state": {"herbs": "brewed"}}) is True

    def test_known_facts_add_is_substantive(self):
        assert delta_is_substantive({"known_facts_add": ["new fact"]}) is True

    def test_objectives_is_substantive(self):
        assert delta_is_substantive({"objectives": {"escape_brig": "complete"}}) is True

    def test_empty_list_is_not_substantive(self):
        assert delta_is_substantive({"inventory_add": []}) is False

    def test_empty_dict_for_object_state_not_substantive(self):
        assert delta_is_substantive({"object_state": {}}) is False


# --------------------------------------------------------------- completed_actions

class TestCompletedActions:
    def test_record_adds_entry(self):
        w = _world()
        w.record_completed_action(
            verb="USE", target="herbs",
            args={"on": "vial"}, summary="herbs=brewed; +inv sleeping_draught",
        )
        log = w.data["completed_actions"]
        assert len(log) == 1
        assert log[0]["verb"] == "USE"
        assert log[0]["target"] == "herbs"
        assert log[0]["on"] == "vial"
        assert "brewed" in log[0]["summary"]

    def test_record_is_idempotent_on_key(self):
        w = _world()
        w.record_completed_action(verb="USE", target="herbs", args={"on": "vial"}, summary="first")
        w.record_completed_action(verb="USE", target="herbs", args={"on": "vial"}, summary="second")
        assert len(w.data["completed_actions"]) == 1
        assert w.data["completed_actions"][0]["summary"] == "first"

    def test_record_distinguishes_targets(self):
        w = _world()
        w.record_completed_action(verb="USE", target="herbs", args={"on": "vial"}, summary="a")
        w.record_completed_action(verb="USE", target="compass_back", args={"on": "lantern"}, summary="b")
        assert len(w.data["completed_actions"]) == 2

    def test_find_returns_entry(self):
        w = _world()
        w.record_completed_action(verb="USE", target="herbs", args={"on": "vial"}, summary="done")
        found = w.find_completed_action(verb="USE", target="herbs", args={"on": "vial"})
        assert found is not None
        assert found["summary"] == "done"

    def test_find_returns_none_for_unknown(self):
        w = _world()
        assert w.find_completed_action(verb="USE", target="herbs", args={"on": "vial"}) is None

    def test_find_is_case_insensitive_on_verb(self):
        w = _world()
        w.record_completed_action(verb="USE", target="herbs", args={"on": "vial"}, summary="x")
        assert w.find_completed_action(verb="use", target="herbs", args={"on": "vial"}) is not None

    def test_find_uses_combine_args(self):
        w = _world()
        w.record_completed_action(verb="COMBINE", target="bent_nail", args={"b": "compass_back"}, summary="ok")
        assert w.find_completed_action(verb="COMBINE", target="bent_nail", args={"b": "compass_back"}) is not None
