"""Simulation orchestrator: alternates player turn → GM adjudication → world update,
emitting events through an injectable async broadcaster."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from .agents import GameMasterAgent, PlayerAgent
from .agents.reflection import Reflector
from .agents.salty import Salty
from .config import settings, DATA_DIR, RUNS_DIR
from .llm import (
    LLMClient,
    MockGameMasterClient,
    MockPlayerClient,
    OllamaClient,
)
from .memory import ClueStore, EpisodicMemory
from .world import RunStore, WorldState, make_event, now_ts


Broadcaster = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class Simulation:
    world: WorldState
    player: PlayerAgent
    gm: GameMasterAgent
    run: RunStore
    episodic: EpisodicMemory
    salty: Salty
    reflector: Reflector | None = None
    broadcast: Broadcaster | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    finished: bool = False

    # --------------------------------------------------------------- factory
    @classmethod
    def build(cls, *, broadcast: Broadcaster | None = None) -> "Simulation":
        world = WorldState.load(DATA_DIR / "world_initial.json")
        clues = ClueStore(DATA_DIR / "game.jsonl")
        player_llm, gm_llm = _build_llms()
        episodic = EpisodicMemory()
        player = PlayerAgent(llm=player_llm, clues=clues, episodic=episodic)
        gm = GameMasterAgent(llm=gm_llm, clues=clues)
        salty = Salty(clues=clues)
        reflector = (
            Reflector(llm=gm_llm, episodic=episodic)
            if settings.reflect_every > 0 else None
        )

        ts = now_ts().replace(":", "-")
        run = RunStore(
            log_path=RUNS_DIR / f"{ts}.events.jsonl",
            snapshot_path=RUNS_DIR / f"{ts}.world.json",
        )
        return cls(
            world=world, player=player, gm=gm, run=run,
            episodic=episodic, salty=salty, reflector=reflector,
            broadcast=broadcast,
        )

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
            },
            "intent": action.intent,
            "plan": action.plan or [],
        }))

        # 1a. Persist BDI in the world.
        self._update_bdi(action)

        # 1b. Loop detector — escalates Salty tier hints when stuck.
        await self._maybe_emit_loop_hint(tick, action)

        # 2. GM adjudicates.
        gm_response = self.gm.adjudicate(self.world.snapshot(), action, self.events)
        narration = gm_response.get("narration") or "(The GM is silent.)"
        delta = gm_response.get("delta") or {}
        await self._emit(make_event(tick, "gm_narration", "gm", {
            "text": narration,
            "success": gm_response.get("success", True),
        }))
        # Episodic ingest: narration is a high-value episode.
        self.episodic.add(tick, "narration", narration, score_hint=1.0)

        # 3. Apply delta.
        notes = self.world.apply_delta(delta)
        if notes:
            await self._emit(make_event(tick, "gm_state_delta", "gm", {
                "delta": delta,
                "notes": notes,
                "world": self.world.snapshot(),
            }))
            self.episodic.add(tick, "delta", " | ".join(notes), score_hint=0.6)

        # 3b. Auto fail-state narration.
        auto = self.world.data.pop("auto_game_over", None)
        if auto:
            text = _auto_fail_narration(auto, self.world.snapshot())
            await self._emit(make_event(tick, "gm_narration", "gm", {
                "text": text, "success": False, "auto": auto,
            }))

        # 4. Periodic reflection — compress episodic memory and add lasting facts.
        if (
            self.reflector is not None
            and not self.world.game_over
            and settings.reflect_every > 0
            and tick > 0
            and tick % settings.reflect_every == 0
        ):
            await self._reflect(tick)

    async def _maybe_emit_loop_hint(self, tick: int, action: Any) -> None:
        key = (action.verb or "").upper(), (action.target or "")
        recent = [
            ev for ev in self.events
            if ev.get("kind") == "player_action"
        ][-6:]  # look back a bit further for tier escalation
        keys = []
        for ev in recent:
            a = ev.get("payload", {}).get("action", {}) or {}
            keys.append(((a.get("verb") or "").upper(), a.get("target") or ""))
        # Count trailing repetitions of the current key.
        streak = 0
        for k in reversed(keys):
            if k == key:
                streak += 1
            else:
                break
        step = max(1, settings.salty_tier_step)
        if streak < step:
            return
        tier = min(3, 1 + (streak - step) // step + 1)
        # Avoid emitting the same tier twice for the same streak.
        last_hint = next(
            (ev for ev in reversed(self.events) if ev.get("kind") == "system_hint"),
            None,
        )
        if last_hint and last_hint.get("payload", {}).get("tier") == tier \
           and tick - last_hint.get("tick", 0) < step:
            return
        text = self.salty.hint_for(tier=tier, world=self.world.snapshot(), action_key=key)
        await self._emit(make_event(tick, "system_hint", "system", {
            "text": text, "tier": tier, "streak": streak,
            "verb": key[0], "target": key[1],
        }))
        # Also feed into episodic memory — hints are sticky.
        self.episodic.add(tick, "hint", text, score_hint=1.5)

    def _update_bdi(self, action: Any) -> None:
        bdi = self.world.data.setdefault("player_bdi", {})
        new_intent = (action.intent or "").strip()
        prev_intent = bdi.get("current_intent") or ""
        if new_intent and new_intent != prev_intent:
            bdi["current_intent"] = new_intent
            bdi["intent_age"] = 1
        elif new_intent:
            bdi["intent_age"] = int(bdi.get("intent_age") or 0) + 1
        if action.plan:
            bdi["current_plan"] = list(action.plan)

    async def _reflect(self, tick: int) -> None:
        try:
            result = self.reflector.reflect(
                tick=tick, world=self.world.snapshot(), recent_events=self.events
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[simulation] reflection failed: {exc}")
            return
        if not result:
            return
        # Merge any new facts into the world.
        new_facts = result.get("new_facts") or []
        if new_facts:
            notes = self.world.apply_delta({"known_facts_add": new_facts})
            await self._emit(make_event(tick, "gm_state_delta", "gm", {
                "delta": {"known_facts_add": new_facts},
                "notes": notes,
                "world": self.world.snapshot(),
            }))
        await self._emit(make_event(tick, "reflection", "system", {
            "summary": result.get("summary", ""),
            "new_facts": new_facts,
        }))

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
