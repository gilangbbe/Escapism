"""Tests for the tolerant JSON protocol parsers."""
from __future__ import annotations

import pytest

from server.agents.protocol import (
    _extract_first_json,
    parse_gm_response,
    parse_player_response,
)


# -------------------------------------------------------------- _extract_first_json
class TestExtractFirstJson:
    def test_returns_none_for_empty(self):
        assert _extract_first_json("") is None
        assert _extract_first_json("no json here at all") is None

    def test_plain_json_object(self):
        assert _extract_first_json('{"a": 1}') == {"a": 1}

    def test_json_with_prose_prefix_and_suffix(self):
        text = "Sure! Here it is:\n{\"verb\": \"WAIT\"}\nThanks."
        assert _extract_first_json(text) == {"verb": "WAIT"}

    def test_fenced_json_block(self):
        text = "```json\n{\"narration\": \"hi\"}\n```"
        assert _extract_first_json(text) == {"narration": "hi"}

    def test_fenced_without_language_tag(self):
        text = "```\n{\"x\": 2}\n```"
        assert _extract_first_json(text) == {"x": 2}

    def test_multiple_fences_picks_first_parseable(self):
        # The greedy brace fallback should still find a valid object even
        # when the first looks fine. The fenced regex picks the first fence.
        text = "```json\n{\"a\": 1}\n```\n```json\n{\"b\": 2}\n```"
        assert _extract_first_json(text) == {"a": 1}

    def test_falls_back_to_brace_scan_when_fence_malformed(self):
        text = "```json\n{not json}\n```\nbut here is one: {\"ok\": true}"
        assert _extract_first_json(text) == {"ok": True}

    def test_nested_objects(self):
        text = '{"outer": {"inner": [1, 2, 3]}}'
        assert _extract_first_json(text) == {"outer": {"inner": [1, 2, 3]}}

    def test_returns_none_when_all_attempts_fail(self):
        assert _extract_first_json("{still {nested but unclosed") is None


# -------------------------------------------------------------- parse_player_response
class TestParsePlayerResponse:
    def test_full_action(self):
        raw = """```json
{"thought": "be still", "say": "", "action": {"verb": "EXAMINE", "target": "bunk", "args": {}}}
```"""
        a = parse_player_response(raw)
        assert a.thought == "be still"
        assert a.say == ""
        assert a.verb == "EXAMINE"
        assert a.target == "bunk"
        assert a.args == {}
        assert a.is_silent is True

    def test_verb_uppercased(self):
        a = parse_player_response('{"action": {"verb": "examine", "target": "x"}}')
        assert a.verb == "EXAMINE"

    def test_missing_action_defaults_to_wait(self):
        a = parse_player_response('{"thought": "...", "say": ""}')
        assert a.verb == "WAIT"
        assert a.target == ""
        assert a.args == {}

    def test_garbage_input_does_not_raise(self):
        a = parse_player_response("complete gibberish, no JSON anywhere")
        assert a.verb == "WAIT"
        assert a.raw == {}

    def test_non_dict_args_coerced_to_empty(self):
        a = parse_player_response('{"action": {"verb": "USE", "args": "not a dict"}}')
        assert a.args == {}

    def test_say_present(self):
        a = parse_player_response('{"say": "easy now", "action": {"verb": "WAIT"}}')
        assert a.say == "easy now"
        assert a.is_silent is False

    def test_bdi_fields_parsed(self):
        a = parse_player_response(
            '{"intent": "sedate Hal", "plan": ["brew draught", "deliver in mug", "wait"],'
            ' "action": {"verb": "USE", "target": "vial"}}'
        )
        assert a.intent == "sedate Hal"
        assert a.plan == ["brew draught", "deliver in mug", "wait"]

    def test_bdi_missing_defaults_safe(self):
        a = parse_player_response('{"action": {"verb": "WAIT"}}')
        assert a.intent == ""
        assert a.plan is None

    def test_bdi_non_string_plan_items_filtered(self):
        a = parse_player_response(
            '{"plan": ["good", 7, "", "  ", null, "alsoGood"],'
            ' "action": {"verb": "WAIT"}}'
        )
        assert a.plan == ["good", "alsoGood"]


# -------------------------------------------------------------- parse_gm_response
class TestParseGmResponse:
    def test_full_response(self):
        raw = """```json
{
  "narration": "You ease the bolt.",
  "success": true,
  "delta": {"alarm_delta": 1, "time_advance_min": 2}
}
```"""
        r = parse_gm_response(raw)
        assert r["narration"] == "You ease the bolt."
        assert r["success"] is True
        assert r["delta"] == {"alarm_delta": 1, "time_advance_min": 2}

    def test_defaults_when_missing(self):
        r = parse_gm_response('{}')
        assert r["narration"] == ""
        assert r["success"] is True   # default
        assert r["delta"] == {}

    def test_non_dict_delta_coerced_to_empty(self):
        r = parse_gm_response('{"delta": "oops"}')
        assert r["delta"] == {}

    def test_success_false(self):
        r = parse_gm_response('{"success": false, "narration": "no"}')
        assert r["success"] is False

    def test_garbage_input(self):
        r = parse_gm_response("not json")
        assert r["narration"] == ""
        assert r["delta"] == {}
