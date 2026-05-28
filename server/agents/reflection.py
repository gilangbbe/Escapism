"""Reflection step: periodically compress recent narrative events into a
small set of durable `known_facts` and one summary episode.

Runs every ``REFLECTION_EVERY`` ticks. Uses the GM's LLM (it has the
authority/voice) to produce structured JSON the world can merge.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..llm import LLMClient, Message
from ..memory.episodic import Episode, EpisodicMemory
from ..agents.protocol import _extract_first_json


REFLECTION_SCHEMA = {
    "summary": "one paragraph, second person, condensing the last block of events",
    "new_facts": "list of <=3 short sentences worth remembering (deduplicated against existing known_facts)",
}

_SYSTEM = (
    "You are the narrative memory of *The Last Voyage of the Black Vesper*. "
    "Compress the recent events into a tight summary and at most three new lasting facts. "
    "Do not invent anything not present in the events. Return JSON only:\n"
    f"{json.dumps(REFLECTION_SCHEMA, indent=2)}"
)


@dataclass
class Reflector:
    llm: LLMClient
    episodic: EpisodicMemory

    def reflect(
        self,
        *,
        tick: int,
        world: dict[str, Any],
        recent_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Produce a summary + new_facts JSON. Returns ``{}`` on failure."""
        prompt = self._build_prompt(world, recent_events)
        try:
            raw = self.llm.chat(
                [Message("system", _SYSTEM), Message("user", prompt)],
                json_mode=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[reflector] LLM call failed: {exc}")
            return {}
        payload = _extract_first_json(raw) or {}
        summary = str(payload.get("summary") or "").strip()
        new_facts = [
            str(f).strip()
            for f in (payload.get("new_facts") or [])
            if isinstance(f, str) and f.strip()
        ][:3]
        if not summary and not new_facts:
            return {}
        # Compact episodic memory: replace older raw episodes with the summary.
        if summary:
            self.episodic.compact(
                before_tick=tick - 1,
                replacement=Episode(
                    tick=tick, kind="reflection", text=summary, score_hint=2.0
                ),
            )
        return {"summary": summary, "new_facts": new_facts}

    @staticmethod
    def _build_prompt(world: dict[str, Any], events: list[dict[str, Any]]) -> str:
        existing = world.get("known_facts") or []
        existing_lines = [f"- {f}" for f in existing[-12:]] or ["- (none yet)"]
        lines = [
            "## World snapshot (key fields)",
            json.dumps({
                "tick": world.get("tick"),
                "location": world.get("current_location"),
                "scene_id": world.get("scene_id"),
                "objectives": world.get("objectives"),
                "inventory": world.get("inventory"),
            }, indent=2),
            "",
            "## Existing known facts (DO NOT REPEAT)",
            *existing_lines,
            "",
            "## Recent events",
        ]
        for ev in events[-12:]:
            payload = ev.get("payload") or {}
            text = payload.get("text") or json.dumps(payload)[:200]
            lines.append(f"- t{ev['tick']} [{ev['actor']}] {ev['kind']}: {text[:240]}")
        lines.append("\nReturn JSON only.")
        return "\n".join(lines)
