"""Provider-agnostic LLM interface.

Every backend takes a list of `Message` and returns a string. JSON
formatting is the responsibility of the caller (the cognitive loop),
not the provider — except where the provider supports a native JSON
mode (Ollama: `format="json"`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Literal

Role = Literal["system", "user", "assistant"]


@dataclass
class Message:
    role: Role
    content: str


class LLMClient(ABC):
    name: str = "abstract"

    @abstractmethod
    def chat(self, messages: List[Message], *, json_mode: bool = False) -> str:
        """Send a conversation and return the assistant's reply as a string."""
        raise NotImplementedError
