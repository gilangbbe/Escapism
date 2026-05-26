"""Working memory: a small, volatile scratchpad for the current turn.

Holds the latest perception, the current plan/intent, and the last
action result. The cognitive loop overwrites these every tick — older
content is promoted to episodic memory before being discarded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class WorkingMemory:
    capacity: int = 7  # Miller's magic number; bounds the focus buffer
    focus: List[str] = field(default_factory=list)
    last_perception: Optional[Dict[str, Any]] = None
    current_plan: str = ""
    last_action_summary: str = ""

    def note(self, text: str) -> None:
        self.focus.append(text)
        if len(self.focus) > self.capacity:
            self.focus = self.focus[-self.capacity :]

    def clear_focus(self) -> None:
        self.focus.clear()

    def snapshot(self) -> Dict[str, Any]:
        return {
            "focus": list(self.focus),
            "current_plan": self.current_plan,
            "last_action_summary": self.last_action_summary,
        }
