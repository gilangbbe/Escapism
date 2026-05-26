"""Ollama backend (HTTP, stdlib only).

Talks to a local Ollama daemon at `http://localhost:11434/api/chat`.
Set `format="json"` so the model returns valid JSON for our action
protocol. Default model is `llama3.2`; override with the constructor
or the `OLLAMA_MODEL` env var.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import List

from .base import LLMClient, Message


class OllamaClient(LLMClient):
    name = "ollama"

    def __init__(
        self,
        model: str | None = None,
        host: str | None = None,
        timeout: float = 120.0,
        temperature: float = 0.2,
    ) -> None:
        self.model = model or os.environ.get("OLLAMA_MODEL", "llama3.2")
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self.timeout = timeout
        self.temperature = temperature

    def chat(self, messages: List[Message], *, json_mode: bool = False) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": self.temperature},
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if json_mode:
            payload["format"] = "json"

        url = f"{self.host}/api/chat"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Ollama request failed at {url}: {exc}. "
                "Is the Ollama daemon running? (`ollama serve`)"
            ) from exc

        data = json.loads(body)
        # /api/chat returns {"message": {"role": "assistant", "content": "..."}, ...}
        msg = data.get("message", {})
        return msg.get("content", "")
