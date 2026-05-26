"""Simulation orchestrator: alternates player turn → GM adjudication → world update,
emitting events through an injectable async broadcaster."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from .agents import GameMasterAgent, PlayerAgent
from .config import settings, DATA_DIR, RUNS_DIR
from .llm import (
    LLMClient,
    MockGameMasterClient,
    MockPlayerClient,
    OllamaClient,
)
from .memory import ClueStore
from .world import RunStore, WorldState, make_event, now_ts


Broadcaster = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class Simulation:
    world: WorldState
    player: PlayerAgent
    gm: GameMasterAgent
    run: RunStore
    broadcast: Broadcaster | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    finished: bool = False

    # --------------------------------------------------------------- factory
    @classmethod
    def build(cls, *, broadcast: Broadcaster | None = None) -> "Simulation":
        world = WorldState.load(DATA_DIR / "world_initial.json")
        clues = ClueStore(DATA_DIR / "game.jsonl")
        player_llm, gm_llm = _build_llms()
        player = PlayerAgent(llm=player_llm, clues=clues)
        gm = GameMasterAgent(llm=gm_llm, clues=clues)

        ts = now_ts().replace(":", "-")
        run = RunStore(
            log_path=RUNS_DIR / f"{ts}.events.jsonl",
            snapshot_path=RUNS_DIR / f"{ts}.world.json",
        )
        return cls(world=world, player=player, gm=gm, run=run, broadcast=broadcast)

    # --------------------------------------------------------------- driver
    async def run_loop(self) -> None:
        await self._emit(make_event(self.world.tick, "scene_start", "system", {
            "world": self.world.snapshot(),
            "message": (
                "You wake on the cell floor of the Black Vesper's brig. The others are still under "
                "Vane's drugged rum. Through the bars Hal sleeps at his desk. Dawn is in ninety minutes."
            ),
        }))

        for _ in range(settings.max_ticks):
            if self.finished:
                break
            await self._take_turn()
            if self.world.game_over:
                await self._emit(make_event(
                    self.world.tick, "game_over", "system", {"outcome": self.world.game_over}
                ))
                self.finished = True
                break
            if settings.tick_delay_seconds > 0:
                await asyncio.sleep(settings.tick_delay_seconds)

        self.run.write_snapshot(self.world.snapshot())

    async def _take_turn(self) -> None:
        tick = self.world.next_tick()

        # 1. Player decides.
        action = self.player.decide(self.world.snapshot(), self.events)
        if action.thought:
            await self._emit(make_event(tick, "player_thought", "mira", {"text": action.thought}))
        if action.say:
            await self._emit(make_event(tick, "player_say", "mira", {"text": action.say}))
        await self._emit(make_event(tick, "player_action", "mira", {
            "action": action.raw.get("action") or {
                "verb": action.verb, "target": action.target, "args": action.args
            }
        }))

        # 1b. Loop detector: if the same (verb, target) has just been repeated 3x,
        # inject a system hint that the player prompt will surface next turn.
        await self._maybe_emit_loop_hint(tick, action)

        # 2. GM adjudicates.
        gm_response = self.gm.adjudicate(self.world.snapshot(), action, self.events)
        narration = gm_response.get("narration") or "(The GM is silent.)"
        delta = gm_response.get("delta") or {}
        await self._emit(make_event(tick, "gm_narration", "gm", {
            "text": narration,
            "success": gm_response.get("success", True),
        }))

        # 3. Apply delta.
        notes = self.world.apply_delta(delta)
        if notes:
            await self._emit(make_event(tick, "gm_state_delta", "gm", {
                "delta": delta,
                "notes": notes,
                "world": self.world.snapshot(),
            }))

        # 3b. If an automatic fail-state fired (alarm maxed / time expired) and
        # the GM did not narrate it themselves, inject a closing narration so the
        # player and the chat UI both see WHY the game ended.
        auto = self.world.data.pop("auto_game_over", None)
        if auto:
            text = _auto_fail_narration(auto, self.world.snapshot())
            await self._emit(make_event(tick, "gm_narration", "gm", {
                "text": text, "success": False, "auto": auto,
            }))

    async def _maybe_emit_loop_hint(self, tick: int, action: Any) -> None:
        key = (action.verb or "").upper(), (action.target or "")
        recent = [
            ev for ev in self.events
            if ev.get("kind") == "player_action"
        ][-3:]
        if len(recent) < 3:
            return
        keys = []
        for ev in recent:
            a = ev.get("payload", {}).get("action", {}) or {}
            keys.append(((a.get("verb") or "").upper(), a.get("target") or ""))
        if not all(k == key for k in keys):
            return
        # Don't spam: only one hint per stuck streak.
        last_hint = next(
            (ev for ev in reversed(self.events) if ev.get("kind") == "system_hint"),
            None,
        )
        if last_hint and tick - last_hint.get("tick", 0) < 3:
            return
        verb, target = key
        msg = (
            f"You have repeated {verb} {target} three turns in a row with no visible change in the "
            f"world. That approach is a dead end. Pick a DIFFERENT verb (TAKE, USE, COMBINE, MOVE_TO, "
            f"WAIT) or a DIFFERENT target. Re-read your active objectives and inventory."
        )
        await self._emit(make_event(tick, "system_hint", "system", {"text": msg}))

    # --------------------------------------------------------------- helpers
    async def _emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        self.run.append(event)
        if self.broadcast:
            try:
                await self.broadcast(event)
            except Exception as exc:  # noqa: BLE001
                print(f"[simulation] broadcast failed: {exc}")


# ---------------------------------------------------------------------------
def _build_llms() -> tuple[LLMClient, LLMClient]:
    backend = settings.backend.lower()
    if backend == "mock":
        return MockPlayerClient(), MockGameMasterClient()
    if backend == "ollama":
        return (
            OllamaClient(settings.player_model),
            OllamaClient(settings.gm_model),
        )
    raise ValueError(f"Unknown LLM_BACKEND: {settings.backend}")


def _auto_fail_narration(kind: str, world: dict[str, Any]) -> str:
    if kind == "alarm_max":
        return (
            "A board groans under your heel and Hal's eyes snap open. He has his cutlass clear of the "
            "scabbard before you can move, and his bellow brings the watch boiling down the ladder. "
            "Hands seize you from behind. The brig door slams. Whatever you were going to do, you are "
            "doing it in chains now."
        )
    if kind == "port_royal_reached":
        loc = world.get("in_game_time", "06:00")
        return (
            f"At {loc} the anchor chain rattles out and the *Black Vesper* settles against the "
            "Port Royal mole. Boots on the deck above. British voices. Vane laughs once, somewhere "
            "forward, as the Navy comes down for you. The voyage is over and you are not free."
        )
    return f"The story ends abruptly: {kind}."
