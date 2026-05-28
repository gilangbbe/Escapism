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
from .puzzle_validator import find_triggered_puzzle, check_preconditions, format_precondition_brief


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
    "\n## Idempotency — NEVER re-do completed actions (CRITICAL)\n"
    "- BEFORE narrating, scan the `## Completed actions` list AND the current `object_state` /\n"
    "  `inventory` / `known_facts`. If the player's action targets something that is ALREADY in the\n"
    "  requested state — herbs already brewed, lantern already focused, rope already rigged, an item\n"
    "  already in inventory, an objective already complete — you MUST respond with:\n"
    "    * `success: true`, `delta: {}` (empty), and a SHORT one-sentence narration that REDIRECTS the\n"
    "      player to the next useful step.\n"
    "    * Example: action `USE herbs on vial` when `object_state.herbs == 'brewed'` → narrate\n"
    "      \"The vial already holds the amber draught — you brewed it earlier. Hal still snores; the\n"
    "      next step is to get the draught into his mug.\"\n"
    "- NEVER re-narrate the original success. NEVER duplicate the original delta. NEVER add the same\n"
    "  fact to `known_facts_add` twice.\n"
    "\n## Narration ↔ delta consistency (CRITICAL)\n"
    "- If your narration describes a NEW change to the world — an item created, taken, consumed, moved,\n"
    "  combined; an NPC's state shifting; a door opening; a location changing — your `delta` MUST encode\n"
    "  that exact change with the appropriate fields (`inventory_add`, `object_state`, `npc_state`,\n"
    "  `discovered_items`, etc.). Narration without a matching delta is a CONTRACT VIOLATION.\n"
    "- If `success` is true your delta MUST contain at least one substantive field beyond\n"
    "  `time_advance_min` / `alarm_delta`. Time and alarm alone are not enough to justify a success.\n"
    "- If you cannot justify a substantive delta, set `success: false` instead and describe the failure.\n"
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
        *,
        correction: str | None = None,
    ) -> dict[str, Any]:
        prompt = self._build_user_prompt(world, action, history)
        if correction:
            prompt += (
                "\n\n## CORRECTION REQUIRED\n"
                f"{correction}\n"
                "Re-emit a corrected JSON object now. No prose, no apologies \u2014 just the corrected JSON."
            )
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
        # If the player's action matches a puzzle trigger, surface its formal
        # preconditions / effects as an unmissable instruction. This is the
        # corpus-grounded source of truth \u2014 the GM must respect it.
        triggered = find_triggered_puzzle(
            self.clues, verb=action.verb, target=action.target, args=action.args, scope=scope,
        )
        if triggered:
            unmet = check_preconditions(triggered, world)
            sections.append("\n## Triggered puzzle (FORMAL PRECONDITIONS \u2014 obey strictly)")
            sections.append(f"- **{triggered.get('title') or triggered['id']}**")
            sections.append(f"- contract: {format_precondition_brief(triggered)}")
            if unmet:
                sections.append("- UNMET preconditions for this attempt:")
                for u in unmet:
                    sections.append(f"  * {u}")
                sections.append(
                    "- Therefore: `success: false`. Describe the honest failure (the rope is not "
                    "yet rigged; the draught is not yet brewed; the keys are not yet in hand). "
                    "Add a small `time_advance_min` and optionally `alarm_delta` as cost. Do NOT "
                    "grant the puzzle's effects."
                )
            else:
                sections.append(
                    "- All preconditions are MET. You MUST emit `success: true` AND include the "
                    "declared effects in your `delta` exactly as specified above."
                )
        # Completed actions — the durable, deterministic anti-repeat ledger.
        completed = world.get("completed_actions") or []
        sections.append("\n## Completed actions (DO NOT RE-DO — idempotency)")
        if completed:
            for entry in completed[-12:]:
                args = f" on={entry['on']}" if entry.get("on") else ""
                sections.append(
                    f"- t{entry.get('tick','?')}: {entry.get('verb','?')} {entry.get('target','')}{args} → {entry.get('summary','')}"
                )
        else:
            sections.append("- (none yet)")

        # Recent player actions (for stall detection).
        recent_actions = [ev for ev in history if ev.get("kind") == "player_action"][-4:]
        if recent_actions:
            sections.append("\n## Player's recent actions (for stall detection)")
            for ev in recent_actions:
                a = ev.get("payload", {}).get("action", {}) or {}
                sections.append(
                    f"- t{ev['tick']}: {a.get('verb','?')} {a.get('target','') or ''} {a.get('args','') or ''}".rstrip()
                )

        sections.append("\n## Recent narration & events (your own words — do NOT contradict)")
        for ev in history[-16:]:
            kind = ev.get("kind")
            payload = ev.get("payload") or {}
            if kind == "gm_narration":
                text = (payload.get("text") or "").strip()
                sections.append(f"- t{ev['tick']} [gm] narration: {text[:240]}")
            elif kind == "gm_state_delta":
                notes = payload.get("notes") or []
                if notes:
                    sections.append(f"- t{ev['tick']} [gm] delta: {'; '.join(notes)[:240]}")
            elif kind == "player_action":
                a = payload.get("action") or {}
                sections.append(
                    f"- t{ev['tick']} [mira] action: {a.get('verb','?')} {a.get('target','')}".rstrip()
                )
            elif kind == "player_say":
                sections.append(f"- t{ev['tick']} [mira] say: {(payload.get('text') or '')[:160]}")
            elif kind == "system_hint":
                sections.append(f"- t{ev['tick']} [system] hint: {(payload.get('text') or '')[:200]}")
            elif kind == "reflection":
                sections.append(f"- t{ev['tick']} [system] reflection: {(payload.get('summary') or '')[:200]}")
        sections.append("\n## Your response")
        sections.append(
            "Return the JSON adjudication only. Be faithful to the clues above; do not invent new world facts. "
            "If the player's action is already complete per the `Completed actions` list or current state, "
            "emit `success: true` with an EMPTY `delta` and redirect them to the next step. "
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
