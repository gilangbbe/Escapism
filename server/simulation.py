"""Simulation orchestrator: alternates player turn → GM adjudication → world update,
emitting events through an injectable async broadcaster."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from .agents import GameMasterAgent, PlayerAgent
from .agents.puzzle_validator import (
    check_preconditions,
    delta_grants_effect,
    find_triggered_puzzle,
)
from .agents.reflection import Reflector
from .agents.salty import Salty
from .config import settings, DATA_DIR, RUNS_DIR, scenario_dir
from .llm import (
    LLMClient,
    MockGameMasterClient,
    MockPlayerClient,
    OllamaClient,
)
from .memory import ClueStore, EpisodicMemory
from .world import RunStore, WorldState, delta_is_substantive, make_event, now_ts


Broadcaster = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class Simulation:
    world: WorldState
    player: PlayerAgent
    gm: GameMasterAgent
    run: RunStore
    episodic: EpisodicMemory
    salty: Salty
    clues: ClueStore | None = None
    reflector: Reflector | None = None
    broadcast: Broadcaster | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    finished: bool = False

    # --------------------------------------------------------------- factory
    @classmethod
    def build(cls, *, broadcast: Broadcaster | None = None) -> "Simulation":
        bundle = scenario_dir(settings.scenario)
        world = WorldState.load(bundle / "world_initial.json")
        clues = ClueStore(bundle / "game.jsonl")
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
            episodic=episodic, salty=salty, clues=clues, reflector=reflector,
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

        # 1c. Idempotency guard: if this exact (verb, target, on) is already in
        # the completed-actions ledger, short-circuit the GM call. The world is
        # already in the desired state; re-running the GM risks duplicate
        # narration / stale deltas (the "Mira brews herbs twice" bug).
        prior = self.world.find_completed_action(
            verb=action.verb, target=action.target, args=action.args
        )
        if prior is not None and action.verb in {"USE", "COMBINE", "TAKE", "MOVE_TO"}:
            redirect = (
                f"You already did that at tick {prior.get('tick','?')} "
                f"({prior.get('summary','no summary')}). The world reflects it already. "
                "Pick a different next step."
            )
            await self._emit(make_event(tick, "gm_narration", "gm", {
                "text": redirect, "success": True, "idempotent": True,
            }))
            self.episodic.add(tick, "hint", redirect, score_hint=1.5)
            # Skip GM, skip delta, skip reflection on this tick.
            return

        # 2. GM adjudicates. If the GM claims `success: true` but emits an
        # empty/non-substantive delta, re-prompt ONCE with a correction note
        # before falling back to forcing success=false.
        gm_response = self.gm.adjudicate(self.world.snapshot(), action, self.events)
        delta = gm_response.get("delta") or {}

        # 2a. Puzzle-precondition validation. If the player's action triggers a
        # puzzle and the GM granted any of its declared effects despite unmet
        # preconditions, REJECT and reprompt with a hard correction. This is
        # the corpus-grounded sanity check on top of the GM's prose.
        triggered = None
        if self.clues is not None:
            scope = f"act{self.world.data.get('act', 1)}"
            triggered = find_triggered_puzzle(
                self.clues, verb=action.verb, target=action.target,
                args=action.args, scope=scope,
            )
        if triggered is not None:
            unmet = check_preconditions(triggered, self.world.snapshot())
            if unmet and delta_grants_effect(delta, triggered):
                pre_correction = (
                    f"You granted effects of puzzle `{triggered.get('id')}` despite UNMET "
                    f"preconditions: {'; '.join(unmet)}. Re-emit with `success: false`, "
                    "a narration that honestly describes the failure, a small `time_advance_min` "
                    "and optionally `alarm_delta`. Do NOT include any of the puzzle's effects in "
                    "the delta."
                )
                retry = self.gm.adjudicate(
                    self.world.snapshot(), action, self.events, correction=pre_correction,
                )
                retry_delta = retry.get("delta") or {}
                if not delta_grants_effect(retry_delta, triggered) or check_preconditions(triggered, self.world.snapshot()) == []:
                    gm_response = retry
                    delta = retry_delta
                else:
                    # Force a clean failure response.
                    gm_response = {
                        "narration": (
                            f"The attempt fails: {'; '.join(unmet)}. Time slips by as you "
                            "fumble with what you do not yet have."
                        ),
                        "success": False,
                        "delta": {"time_advance_min": 1, "alarm_delta": 1},
                        "raw": gm_response.get("raw", {}),
                    }
                    delta = gm_response["delta"]

        if gm_response.get("success", True) and not delta_is_substantive(delta):
            correction = (
                "Your previous response had `success: true` but `delta` was empty (or contained only "
                "time/alarm changes). That violates the narration\u2194delta consistency rule. Either:\n"
                "(a) Re-emit with a substantive delta encoding the change your narration described "
                "(`inventory_add`, `object_state`, `npc_state`, `discovered_items`, `known_facts_add`, "
                "`objectives`, `current_location`, etc.), OR\n"
                "(b) Re-emit with `success: false` and a narration that honestly describes the failure, "
                "plus a small `time_advance_min` and/or `alarm_delta` as cost."
            )
            retry = self.gm.adjudicate(
                self.world.snapshot(), action, self.events, correction=correction,
            )
            retry_delta = retry.get("delta") or {}
            if delta_is_substantive(retry_delta) or not retry.get("success", True):
                gm_response = retry
                delta = retry_delta
            else:
                # GM still won't comply \u2014 force success=false so the player at least
                # sees no state change and can adapt.
                gm_response = {
                    **gm_response,
                    "success": False,
                    "narration": (
                        (gm_response.get("narration") or "").rstrip() +
                        " (Nothing actually changed; the attempt was hollow.)"
                    ).strip(),
                }
                delta = {"time_advance_min": int(delta.get("time_advance_min") or 1)}

        narration = gm_response.get("narration") or "(The GM is silent.)"
        success = bool(gm_response.get("success", True))
        await self._emit(make_event(tick, "gm_narration", "gm", {
            "text": narration,
            "success": success,
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

        # 3a. Record the completed action in the durable ledger if it produced
        # substantive state change. This is what makes the idempotency guard work
        # on the NEXT tick and what surfaces in both prompts as "already done".
        if success and delta_is_substantive(delta):
            self.world.record_completed_action(
                verb=action.verb,
                target=action.target,
                args=action.args,
                summary=_summarize_delta(delta) or narration[:120],
            )

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
            OllamaClient(settings.player_model, temperature=settings.player_temperature),
            OllamaClient(settings.gm_model, temperature=settings.gm_temperature),
        )
    raise ValueError(f"Unknown LLM_BACKEND: {settings.backend}")


def _summarize_delta(delta: dict[str, Any]) -> str:
    """Render a one-line summary of a substantive delta for the completed-actions ledger."""
    bits: list[str] = []
    inv_add = delta.get("inventory_add") or []
    if inv_add:
        bits.append(f"+inv {','.join(inv_add)}")
    inv_rm = delta.get("inventory_remove") or []
    if inv_rm:
        bits.append(f"-inv {','.join(inv_rm)}")
    for name, state in (delta.get("object_state") or {}).items():
        bits.append(f"{name}={state}")
    for name, state in (delta.get("npc_state") or {}).items():
        bits.append(f"npc {name}={state}")
    disc = delta.get("discovered_items") or []
    if disc:
        bits.append(f"discovered {','.join(disc)}")
    for oid, status in (delta.get("objectives") or {}).items():
        bits.append(f"obj {oid}={status}")
    if delta.get("current_location"):
        bits.append(f"loc={delta['current_location']}")
    return "; ".join(bits)


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
