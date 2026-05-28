"""World state model: a single mutable snapshot the GM is allowed to edit."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class WorldState:
    data: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "WorldState":
        return cls(json.loads(path.read_text()))

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.data)

    # ------------------------------------------------------------------ accessors
    @property
    def tick(self) -> int:
        return int(self.data.get("tick", 0))

    @property
    def inventory(self) -> list[str]:
        return list(self.data.get("inventory", []))

    @property
    def alarm(self) -> int:
        return int(self.data.get("alarm_meter", 0))

    @property
    def game_over(self) -> str | None:
        return self.data.get("game_over")

    # ------------------------------------------------------------------ mutators
    def next_tick(self) -> int:
        self.data["tick"] = self.tick + 1
        return self.data["tick"]

    def record_completed_action(
        self,
        *,
        verb: str,
        target: str,
        args: dict[str, Any] | None,
        summary: str,
    ) -> None:
        """Append an entry to ``completed_actions``. Idempotent on (verb, target, on)."""
        log = self.data.setdefault("completed_actions", [])
        on = ""
        if isinstance(args, dict):
            on = str(args.get("on") or args.get("b") or args.get("location") or "").strip()
        key = (verb.upper(), target, on)
        for entry in log:
            if (
                entry.get("verb", "").upper() == key[0]
                and entry.get("target", "") == key[1]
                and entry.get("on", "") == key[2]
            ):
                return  # already logged
        log.append({
            "tick": self.tick,
            "verb": verb.upper(),
            "target": target,
            "on": on,
            "summary": summary,
        })

    def find_completed_action(
        self,
        *,
        verb: str,
        target: str,
        args: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Return a completed-action entry matching this (verb, target, on), else None."""
        on = ""
        if isinstance(args, dict):
            on = str(args.get("on") or args.get("b") or args.get("location") or "").strip()
        log = self.data.get("completed_actions") or []
        for entry in log:
            if (
                entry.get("verb", "").upper() == verb.upper()
                and entry.get("target", "") == target
                and entry.get("on", "") == on
            ):
                return entry
        return None

    def apply_delta(self, delta: dict[str, Any]) -> list[str]:
        """Apply a structured delta from the GM. Returns list of human-readable change notes."""
        notes: list[str] = []
        if not isinstance(delta, dict):
            return notes

        for key, value in (delta.get("set") or {}).items():
            self.data[key] = value
            notes.append(f"set {key} = {value}")

        for item in delta.get("inventory_add") or []:
            inv = self.data.setdefault("inventory", [])
            if item not in inv:
                inv.append(item)
                notes.append(f"+inv {item}")

        for item in delta.get("inventory_remove") or []:
            inv = self.data.setdefault("inventory", [])
            if item in inv:
                inv.remove(item)
                notes.append(f"-inv {item}")

        for name, state in (delta.get("npc_state") or {}).items():
            self.data.setdefault("npc_state", {})[name] = state
            notes.append(f"npc {name}={state}")

        for name, state in (delta.get("object_state") or {}).items():
            self.data.setdefault("object_state", {})[name] = state
            notes.append(f"obj {name}={state}")

        for item in delta.get("discovered_items") or []:
            disc = self.data.setdefault("discovered_items", [])
            if item not in disc:
                disc.append(item)
            hidden = self.data.setdefault("hidden_items", [])
            if item in hidden:
                hidden.remove(item)
            notes.append(f"discovered {item}")

        for fact in delta.get("known_facts_add") or []:
            facts = self.data.setdefault("known_facts", [])
            if fact not in facts:
                facts.append(fact)
                notes.append(f"learned: {fact}")

        for oid, status in (delta.get("objectives") or {}).items():
            self.data.setdefault("objectives", {})[oid] = status
            notes.append(f"objective {oid}={status}")

        if "alarm_delta" in delta:
            self.data["alarm_meter"] = max(0, self.alarm + int(delta["alarm_delta"]))
            notes.append(f"alarm={self.data['alarm_meter']}")

        if "time_advance_min" in delta:
            mins = int(delta["time_advance_min"])
            self.data["minutes_until_port_royal"] = max(
                0, int(self.data.get("minutes_until_port_royal", 90)) - mins
            )
            self.data["in_game_time"] = _advance_clock(self.data.get("in_game_time", "04:30"), mins)
            notes.append(f"time +{mins}min -> {self.data['in_game_time']}")

        if "scene_id" in delta:
            self.data["scene_id"] = delta["scene_id"]
            notes.append(f"scene={delta['scene_id']}")

        if "current_location" in delta:
            self.data["current_location"] = delta["current_location"]
            notes.append(f"location={delta['current_location']}")

        if "game_over" in delta:
            self.data["game_over"] = delta["game_over"]
            notes.append(f"game_over={delta['game_over']}")

        # ----- Automatic fail-state triggers -----
        # These fire regardless of what the GM emitted, so the simulation cannot
        # silently exceed the alarm cap or sail past Port Royal without ending.
        if not self.data.get("game_over"):
            alarm_max = int(self.data.get("alarm_max", 10))
            if self.alarm >= alarm_max:
                self.data["game_over"] = "alarm_max"
                self.data["auto_game_over"] = "alarm_max"
                notes.append(f"!! alarm hit {alarm_max} -> Hal wakes, you are caught")
            elif int(self.data.get("minutes_until_port_royal", 1)) <= 0:
                self.data["game_over"] = "port_royal_reached"
                self.data["auto_game_over"] = "port_royal_reached"
                notes.append("!! time is up -> the brig moors at Port Royal")

        return notes


def _advance_clock(hhmm: str, minutes: int) -> str:
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except Exception:
        return hhmm
    total = (h * 60 + m + minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


_SUBSTANTIVE_KEYS = (
    "inventory_add", "inventory_remove",
    "npc_state", "object_state",
    "discovered_items", "known_facts_add",
    "objectives", "scene_id", "current_location",
    "game_over", "set",
)


def delta_is_substantive(delta: dict[str, Any] | None) -> bool:
    """True iff the delta would actually mutate world facts (not just time/alarm).

    A GM that narrates success but emits only ``time_advance_min`` / ``alarm_delta``
    has effectively lied to the player \u2014 the world won't reflect the claim.
    """
    if not isinstance(delta, dict):
        return False
    for key in _SUBSTANTIVE_KEYS:
        value = delta.get(key)
        if isinstance(value, (list, dict)) and len(value) > 0:
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False
