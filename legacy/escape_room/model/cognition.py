"""Cognitive loop: Perceive → Recall → Deliberate (LLM) → Act → Reflect.

`LLMAgent` is the user-facing object. It owns a `Persona`, three memory
subsystems, and a reference to the world ontology / state. On each turn
the loop:

1. **Perceive** — pull a structured perception from `WorldState`.
2. **Recall** — gather relevant items from working / episodic / semantic
   memory.
3. **Deliberate** — build a prompt (persona + ontology + map +
   memories + recent chat) and call the LLM, which returns a JSON
   action.
4. **Act** — parse + validate JSON, hand the `Action` to
   `ActionValidator`, capture the result.
5. **Reflect** — write the perception, action, and result into
   episodic memory; update semantic facts.

The loop deliberately treats the LLM as a black box that *must* return
the JSON schema below. If the model deviates, we fall back to WAIT and
log the parse failure for debugging.

LLM response schema (JSON):
{
  "thought": "private reasoning",
  "say":     "what to broadcast in the group chat (may be empty)",
  "action":  {"verb": "MOVE|PICKUP|USE|EXAMINE|SAY|WAIT", "args": {...}}
}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..environment import (
    Action,
    ActionResult,
    ActionValidator,
    Ontology,
    PuzzleEngine,
    WorldState,
)
from ..environment.ontology import ObjectType
from ..environment.state import DIRECTIONS
from ..llm import LLMClient, Message
from ..memory import EpisodicMemory, SemanticMemory, WorkingMemory
from .persona import Persona


@dataclass
class TurnRecord:
    """Everything produced by one cognitive cycle. Renderers consume this."""

    tick: int
    agent_id: str
    persona_name: str
    thought: str
    say: str
    action: Action
    result: ActionResult
    raw_llm: str = ""


@dataclass
class LLMAgent:
    persona: Persona
    llm: LLMClient
    agent_id: str
    working: WorkingMemory = field(default_factory=WorkingMemory)
    episodic: EpisodicMemory = field(default_factory=EpisodicMemory)
    semantic: SemanticMemory = field(default_factory=SemanticMemory)

    def seed_world_rules(self) -> None:
        self.semantic.add_rule("Walls (#) block movement.")
        self.semantic.add_rule("Locked doors block movement until unlocked.")
        self.semantic.add_rule("Use a key on a door (USE item=key target=door) while adjacent to unlock it.")
        self.semantic.add_rule("Pick up an object only when standing on its tile.")


class CognitiveLoop:
    """Drives a single agent through one tick."""

    def __init__(
        self,
        agent: LLMAgent,
        world: WorldState,
        ontology: Ontology,
        validator: ActionValidator,
        puzzles: PuzzleEngine,
        chat_history: List[Tuple[str, str]],  # (speaker, text)
    ) -> None:
        self.agent = agent
        self.world = world
        self.ontology = ontology
        self.validator = validator
        self.puzzles = puzzles
        self.chat_history = chat_history

    # ---------- one tick ----------

    def step(self, tick: int) -> TurnRecord:
        perception = self._perceive(tick)
        recalled = self._recall()
        messages = self._build_prompt(tick, perception, recalled)
        raw = self.agent.llm.chat(messages, json_mode=True)
        parsed = self._parse(raw)
        action = self._build_action(parsed)
        result = self.validator.apply(action)
        self._reflect(tick, perception, action, result, parsed)
        return TurnRecord(
            tick=tick,
            agent_id=self.agent.agent_id,
            persona_name=self.agent.persona.name,
            thought=parsed.get("thought", ""),
            say=parsed.get("say", ""),
            action=action,
            result=result,
            raw_llm=raw,
        )

    # ---------- 1. perceive ----------

    def _perceive(self, tick: int) -> Dict:
        perception = self.world.perceive(self.agent.agent_id, radius=2)
        self.agent.working.last_perception = perception
        # Promote any newly-seen objects into semantic memory.
        for o in perception["visible_objects"]:
            key = f"{o['type']}:{o['id']}"
            self.agent.semantic.assert_fact(key, f"at position {tuple(o['position'])}, props={o['properties']}")
        self.agent.episodic.record(
            tick=tick,
            kind="perceive",
            content=f"At {tuple(perception['position'])}; sees {[o['id'] for o in perception['visible_objects']]}.",
            tags=["perceive"],
        )
        return perception

    # ---------- 2. recall ----------

    def _recall(self) -> Dict[str, object]:
        return {
            "working": self.agent.working.snapshot(),
            "recent_events": [
                f"t={e.tick} [{e.kind}] {e.content}"
                for e in self.agent.episodic.recall_recent(k=6)
            ],
            "semantic": self.agent.semantic.describe(),
        }

    # ---------- 3. deliberate ----------

    def _build_prompt(self, tick: int, perception: Dict, recalled: Dict[str, object]) -> List[Message]:
        sys = [
            self.agent.persona.system_preamble(),
            "",
            "You are an embodied agent in a text-based escape room.",
            "Respond with STRICT JSON only matching this schema:",
            '{ "thought": str, "say": str, "action": { "verb": str, "args": object } }',
            "",
            "Available verbs:",
            self.ontology.describe_for_prompt(),
            "",
            "Active puzzles:",
            self.puzzles.describe_for_prompt(),
            "",
            "Rules:",
            "- Always pick exactly ONE action per turn.",
            "- Direction values for MOVE must be one of: UP, DOWN, LEFT, RIGHT.",
            "- Use object_id strings exactly as they appear in perception (e.g. 'key-1', 'door-1').",
            "- 'say' is broadcast in the group chat and visible to everyone.",
            "- Keep 'thought' under 25 words.",
        ]
        usr = [
            f"Tick: {tick}",
            "",
            "MAP (god's-eye view; A = you, K = key, D = locked door, O = unlocked door, # = wall):",
            "<<<MAP>>>",
            self._render_map(),
            "<<<END_MAP>>>",
            "",
            f"Your position: {tuple(perception['position'])}",
            f"Inventory: [{', '.join(perception['inventory']) or ''}]",
            f"Objects on your tile: {perception['objects_here']}",
            *self._object_location_hints(),
            f"Visible objects: {json.dumps(perception['visible_objects'])}",
            f"Adjacent tiles: {json.dumps(perception['neighbours'])}",
            "",
            "Recent memory (episodic, most recent last):",
            *[f"  {line}" for line in recalled["recent_events"]],  # type: ignore[index]
            "",
            "Semantic memory:",
            str(recalled["semantic"]),
            "",
            "Working memory:",
            json.dumps(recalled["working"]),
            "",
            "Recent group chat:",
            *[f"  {spk}: {txt}" for spk, txt in self.chat_history[-6:]],
            "",
            "Decide your next action now. Reply with JSON only.",
        ]
        return [
            Message(role="system", content="\n".join(sys)),
            Message(role="user", content="\n".join(usr)),
        ]

    # ---------- 4. parse + build action ----------

    @staticmethod
    def _parse(raw: str) -> Dict:
        # Tolerate stray prose around the JSON object.
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return {"thought": "(no JSON in reply)", "say": "", "action": {"verb": "WAIT", "args": {}}}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {
                "thought": "(invalid JSON; defaulting to WAIT)",
                "say": "",
                "action": {"verb": "WAIT", "args": {}},
            }

    def _build_action(self, parsed: Dict) -> Action:
        act = parsed.get("action") or {}
        verb = str(act.get("verb", "WAIT")).upper()
        args = act.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        # Light normalisation
        if verb == "MOVE" and "direction" in args:
            args["direction"] = str(args["direction"]).upper()
        return Action(
            actor_id=self.agent.agent_id,
            verb=verb,
            args=args,
            thought=str(parsed.get("thought", "")),
            say=str(parsed.get("say", "")),
        )

    # ---------- 5. reflect ----------

    def _reflect(
        self,
        tick: int,
        perception: Dict,
        action: Action,
        result: ActionResult,
        parsed: Dict,
    ) -> None:
        self.agent.working.last_action_summary = result.summary
        self.agent.working.note(f"t={tick} {action.verb} -> {'ok' if result.ok else 'fail'}")
        self.agent.episodic.record(
            tick=tick,
            kind="action",
            content=f"{action.verb}({action.args}) -> {result.summary}",
            tags=["action", action.verb.lower()] + (["ok"] if result.ok else ["fail"]),
        )
        # Promote useful observations to semantic facts.
        for effect in result.side_effects:
            self.agent.semantic.assert_fact(f"event:{tick}:{effect}", result.summary)

    # ---------- map rendering for the prompt ----------

    def _object_location_hints(self) -> List[str]:
        """Authoritative one-liners about important objects. Cheap for the LLM and the mock."""
        hints: List[str] = []
        for obj in self.world.objects.values():
            r, c = obj.position
            where = "in an agent's inventory" if r < 0 else f"{(r, c)}"
            extra = ""
            if obj.type == ObjectType.DOOR:
                extra = " [locked]" if obj.properties.get("locked", True) else " [unlocked]"
            hints.append(f"{obj.type.value.capitalize()} '{obj.obj_id}' location: {where}{extra}")
        return hints

    def _render_map(self) -> str:
        out: List[List[str]] = []
        for r in range(self.world.height):
            row: List[str] = []
            for c in range(self.world.width):
                tile = self.world.tile_at((r, c))
                ch = "#" if tile.value == "#" else "."
                row.append(ch)
            out.append(row)
        # Overlay objects (door uses K/D/O depending on state).
        for obj in self.world.objects.values():
            r, c = obj.position
            if r < 0:  # picked up
                continue
            out[r][c] = obj.glyph
        # Overlay agents.
        for body in self.world.bodies.values():
            r, c = body.position
            base = out[r][c]
            out[r][c] = "@" if base in ("D", "O") else "A"
        return "\n".join(" ".join(row) for row in out)
