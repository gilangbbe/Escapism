"""Semantic memory: distilled, generalised beliefs about the world.

Two stores:
- `facts`: ground truths the agent has confirmed (e.g. "door-1 is at (5,8)").
- `rules`: general world knowledge supplied by the persona / learned later
  (e.g. "locked doors require keys").

For the PoC writes happen explicitly from the cognitive loop after
successful perceptions or actions. A future version can run a
reflection step that compresses episodic memory into new facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class SemanticMemory:
    facts: Dict[str, str] = field(default_factory=dict)
    rules: List[str] = field(default_factory=list)

    def assert_fact(self, key: str, value: str) -> None:
        self.facts[key] = value

    def retract_fact(self, key: str) -> None:
        self.facts.pop(key, None)

    def add_rule(self, rule: str) -> None:
        if rule not in self.rules:
            self.rules.append(rule)

    def describe(self) -> str:
        facts = "\n".join(f"- {k}: {v}" for k, v in self.facts.items()) or "- (none yet)"
        rules = "\n".join(f"- {r}" for r in self.rules) or "- (none yet)"
        return f"Known facts:\n{facts}\nWorld rules:\n{rules}"
