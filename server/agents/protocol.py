"""Shared protocol primitives for player ↔ GM communication."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


PLAYER_ACTION_SCHEMA = {
    "thought": "string (internal monologue, not spoken)",
    "say": "string (spoken aloud; empty string if silent)",
    "action": {
        "verb": "one of: EXAMINE, SEARCH, TAKE, COMBINE, USE, WAIT, MOVE_TO, SAY",
        "target": "string id of an item, npc, object, or location (optional)",
        "args": "object with verb-specific arguments (e.g. {a, b} for COMBINE, {on} for USE)",
    },
}

GM_RESPONSE_SCHEMA = {
    "narration": "string in second person, period-appropriate, 2-5 sentences",
    "success": "bool — did the action accomplish something",
    "delta": {
        "set": "object of world-state key/value overrides",
        "inventory_add": "list of item ids",
        "inventory_remove": "list of item ids",
        "npc_state": "object of npc_id -> state",
        "object_state": "object of object_id -> state",
        "discovered_items": "list of item ids the player can now see",
        "known_facts_add": "list of short sentences the player has now learned",
        "objectives": "object of objective_id -> 'active'|'complete'|'failed'",
        "alarm_delta": "integer change to the alarm meter",
        "time_advance_min": "integer minutes consumed by this action",
        "scene_id": "string scene marker (optional)",
        "current_location": "string location id (optional)",
        "game_over": "string 'win'|'lose'|'poc_complete' (optional)",
    },
}


@dataclass
class PlayerAction:
    thought: str
    say: str
    verb: str
    target: str
    args: dict[str, Any]
    raw: dict[str, Any]

    @property
    def is_silent(self) -> bool:
        return not self.say.strip()


def parse_player_response(text: str) -> PlayerAction:
    payload = _extract_first_json(text) or {}
    action = payload.get("action") or {}
    return PlayerAction(
        thought=str(payload.get("thought") or "").strip(),
        say=str(payload.get("say") or "").strip(),
        verb=str(action.get("verb") or "WAIT").upper(),
        target=str(action.get("target") or "").strip(),
        args=action.get("args") if isinstance(action.get("args"), dict) else {},
        raw=payload,
    )


def parse_gm_response(text: str) -> dict[str, Any]:
    payload = _extract_first_json(text) or {}
    return {
        "narration": str(payload.get("narration") or "").strip(),
        "success": bool(payload.get("success", True)),
        "delta": payload.get("delta") if isinstance(payload.get("delta"), dict) else {},
        "raw": payload,
    }


# ---------------------------------------------------------------------------
def _extract_first_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    # Code-fenced JSON first.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    # Greedy brace match.
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None
