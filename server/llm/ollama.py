"""Ollama HTTP client (stdlib only)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Iterable

from ..config import settings
from .base import LLMClient, Message


class OllamaClient(LLMClient):
    name = "ollama"

    def __init__(self, model: str, *, temperature: float | None = None, host: str | None = None, timeout: int = 180):
        self.model = model
        self.host = (host or settings.ollama_host).rstrip("/")
        self.temperature = settings.temperature if temperature is None else temperature
        self.timeout = timeout

    def chat(self, messages: Iterable[Message], *, json_mode: bool = False) -> str:
        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        if json_mode:
            payload["format"] = "json"
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Ollama request failed ({self.host}): {exc}") from exc
        return body.get("message", {}).get("content", "")
