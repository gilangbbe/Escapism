"""LLM client abstractions."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class LLMClient(ABC):
    name: str = "abstract"

    @abstractmethod
    def chat(self, messages: Iterable[Message], *, json_mode: bool = False) -> str: ...
