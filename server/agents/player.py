"""Player agent: Mira's cognitive loop.

Each turn it builds a prompt from (a) persona, (b) world snapshot,
(c) retrieved clues from the vector store, and (d) recent narrative history,
then asks the LLM for a single JSON action.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..llm import LLMClient, Message
from ..memory import ClueStore
from .protocol import PLAYER_ACTION_SCHEMA, PlayerAction, parse_player_response


PERSONA = (
    "You are Mira 'Ironhand' Castellanos, Quartermaster of the pirate brig Black Vesper. "
    "It is 1721. Captain Vane has drugged the crew and locked you all in the brig, sailing to "
    "Port Royal to trade you to the British Navy for a pardon. Your shipmates lie unconscious around "
    "you in the cell. You alone are awake. Your style: terse, period-appropriate, observational. "
    "You think in plain pragmatic sentences. You speak only when speaking helps you or steadies your "
    "nerves. Above all: be quiet. Crooked Hal is asleep at his desk just outside the bars — wake him "
    "and it is over."
)

SYSTEM_RULES = (
    "On each turn you MUST output a single JSON object that exactly matches this schema:\n"
    f"{json.dumps(PLAYER_ACTION_SCHEMA, indent=2)}\n\n"
    "Rules:\n"
    "- Choose ONE concrete action per turn. Never narrate multiple steps in one turn.\n"
    "- Use only items that appear in your inventory or are listed in 'discovered_items'/'object_state'.\n"
    "- The available verbs are: EXAMINE (look), SEARCH (rummage), TAKE, COMBINE (args: {a, b}), "
    "USE (target: item, args: {on: target}), WAIT (args: {minutes}), MOVE_TO (args: {location}), SAY.\n"
    "- If you do not yet have an item you need, examine or search for it first.\n"
    "- Do not invent items the world has not shown you.\n"
    "\n## Anti-loop rules (CRITICAL)\n"
    "- NEVER repeat the same (verb, target) you used in your last 3 actions. Look at the 'Recent actions' "
    "  list below: if your last action was EXAMINE hal_keyring, do NOT EXAMINE hal_keyring again.\n"
    "- EXAMINE and SEARCH are information verbs. After you have examined something once, your next "
    "  action on it MUST be a state-changing verb: TAKE, USE, COMBINE, MOVE_TO, or WAIT.\n"
    "- If a previous action produced no visible change in the world snapshot (no new inventory, no new "
    "  known_fact, no objective progress), it was a dead end. Try a DIFFERENT verb or a DIFFERENT target.\n"
    "- Re-read the 'objectives' that are still active and pick the action that most directly advances one "
    "  of them. Items in your inventory exist to be USED or COMBINED, not re-examined.\n"
    "\nOutput ONLY the JSON object. No prose before or after."
)


@dataclass
class PlayerAgent:
    llm: LLMClient
    clues: ClueStore

    def decide(self, world: dict[str, Any], history: list[dict[str, Any]]) -> PlayerAction:
        prompt = self._build_user_prompt(world, history)
        messages = [
            Message("system", PERSONA + "\n\n" + SYSTEM_RULES),
            Message("user", prompt),
        ]
        raw = self.llm.chat(messages, json_mode=True)
        action = parse_player_response(raw)
        action.raw["_llm_raw"] = raw
        return action

    # ------------------------------------------------------------------ prompt
    def _build_user_prompt(self, world: dict[str, Any], history: list[dict[str, Any]]) -> str:
        scope = f"act{world.get('act', 1)}"
        retrieved = self.clues.query(
            self._retrieval_query(world, history), k=6, scope=scope
        )

        recent_actions = [ev for ev in history if ev.get("kind") == "player_action"][-5:]
        recent_hints = [ev for ev in history if ev.get("kind") == "system_hint"][-2:]

        sections = [
            "## World snapshot",
            "```json",
            json.dumps(_world_view(world), indent=2),
            "```",
            "## Relevant clues (from your memory of the ship)",
        ]
        for doc in retrieved:
            sections.append(f"- **{doc.get('title') or doc['id']}** — {doc.get('text', '')}")

        sections.append("\n## Recent actions YOU have already taken (DO NOT REPEAT)")
        if recent_actions:
            for ev in recent_actions:
                a = ev.get("payload", {}).get("action", {})
                sections.append(
                    f"- t{ev['tick']}: {a.get('verb','?')} {a.get('target','') or ''} {a.get('args','') or ''}".rstrip()
                )
        else:
            sections.append("- (none yet)")

        sections.append("\n## Recent narration / events")
        for ev in history[-8:]:
            if ev.get("kind") in {"player_action", "player_thought", "player_say"}:
                continue
            sections.append(f"- t{ev['tick']} [{ev['actor']}] {ev['kind']}: {self._render_event(ev)}")

        if recent_hints:
            sections.append("\n## System hints (heed these)")
            for ev in recent_hints:
                sections.append(f"- {ev.get('payload', {}).get('text', '')}")

        sections.append("\n## Your next action")
        sections.append(
            "Pick a NEW action that advances an active objective. If the last GM narration revealed "
            "something (an item within reach, a sound, a fact), ACT on it now — do not re-examine. "
            "Respond with the JSON object only."
        )
        # Wrap final action request so the GM stub mock can also find it; harmless for real LLM.
        sections.append("```json\n{...your action json...}\n```")
        return "\n".join(sections)

    @staticmethod
    def _retrieval_query(world: dict[str, Any], history: list[dict[str, Any]]) -> str:
        # Bias retrieval toward forward progress: active objectives + inventory + scene.
        # Deliberately do NOT include the last event payload, which causes the model to
        # keep retrieving the clue for the action it just took (repetition loop).
        active_objs = [
            oid for oid, status in (world.get("objectives") or {}).items() if status == "active"
        ]
        bits = [
            world.get("current_location", ""),
            world.get("scene_id", ""),
            " ".join(active_objs),
            " ".join(world.get("inventory", [])),
            " ".join(world.get("known_facts", [])[-3:]),
        ]
        return " ".join(b for b in bits if b)

    @staticmethod
    def _render_event(ev: dict[str, Any]) -> str:
        p = ev.get("payload", {})
        if ev["kind"] == "player_action":
            a = p.get("action", {})
            return f"{a.get('verb')} {a.get('target', '')} {a.get('args', '')}".strip()
        if ev["kind"] == "gm_narration":
            return (p.get("text") or "")[:200]
        return json.dumps(p)[:200]


def _world_view(world: dict[str, Any]) -> dict[str, Any]:
    """A trimmed world view suitable for prompting — drops noisy/irrelevant fields."""
    keep = (
        "tick",
        "in_game_time",
        "minutes_until_port_royal",
        "current_location",
        "alarm_meter",
        "inventory",
        "discovered_items",
        "known_facts",
        "npc_state",
        "object_state",
        "objectives",
        "scene_id",
    )
    return {k: world.get(k) for k in keep if k in world}
