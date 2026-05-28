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
from ..memory import ClueStore, EpisodicMemory
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
    "\n## BDI (Belief / Desire / Intention) discipline\n"
    "- ALWAYS fill `intent` with the single immediate goal you are pursuing this very turn "
    "  (e.g. 'sedate Hal so the cell can be unlocked safely').\n"
    "- ALWAYS fill `plan` with 1-3 short, ordered next steps that would complete the current intent. "
    "  The first item of `plan` should describe the action you are about to take.\n"
    "- If the GM blocked your last action or revealed information that changes the plan, REVISE the "
    "  intent or plan accordingly. Never keep the same `intent` for more than 4 turns.\n"
    "\n## Anti-loop rules (CRITICAL)\n"
    "- NEVER repeat the same (verb, target) you used in your last 3 actions. Look at the 'Recent actions' "
    "  list below: if your last action was EXAMINE hal_keyring, do NOT EXAMINE hal_keyring again.\n"
    "- NEVER attempt anything listed in 'Actions you have ALREADY COMPLETED'. Those state changes "
    "  are permanent; the world reflects them already. Trying again wastes time and raises the alarm.\n"
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
    episodic: EpisodicMemory | None = None

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

        # BDI snapshot.
        active_objs = [oid for oid, s in (world.get("objectives") or {}).items() if s == "active"]
        beliefs = (world.get("known_facts") or [])[-8:]
        bdi = world.get("player_bdi") or {}
        current_intent = bdi.get("current_intent") or ""
        current_plan = bdi.get("current_plan") or []
        intent_age = int(bdi.get("intent_age") or 0)

        # Episodic recall (only if an episodic store is wired in).
        episodic_recall: list[str] = []
        if self.episodic is not None:
            query = " ".join([
                world.get("current_location", ""),
                current_intent,
                " ".join(active_objs),
            ])
            for ep in self.episodic.query(query, k=4, current_tick=int(world.get("tick", 0))):
                episodic_recall.append(f"[t{ep.tick} {ep.kind}] {ep.text[:200]}")

        belief_lines = [f"  * {b}" for b in beliefs] or ["  * (none yet)"]
        sections = [
            "## World snapshot",
            "```json",
            json.dumps(_world_view(world), indent=2),
            "```",
            "",
            "## BDI — your current Desires / Beliefs / Intentions",
            f"- Desires (active objectives): {', '.join(active_objs) or '(none)'}",
            "- Beliefs (recent known facts):",
            *belief_lines,
            f"- Current intent: {current_intent or '(none yet — set one this turn)'}"
            + (f" [age={intent_age} turns]" if current_intent else ""),
            f"- Current plan: {current_plan or '(none yet — propose one this turn)'}",
            "",
            "## Relevant clues (from your memory of the ship)",
        ]
        for doc in retrieved:
            sections.append(f"- **{doc.get('title') or doc['id']}** — {doc.get('text', '')}")

        if episodic_recall:
            sections.append("\n## From your memory of THIS voyage (episodic)")
            for line in episodic_recall:
                sections.append(f"- {line}")

        sections.append("\n## Recent actions YOU have already taken (DO NOT REPEAT)")
        if recent_actions:
            for ev in recent_actions:
                a = ev.get("payload", {}).get("action", {})
                sections.append(
                    f"- t{ev['tick']}: {a.get('verb','?')} {a.get('target','') or ''} {a.get('args','') or ''}".rstrip()
                )
        else:
            sections.append("- (none yet)")

        # Completed actions \u2014 the durable, deterministic anti-repeat ledger.
        completed = world.get("completed_actions") or []
        sections.append("\n## Actions you have ALREADY COMPLETED (do NOT re-do these)")
        if completed:
            for entry in completed[-12:]:
                args = f" on={entry['on']}" if entry.get("on") else ""
                sections.append(
                    f"- t{entry.get('tick','?')}: {entry.get('verb','?')} {entry.get('target','')}{args} \u2192 {entry.get('summary','')}"
                )
        else:
            sections.append("- (none yet)")

        sections.append("\n## Recent narration / events")
        for ev in history[-12:]:
            kind = ev.get("kind")
            payload = ev.get("payload") or {}
            if kind == "gm_narration":
                sections.append(f"- t{ev['tick']} [gm] narration: {(payload.get('text') or '')[:220]}")
            elif kind == "gm_state_delta":
                notes = payload.get("notes") or []
                if notes:
                    sections.append(f"- t{ev['tick']} [gm] delta: {'; '.join(notes)[:200]}")
            elif kind == "system_hint":
                sections.append(f"- t{ev['tick']} [system] hint: {(payload.get('text') or '')[:200]}")
            elif kind == "reflection":
                sections.append(f"- t{ev['tick']} [system] reflection: {(payload.get('summary') or '')[:200]}")

        if recent_hints:
            sections.append("\n## System hints (heed these)")
            for ev in recent_hints:
                sections.append(f"- {ev.get('payload', {}).get('text', '')}")

        sections.append("\n## Your next action")
        sections.append(
            "Pick a NEW action that advances an active objective. Always fill `intent` and `plan`. "
            "If your `current intent` has aged past 4 turns without progress, REVISE it. "
            "If the last GM narration revealed something, ACT on it now — do not re-examine. "
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
        "alarm_max",
        "inventory",
        "discovered_items",
        "known_facts",
        "npc_state",
        "object_state",
        "objectives",
        "scene_id",
    )
    return {k: world.get(k) for k in keep if k in world}
