"""Append-only JSONL event log + helper to build a Run record."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def now_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def make_event(tick: int, kind: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"tick": tick, "ts": now_ts(), "kind": kind, "actor": actor, "payload": payload}


@dataclass
class RunStore:
    log_path: Path
    snapshot_path: Path
    events: list[dict[str, Any]] = field(default_factory=list)

    def append(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        with self.log_path.open("a") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    def write_snapshot(self, world: dict[str, Any]) -> None:
        self.snapshot_path.write_text(json.dumps(world, indent=2, ensure_ascii=False))
