"""Model layer: agent persona + cognitive loop that ties memory ↔ LLM ↔ environment."""

from .cognition import CognitiveLoop, LLMAgent
from .persona import Persona

__all__ = ["CognitiveLoop", "LLMAgent", "Persona"]
