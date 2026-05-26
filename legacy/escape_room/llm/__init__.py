"""LLM client abstraction + concrete backends."""

from .base import LLMClient, Message
from .mock import MockLLMClient
from .ollama import OllamaClient

__all__ = ["LLMClient", "Message", "MockLLMClient", "OllamaClient"]
