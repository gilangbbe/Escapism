"""Deterministic mock LLM clients used to smoke-test the wiring without Ollama.

Two flavours:
- :class:`MockPlayerClient` walks Mira through the canonical Act 1 solution.
- :class:`MockGameMasterClient` applies the matching world-state deltas.

Both speak the same JSON protocol the real Ollama-backed agents use, so the
runtime code path is identical.
"""
from __future__ import annotations

import json
import re
from typing import Iterable

from .base import LLMClient, Message


# ---------------------------------------------------------------------------
# Player script: each entry is the JSON payload the player agent emits.
# ---------------------------------------------------------------------------
_PLAYER_SCRIPT: list[dict] = [
    {
        "thought": "I'm awake. The others aren't. Hal's slumped at his desk across the bars. Take stock.",
        "say": "Easy, Mira. Take it one step at a time.",
        "action": {"verb": "EXAMINE", "target": "brig", "args": {}},
    },
    {
        "thought": "Vane drugged the rum. The crew is breathing — Eliza, Jin, Tomás, Kwame. Search them gently.",
        "say": "Sorry, friends. Borrowing what you carry.",
        "action": {"verb": "SEARCH", "target": "crew_unconscious", "args": {}},
    },
    {
        "thought": "Kwame keeps rope on him. The ceiling hook above Hal's desk \u2014 measure the throw.",
        "say": "",
        "action": {"verb": "EXAMINE", "target": "ceiling_hook", "args": {}},
    },
    {
        "thought": "Bunk's bolted to the wall. There's a nail working loose underneath.",
        "say": "",
        "action": {"verb": "EXAMINE", "target": "bunk", "args": {}},
    },
    {
        "thought": "Jin's compass back is concave brass. Held near the lantern flame, it'll focus heat onto a small target.",
        "say": "Old trick. Burning glass without the glass.",
        "action": {"verb": "COMBINE", "args": {"a": "compass_back", "b": "lantern"}},
    },
    {
        "thought": "Eliza's herbs in the vial — valerian, hops, passionflower. The recipe says brewed they drop a horse.",
        "say": "",
        "action": {"verb": "COMBINE", "args": {"a": "herb_packet", "b": "glass_vial"}},
    },
    {
        "thought": "Now heat the vial in the focused flame for two minutes. Quietly.",
        "say": "",
        "action": {"verb": "USE", "target": "glass_vial", "args": {"on": "lantern_focused"}},
    },
    {
        "thought": "Rope over the ceiling hook above Hal's desk. The bars stop arms, not rope.",
        "say": "",
        "action": {"verb": "USE", "target": "rope_coil", "args": {"on": "ceiling_hook"}},
    },
    {
        "thought": "Slip-knot the vial to the rope and lower it over his mug. Tug the knife-tied loop to uncork it.",
        "say": "Drink it down, Hal. There's a good lad.",
        "action": {"verb": "USE", "target": "sleeping_draught", "args": {"on": "hal_mug"}},
    },
    {
        "thought": "He drank. Now I wait — five minutes for the herbs to take him deep.",
        "say": "",
        "action": {"verb": "WAIT", "args": {"minutes": 5}},
    },
    {
        "thought": "He's out cold. Tie the folding knife to the rope end and hook the keyring off his belt.",
        "say": "",
        "action": {"verb": "USE", "target": "rope_grapple", "args": {"on": "hal_keyring"}},
    },
    {
        "thought": "Keys in hand. The cell padlock opens silently.",
        "say": "Easy as that.",
        "action": {"verb": "USE", "target": "hal_keyring", "args": {"on": "cell_door"}},
    },
    {
        "thought": "Stairs to the lower decks. Footsteps overhead — Vane is shouting at someone. Stay low.",
        "say": "",
        "action": {"verb": "MOVE_TO", "args": {"location": "lower_decks"}},
    },
]


# ---------------------------------------------------------------------------
# GM responses: keyed by (verb, target/args fingerprint).
# Each yields the JSON the GM agent emits — narration + state delta.
# ---------------------------------------------------------------------------
def _gm_table() -> dict[tuple[str, str], dict]:
    return {
        ("EXAMINE", "brig"): {
            "narration": (
                "The cell is a six-by-eight iron cage in the belly of the Vesper. Salt has eaten the rivets to "
                "a copper-green. Above you, an oil lantern swings on its chain. Through the bars you can see "
                "Crooked Hal slumped at a wooden desk, snoring with his mouth open, a tin mug at his elbow and "
                "a keyring sagging from his belt. Bolted into the beam directly over his desk is an old iron hook."
            ),
            "delta": {"set": {"scene_id": "brig:taking_stock"}, "time_advance_min": 1},
        },
        ("SEARCH", "crew_unconscious"): {
            "narration": (
                "You move along the cell floor on your hands and knees. From Eliza's coat: a stoppered glass vial, "
                "a packet of three herbs labelled in her hand, and a leather recipe book opened to a sleeping "
                "draught. From Jin's belt: her cracked brass compass. From Tomás: flint and steel. Kwame's rope "
                "is already coiled beside him."
            ),
            "delta": {
                "discovered_items": ["herb_packet", "recipe_book", "glass_vial", "compass_back", "rope_coil"],
                "inventory_add": ["herb_packet", "recipe_book", "glass_vial", "compass_back", "rope_coil"],
                "known_facts_add": [
                    "Eliza's three herbs brewed in hot water make a sleeping draught.",
                    "The compass back is concave brass — useful for focusing heat.",
                ],
                "time_advance_min": 2,
            },
        },
        ("EXAMINE", "ceiling_hook"): {
            "narration": "Above Hal's desk, an old iron beam-hook is set into the deckhead \u2014 once used to hang lanterns. Within rope-throwing range from inside the bars.",
            "delta": {"time_advance_min": 1, "known_facts_add": ["Ceiling hook above Hal's desk is reachable from inside the cell with a rope."]},
        },
        ("EXAMINE", "bunk"): {
            "narration": (
                "The bunk plank is rough-cut pine. Underneath, a rusted nail has been working its way out of the "
                "wood for years. With the knife as a pry, you free it without a sound — three inches of bent iron. "
                "Half a lockpick."
            ),
            "delta": {
                "discovered_items": ["bent_nail"],
                "inventory_add": ["bent_nail"],
                "known_facts_add": ["Bent nail is half a lockpick — needs a thin metal strip to complete."],
                "time_advance_min": 2,
            },
        },
        ("COMBINE", "compass_back+lantern"): {
            "narration": (
                "You climb onto the bunk and hold the compass's polished concave back inches from the lantern "
                "flame. The light pools into a hot pinprick on the cell floor. A reflector worthy of any chemist."
            ),
            "delta": {
                "object_state": {"lantern": "focused"},
                "discovered_items": ["lantern_focused"],
                "known_facts_add": ["Lantern flame is now focused through the compass back."],
                "time_advance_min": 1,
            },
        },
        ("COMBINE", "herb_packet+glass_vial"): {
            "narration": "You crumble the three herbs into the vial. Dry, fragrant, useless until heated.",
            "delta": {
                "object_state": {"vial": "herbs_dry"},
                "inventory_remove": ["herb_packet"],
                "time_advance_min": 1,
            },
        },
        ("USE", "glass_vial->lantern_focused"): {
            "narration": (
                "You hold the vial in the hot pinprick of focused light. Two slow minutes pass. The contents "
                "darken, releasing a sweet, sleepy scent. A draught strong enough to drop a horse."
            ),
            "delta": {
                "object_state": {"vial": "sleeping_draught"},
                "discovered_items": ["sleeping_draught"],
                "inventory_add": ["sleeping_draught"],
                "inventory_remove": ["glass_vial"],
                "known_facts_add": ["Sleeping draught is brewed and ready in the vial."],
                "time_advance_min": 2,
            },
        },
        ("USE", "rope_coil->ceiling_hook"): {
            "narration": (
                "You toss the rope underhand through the bars. Third try — it loops the ceiling hook and falls "
                "back into your hand. A clean rigging from the inside of the cell to the air above Hal's desk."
            ),
            "delta": {
                "object_state": {"rope_coil": "rigged"},
                "discovered_items": ["rope_rigged"],
                "known_facts_add": ["Rope is rigged over the ceiling hook above Hal's desk."],
                "time_advance_min": 1,
            },
        },
        ("USE", "sleeping_draught->hal_mug"): {
            "narration": (
                "You slip-knot the stoppered vial to the rope, lower it across the gap, and with a tug pull the "
                "cork free directly over Hal's mug. The draught streams down into the rum. Hal stirs — mutters — "
                "settles. A minute later his hand finds the mug. He drinks."
            ),
            "delta": {
                "object_state": {"hal_mug": "tainted_drunk", "vial": "spent"},
                "npc_state": {"hal": "drinking_tainted"},
                "inventory_remove": ["sleeping_draught"],
                "time_advance_min": 2,
            },
        },
        ("WAIT", "5min"): {
            "narration": (
                "You count the swing of the lantern. One hundred, two hundred, three hundred. Hal's breathing "
                "deepens, slows. His head settles forward onto the desk. He is gone — for hours."
            ),
            "delta": {
                "npc_state": {"hal": "drugged_deep_sleep"},
                "time_advance_min": 5,
            },
        },
        ("USE", "rope_grapple->hal_keyring"): {
            "narration": (
                "You tie the folding knife to the rope's end as a weighted hook. Three patient casts — and the "
                "blade catches the leather loop. You lift the keyring up, over, and into your waiting hand."
            ),
            "delta": {
                "discovered_items": ["hal_keyring"],
                "inventory_add": ["hal_keyring"],
                "known_facts_add": ["Hal's keyring is now in your hand."],
                "time_advance_min": 3,
            },
        },
        ("USE", "hal_keyring->cell_door"): {
            "narration": (
                "The third key fits. The padlock opens with a soft iron sigh. You ease the door wide enough to "
                "slip through. Hal does not stir."
            ),
            "delta": {
                "object_state": {"cell_door": "open"},
                "objectives": {"escape_brig": "complete", "lower_decks": "active"},
                "known_facts_add": ["Cell door is open. The brig is yours."],
                "time_advance_min": 1,
            },
        },
        ("MOVE_TO", "lower_decks"): {
            "narration": (
                "You take the iron stairs two at a time, silent as a cat. At the top of the stairwell you press "
                "yourself flat against the bulkhead. Vane's voice rings out somewhere above — sharp, irritated, "
                "alive. The lower decks open before you: the cargo hold, the galley, the powder room. The clock "
                "is ticking now in earnest."
            ),
            "delta": {
                "current_location": "lower_decks",
                "set": {"scene_id": "act2:cold_open"},
                "time_advance_min": 1,
                "game_over": "poc_complete",
            },
        },
    }


# ---------------------------------------------------------------------------
class MockPlayerClient(LLMClient):
    name = "mock-player"

    def __init__(self) -> None:
        self._cursor = 0

    def chat(self, messages: Iterable[Message], *, json_mode: bool = False) -> str:
        if self._cursor >= len(_PLAYER_SCRIPT):
            payload = {
                "thought": "I've done all I came to do in the brig.",
                "say": "",
                "action": {"verb": "WAIT", "args": {}},
            }
        else:
            payload = dict(_PLAYER_SCRIPT[self._cursor])
            self._cursor += 1
        # Synthesize a small BDI overlay so the simulation's BDI plumbing
        # exercises on the mock path too.
        payload.setdefault("intent", _intent_from_script(self._cursor - 1))
        payload.setdefault("plan", _plan_from_script(self._cursor - 1))
        return json.dumps(payload)


_INTENTS = [
    "take stock of the brig",
    "search the unconscious crew for tools",
    "find a lockpick or improvised tool",
    "free a usable nail from the bunk",
    "focus the lantern flame to brew a draught",
    "brew the sleeping draught in the vial",
    "heat the vial in the focused flame",
    "rig a rope through the ceiling hook above Hal's desk",
    "deliver the draught into Hal's mug",
    "wait for the draught to take Hal",
    "grapple Hal's keyring off his belt",
    "unlock the cell door silently",
    "descend to the lower decks",
]


def _intent_from_script(idx: int) -> str:
    if 0 <= idx < len(_INTENTS):
        return _INTENTS[idx]
    return "look for the next opportunity"


def _plan_from_script(idx: int) -> list:
    # First step = the action being taken now; followups are placeholders.
    if 0 <= idx < len(_INTENTS):
        return [_INTENTS[idx], "observe the result", "adjust plan based on what changes"]
    return ["assess the situation", "act on what changed"]


class MockGameMasterClient(LLMClient):
    name = "mock-gm"
    _table = _gm_table()

    def chat(self, messages: Iterable[Message], *, json_mode: bool = False) -> str:
        last_user = ""
        for m in messages:
            if m.role == "user":
                last_user = m.content
        action = _extract_action(last_user)
        key = _key_for(action)
        entry = self._table.get(key)
        if entry is None:
            return json.dumps(
                {
                    "narration": "Nothing happens. (Mock GM has no scripted response for that action.)",
                    "delta": {"time_advance_min": 1},
                    "success": False,
                }
            )
        return json.dumps({"narration": entry["narration"], "delta": entry["delta"], "success": True})


# ---------------------------------------------------------------------------
_ACTION_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_action(text: str) -> dict:
    # Scan every JSON fence; return the first one whose payload contains a verb.
    for match in _ACTION_RE.finditer(text):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if _looks_like_action(payload):
            return payload
    # Fallback: scan every brace-balanced JSON block.
    cursor = 0
    while cursor < len(text):
        start = text.find("{", cursor)
        if start == -1:
            break
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        payload = json.loads(text[start : i + 1])
                        if _looks_like_action(payload):
                            return payload
                    except json.JSONDecodeError:
                        pass
                    cursor = i + 1
                    break
        else:
            break
    return {}


def _looks_like_action(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    action = payload.get("action")
    if isinstance(action, dict) and action.get("verb"):
        return True
    return bool(payload.get("verb"))


def _key_for(action_payload: dict) -> tuple[str, str]:
    action = action_payload.get("action") or action_payload
    verb = (action.get("verb") or "").upper()
    target = action.get("target") or ""
    args = action.get("args") or {}
    if verb == "COMBINE":
        a, b = sorted([args.get("a", ""), args.get("b", "")])
        # Map order-insensitive pairs to scripted keys.
        for known in (("compass_back", "lantern"), ("herb_packet", "glass_vial")):
            if sorted(known) == [a, b]:
                return ("COMBINE", f"{known[0]}+{known[1]}")
        return ("COMBINE", f"{a}+{b}")
    if verb == "USE":
        on = args.get("on", "")
        return ("USE", f"{target}->{on}")
    if verb == "WAIT":
        mins = args.get("minutes")
        if mins:
            return ("WAIT", f"{mins}min")
        return ("WAIT", "")
    if verb == "MOVE_TO":
        return ("MOVE_TO", args.get("location", ""))
    return (verb, target)
