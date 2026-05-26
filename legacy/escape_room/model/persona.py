"""Persona: the agent's identity and stable disposition.

A persona is fed verbatim into the LLM system prompt. Keep it short and
behavioural — it sets *how* the agent thinks, not *what it currently
knows* (that's memory).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Persona:
    name: str
    role: str = "explorer"
    goals: List[str] = field(default_factory=list)
    style: str = "concise, curious, cooperative"
    backstory: str = ""

    def system_preamble(self) -> str:
        goals = "\n".join(f"  - {g}" for g in self.goals) or "  - (none specified)"
        return (
            f"You are {self.name}, a {self.role}.\n"
            f"Communication style: {self.style}.\n"
            f"Backstory: {self.backstory or '(none)'}\n"
            f"Your goals:\n{goals}"
        )


def default_solo_persona() -> Persona:
    return Persona(
        name="Echo",
        role="lone escapee",
        goals=[
            "Escape the room.",
            "Reason out loud so observers can follow your thinking.",
        ],
        style="concise, methodical, narrates intent in one short sentence",
        backstory="You woke up in a strange room with no memory of how you got here.",
    )
