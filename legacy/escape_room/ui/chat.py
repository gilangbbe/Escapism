"""Group-chat style ASCII renderer.

Renders each tick as a series of messenger-style chat bubbles:
- `world` bubble shows the current map snapshot.
- `system` bubble announces puzzles solved / escapes.
- agent bubble shows: persona avatar header, the agent's spoken line,
  a collapsed thought block, and the action it just took.
"""

from __future__ import annotations

import textwrap
from typing import Iterable, List

from ..environment import WorldState
from ..environment.ontology import ObjectType
from ..model.cognition import TurnRecord


BUBBLE_WIDTH = 64
INDENT_LEFT = "  "
INDENT_RIGHT = " " * 18  # right-aligned-ish for the agent's own turns


def _wrap(text: str, width: int) -> List[str]:
    if not text:
        return [""]
    out: List[str] = []
    for paragraph in text.splitlines() or [text]:
        wrapped = textwrap.wrap(paragraph, width=width) or [""]
        out.extend(wrapped)
    return out


def _bubble(speaker: str, lines: Iterable[str], *, align: str = "left", accent: str = "·") -> str:
    inner_width = BUBBLE_WIDTH - 4
    body_lines: List[str] = []
    for raw in lines:
        for w in _wrap(raw, inner_width):
            body_lines.append(f"│ {w.ljust(inner_width)} │")
    top = "┌" + "─" * (BUBBLE_WIDTH - 2) + "┐"
    header = f"│ {accent} {speaker}".ljust(BUBBLE_WIDTH - 1) + "│"
    sep = "├" + "─" * (BUBBLE_WIDTH - 2) + "┤"
    bot = "└" + "─" * (BUBBLE_WIDTH - 2) + "┘"
    indent = INDENT_RIGHT if align == "right" else INDENT_LEFT
    return "\n".join(indent + ln for ln in [top, header, sep, *body_lines, bot])


def _render_map(world: WorldState) -> str:
    rows: List[List[str]] = []
    for r in range(world.height):
        row: List[str] = []
        for c in range(world.width):
            row.append("#" if world.tile_at((r, c)).value == "#" else ".")
        rows.append(row)
    for obj in world.objects.values():
        r, c = obj.position
        if r < 0:
            continue
        rows[r][c] = obj.glyph
    for body in world.bodies.values():
        r, c = body.position
        base = rows[r][c]
        rows[r][c] = "@" if base in ("D", "O") else "A"
    return "\n".join(" ".join(row) for row in rows)


class GroupChatRenderer:
    """Stateless formatter; `Simulation` calls it once per tick."""

    def legend(self) -> str:
        return _bubble(
            "system",
            [
                "Escape Room PoC — single LLM agent",
                "Legend: A=you  K=key  D=locked door  O=open door",
                "        @=agent on door  #=wall  .=floor",
                "Each turn: Perceive → Recall → Deliberate (LLM) → Act → Reflect",
            ],
            accent="★",
        )

    def world_frame(self, world: WorldState, tick: int) -> str:
        body = [f"Tick {tick:02d} — room state:", "", *_render_map(world).splitlines()]
        return _bubble("world", body, accent="◌")

    def agent_turn(self, record: TurnRecord) -> str:
        verb = record.action.verb
        args = record.action.args
        arg_str = ", ".join(f"{k}={v}" for k, v in args.items()) if args else ""
        action_line = f"[action] {verb}({arg_str})  →  {'✓' if record.result.ok else '✗'} {record.result.summary}"
        lines: List[str] = []
        if record.say:
            lines.append(f"💬 {record.say}")
        if record.thought:
            lines.append(f"💭 {record.thought}")
        lines.append(action_line)
        speaker = f"{record.persona_name} ({record.agent_id}) — t={record.tick:02d}"
        return _bubble(speaker, lines, align="right", accent="◆")

    def system_event(self, text: str) -> str:
        return _bubble("system", [text], accent="★")
