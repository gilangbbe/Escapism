"""Game Master agent: the world's sole mutator and narrator.

It receives the player's structured action plus the live world snapshot,
retrieves the relevant clue documents, and emits a JSON response with prose
narration and a structured state delta.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..llm import LLMClient, Message
from ..memory import ClueStore
from .protocol import GM_RESPONSE_SCHEMA, PlayerAction, parse_gm_response


PERSONA = (
    "You are the Game Master of *The Last Voyage of the Black Vesper*, a tense narrative escape room set "
    "aboard a pirate brig in 1721. The protagonist is Mira 'Ironhand' Castellanos, the Quartermaster — "
    "the only crew member awake in the brig. You narrate in second person, period-appropriate prose. "
    "You are the sole authority on what is true in the world. You never invent items the clue corpus "
    "does not mention. You enforce diegetic rules (no forcing the cell door, noise wakes Hal, item "
    "combinations must be physically plausible). When the player tries something nonsensical or premature, "
    "you describe the failure honestly and advance time without unlocking progress."
)

SYSTEM_RULES = (
    "On each turn you MUST output a single JSON object that exactly matches this schema:\n"
    f"{json.dumps(GM_RESPONSE_SCHEMA, indent=2)}\n\n"
    "Rules:\n"
    "- Narration is 2-5 sentences, second person, sensory, period-appropriate.\n"
    "- Only mutate the world via the `delta` object. Every field is optional; include only what changed.\n"
    "- Reward correct progress. Block invalid actions with `success: false` and a small time/alarm cost.\n"
    "- Stay grounded in the provided clue documents. Do not invent new items, NPCs, or rooms.\n"
    "\n## Time and alarm (CRITICAL — narrate these honestly)\n"
    "- `alarm_meter` rises toward `alarm_max` (default 10). At max, Hal wakes and the run ends. \n"
    "  Whenever you raise the alarm, NARRATE the cause (a creak, a clink, a footfall) in the prose.\n"
    "- `minutes_until_port_royal` counts down to 0. At 0 the ship moors and the run ends. Whenever\n"
    "  you advance time, NARRATE the passage (sand in an hourglass, the watch bell, paling sky).\n"
    "- If the alarm is at or above 8, treat the situation as critical and say so in the prose.\n"
    "- If minutes_until_port_royal <= 15, mention dawn/the approaching coast.\n"
    "- If your delta would push alarm to `alarm_max` or time to 0, include `game_over` accordingly\n"
    "  and write a proper closing paragraph in the narration.\n"
    "\n## Anti-stall (CRITICAL)\n"
    "- If the player just repeated an EXAMINE or SEARCH that already produced no progress, your\n"
    "  delta MUST either (a) reveal a new `known_facts_add` that points to the NEXT useful action,\n"
    "  or (b) add a small `alarm_delta` and `time_advance_min` so dithering has a cost.\n"
    "- Never echo the same `known_facts_add` text more than once in the same run.\n"
    "\nOutput ONLY the JSON object. No prose before or after."
)


@dataclass
class GameMasterAgent:
    llm: LLMClient
    clues: ClueStore

    def adjudicate(
        self,
        world: dict[str, Any],
        action: PlayerAction,
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prompt = self._build_user_prompt(world, action, history)
        messages = [
            Message("system", PERSONA + "\n\n" + SYSTEM_RULES),
            Message("user", prompt),
        ]
        raw = self.llm.chat(messages, json_mode=True)
        parsed = parse_gm_response(raw)
        parsed["raw"]["_llm_raw"] = raw
        return parsed

    # ------------------------------------------------------------------ prompt
    def _build_user_prompt(
        self,
        world: dict[str, Any],
        action: PlayerAction,
        history: list[dict[str, Any]],
    ) -> str:
        scope = f"act{world.get('act', 1)}"
        retrieved = self.clues.query(self._retrieval_query(world, action), k=8, scope=scope)
        sections = [
            "## Current world",
            "```json",
            json.dumps(world, indent=2),
            "```",
            "## Player's action this turn",
            "```json",
            json.dumps(action.raw, indent=2),
            "```",
            "## Grounding clues",
        ]
        for doc in retrieved:
            sections.append(f"- **{doc.get('title') or doc['id']}** ({doc.get('kind')}) — {doc.get('text', '')}")

        # Recent player actions (for stall detection).
        recent_actions = [ev for ev in history if ev.get("kind") == "player_action"][-4:]
        if recent_actions:
            sections.append("\n## Player's recent actions (for stall detection)")
            for ev in recent_actions:
                a = ev.get("payload", {}).get("action", {}) or {}
                sections.append(
                    f"- t{ev['tick']}: {a.get('verb','?')} {a.get('target','') or ''} {a.get('args','') or ''}".rstrip()
                )

        sections.append("\n## Recent events")
        for ev in history[-10:]:
            sections.append(f"- t{ev['tick']} [{ev['actor']}] {ev['kind']}")
        sections.append("\n## Your response")
        sections.append(
            "Return the JSON adjudication only. Be faithful to the clues above; do not invent new world facts. "
            "If the player is stalling, advance time or alarm and point the next step via known_facts_add."
        )
        sections.append("```json\n{...your response...}\n```")
        return "\n".join(sections)

    @staticmethod
    def _retrieval_query(world: dict[str, Any], action: PlayerAction) -> str:
        parts = [
            action.verb,
            action.target,
            json.dumps(action.args),
            world.get("current_location", ""),
            world.get("scene_id", ""),
        ]
        return " ".join(str(p) for p in parts if p)
