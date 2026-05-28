# Journal

A running log of decisions and the reasoning behind them. Append-only.

---

## 2026-05-26 — PoC v0 (BFS toy, superseded)

Built a single-file gridworld escape room with a hand-coded BFS agent.
Archived under [legacy/](legacy/) when the goal pivoted to LLM agents.

## 2026-05-26 — PoC v1 (LLM agent scaffold, superseded)

Refactored the gridworld into a layered scaffold (environment / memory /
llm / model / ui) with `Persona`, `CognitiveLoop`, mock + Ollama clients.
The grid stayed; the agent's intelligence moved into the LLM. Validated
the JSON action protocol end-to-end against a mock backend. Archived
under [legacy/](legacy/) when the goal pivoted to a pure-narrative,
web-rendered PoC.

## 2026-05-26 — PoC v2 (narrative-only, Player + GM agents, web UI)

Major pivot. Dropped the 2D grid entirely. New architecture:

1. **Two LLM agents.** A Player Agent (Mira) and a Game Master Agent. The
   Player proposes an action JSON; the GM adjudicates and emits a
   narration + structured state delta. The world is updated, the events
   are broadcast.
2. **Solo protagonist.** Reframed *The Last Voyage of the Black Vesper*
   around Mira "Ironhand" Castellanos alone in the brig. The other senior
   crew lie unconscious in the cell — narrative justification for a solo
   PoC and a built-in source of inventory (Eliza's herbs/vial/recipes,
   Jin's compass, Kwame's rope, etc.).
3. **Clue corpus as ground truth.** Rewrote the design doc into
   `data/game.jsonl` — every location, item, NPC, puzzle, rule, hint, and
   objective is one JSON document. This corpus is the LLM-facing version
   of `game.md`.
4. **ChromaDB grounding.** A `ClueStore` indexes `game.jsonl` into Chroma
   on startup (default ONNX MiniLM embedder — no Ollama embedding calls
   needed). Both agents retrieve top-*k* relevant clues every turn. Falls
   back to a keyword retriever if Chroma is unavailable, so the system
   always boots.
5. **World state is JSON + a JSONL event log.** `WorldState` is a single
   mutable snapshot the GM updates via structured deltas. Every event
   (thought, say, action, narration, delta) is appended to
   `data/runs/<ts>.events.jsonl`. Replayable, auditable, no hidden state.
6. **Strict JSON contracts.** Action and adjudication schemas are
   declared in `agents/protocol.py` and embedded in system prompts. A
   tolerant parser scans for the first JSON block containing a `verb` or
   `narration` field, ignoring chatty wrappers. Malformed responses
   degrade to a safe WAIT.
7. **FastAPI + WebSocket.** The simulation autostarts on app startup. New
   clients get the full event history on connect and live events
   thereafter. A `POST /api/reset` reboots the run.
8. **React + Vite + TS + Tailwind UI.** Messenger-style chat. Mira's
   thoughts (italic sea-green), spoken lines (ember bubbles), and action
   cards (brass monospace) align right; GM narration aligns left in dark
   stone bubbles; world-state diffs render as small monospace chips
   between turns. Right sidebar HUD shows time, location, alarm meter,
   inventory, objectives, and recent facts.
9. **Mock-first development.** A deterministic mock player + mock GM walk
   the canonical Act 1 solution end-to-end, so the wiring is provable
   without any LLM. Real Ollama is one env var away.

### Smoke test (mock backend)

```bash
USE_CHROMA=0 LLM_BACKEND=mock TICK_DELAY=0 python -m server smoke
```

Result: Mira escapes the brig in 13 ticks, `objectives.escape_brig`
becomes `complete`, `current_location` advances to `lower_decks`,
`game_over = "poc_complete"`.

### Bug found and fixed during this build

The first mock smoke test produced zero state changes — every GM
response was the "nothing happens" fallback. Root cause: the GM's user
prompt embeds **two** JSON code fences (the world snapshot first, the
player action second), and the mock GM's extractor greedily took the
first fence. Fix: the extractor now scans every JSON block and picks the
first one whose payload contains a `verb` key.

### Open items

- Real-LLM smoke test (`LLM_BACKEND=ollama PLAYER_MODEL=llama3.2`) —
  pending the user starting the Ollama daemon and pulling a model.
- Acts 2–5 are present in the clue corpus but not yet covered by the
  mock GM's response table. The real LLM should be able to drive them
  from the clues alone; verifying this is Phase 3 work.

## 2026-05-26 — Auto fail-states + GM anti-stall

First live Ollama run surfaced three issues:

1. `alarm_meter` would climb to 10 but the simulation kept going — no
   terminal check anywhere. Same with `minutes_until_port_royal` hitting 0.
2. The GM raised the alarm in the delta but never narrated *why*, so the
   chat looked disconnected from the HUD.
3. With `llama3.2:3b` the Player Agent looped on `EXAMINE hal_keyring`.

Fixes:

- `WorldState.apply_delta` now auto-sets `game_over="alarm_max"` when
  `alarm_meter >= alarm_max`, and `game_over="port_royal_reached"` when
  the countdown reaches 0. It also writes a transient `auto_game_over`
  flag the Simulation pops to inject a closing GM narration so the player
  sees a proper ending paragraph in the chat.
- GM system prompt grew a "Time and alarm (CRITICAL)" section and an
  "Anti-stall (CRITICAL)" clause that requires the GM to either reveal a
  new fact pointing at the next step or charge `alarm_delta` /
  `time_advance_min` when the player keeps repeating itself.
- GM prompt now also surfaces the last four player actions for stall
  detection.
- README recommends `qwen2.5:7b` for the Player and keeps `llama3.2` for
  the GM. Smaller models can still recover thanks to the loop-detector
  hint, but planning quality is markedly better with a 7B+ planner.

## 2026-05-26 — Phase 3 hardening: tests, persistence, seed

Four Phase 3 items shipped:

- `tests/` (50 tests, all green via `pytest tests/ -q`):
  - `test_protocol.py` covers `_extract_first_json` (fenced, multi-fence,
    prose-wrapped, malformed, nested), `parse_player_response`
    (defaults, uppercased verb, non-dict args, garbage input), and
    `parse_gm_response` (defaults, non-dict delta, success false).
  - `test_world.py` exercises every branch of `apply_delta` plus the new
    auto fail-states and the clock helper (rollover, midnight wrap,
    malformed input).
  - `test_clue_store.py` validates the keyword fallback (ranking, scope,
    empty/no-match), and gates the Chroma path on `chromadb` being
    importable.
  - `conftest.py` makes the repo root importable.
- `ClueStore` now persists between runs. It writes
  `data/chroma/<collection>.mtime` after indexing and on next boot
  compares against the JSONL's current mtime; if it changed it drops the
  collection and rebuilds, otherwise it reuses the persisted index.
- `Settings.seed` reads `LLM_SEED`; when set, `OllamaClient.chat`
  forwards it in `options.seed` for reproducible runs alongside the
  existing `LLM_TEMPERATURE` knob.

Remaining Phase 3 work (deferred):

- Mock GM coverage for Acts 2–5.
- Inbound WebSocket messages for player notes / GM hint requests.

## 2026-05-27 — Phase 4: smarter cognition (episodic memory, reflection, BDI, Salty)

Wired four cognitive upgrades into the Player + GM loop.

- **Episodic memory.** New `EpisodicMemory` (server/memory/episodic.py) —
  per-run, in-memory, keyword + recency retrieval. Distinct from
  `ClueStore` (semantic, static, Chroma). Narrations, deltas, hints, and
  reflections are appended every turn; the Player's prompt now includes a
  *"From your memory of THIS voyage"* section pulled by
  `episodic.query(world.location + intent + objectives)`.
- **Reflection.** New `Reflector` (server/agents/reflection.py) — every
  `REFLECT_EVERY` ticks (default 5), the GM's LLM is asked to compress
  recent events into one paragraph + up to three new `known_facts`. The
  facts are merged via `apply_delta({"known_facts_add": [...]})`; the
  summary replaces the older raw episodes via `episodic.compact()`. New
  event kind `reflection` surfaces in the UI as a centred scene-break
  card.
- **BDI overlay.** `PLAYER_ACTION_SCHEMA` gained `intent` (one-line
  current goal) and `plan` (1–3 next steps). `PlayerAction` carries them;
  the simulation persists them in `world.player_bdi` along with an
  `intent_age` counter. The Player prompt now opens with a *Desires /
  Beliefs / Intentions* block — Desires = active objectives, Beliefs =
  recent `known_facts` + top episodic hits, Intentions = the previous
  turn's persisted intent + plan. Rules tell Mira to revise her intent if
  it hasn't progressed in 4 turns. The mock client synthesizes intent +
  plan so the smoke test exercises the same plumbing.
- **Salty tiered hints.** Replaced the binary loop hint with `Salty`
  (server/agents/salty.py). Repeats of the same (verb, target) escalate
  through three tiers controlled by `SALTY_TIER_STEP` (default 3):
  Tier 1 = vague nudge + active objective; Tier 2 = `kind=hint, tier≤2`
  doc from the corpus scoped to the current act; Tier 3 = `kind=hint
  tier=3` or `kind=puzzle`. Hints are emitted as `system_hint` events
  (now carry `tier`, `streak`, `verb`, `target`) and folded back into
  episodic memory so the Player surfaces them on the next turn.

Tests: added `tests/test_episodic.py` (bounded add / compact /
keyword+recency / fallback), `tests/test_salty.py` (tier 1/2/3 selection
+ no-doc fallback), `tests/test_reflection.py` (parse / compact / cap /
failure paths) plus three BDI cases in `tests/test_protocol.py`. Suite is
67 / 67 green and the mock smoke still escapes the brig in 13 ticks
with `player_bdi` persisted on the final snapshot.

Knobs added: `REFLECT_EVERY` (env, default 5; 0 disables) and
`SALTY_TIER_STEP` (env, default 3).

## 2026-05-28 — Anti state-drift: completed-actions ledger + consistency retry

Observed in a long Ollama run (35+ ticks): Mira would brew the herbs at
tick 20 (GM narrates success), then at tick 30 brew them AGAIN as if the
first time had never happened. Diagnosis: the GM was emitting `narration`
without a matching `delta`, so the world snapshot never reflected the
claim. By the time the action drifted out of the recent-events window,
both agents “forgot” it had ever happened. Five fixes shipped together:

1. **Completed-actions ledger.** `WorldState` now keeps an append-only
   `completed_actions: [{tick, verb, target, on, summary}]`. The
   simulation writes to it after every successful, substantive delta via
   `WorldState.record_completed_action(...)`. The entry is idempotent on
   `(verb, target, on)` so a re-trigger never duplicates. Both the Player
   and the GM prompts now include a `## Completed actions / Actions you
   have ALREADY COMPLETED` section drawn from this ledger — durable,
   deterministic, and survives any context-window truncation.
2. **Pre-GM idempotency guard.** Before calling the GM, the simulation
   checks `WorldState.find_completed_action(...)` for the player's exact
   `(verb, target, on)`. For state-changing verbs (USE, COMBINE, TAKE,
   MOVE_TO) a hit short-circuits the GM entirely — it emits a
   `gm_narration` (flagged `idempotent: true`) redirecting Mira to the
   next step and feeds it into episodic memory. EXAMINE / SEARCH are
   never short-circuited (information verbs may legitimately repeat).
3. **Narration↔delta consistency rule + retry.** New `delta_is_substantive`
   helper in `world/state.py` recognizes deltas that mutate world facts
   (anything beyond `time_advance_min` / `alarm_delta`). If the GM emits
   `success: true` with a non-substantive delta, the simulation calls
   `GameMasterAgent.adjudicate(..., correction=...)` once with an inline
   correction note explaining the violation. If the retry still won't
   comply, the simulation forces `success: false` and appends *“Nothing
   actually changed; the attempt was hollow.”* so the player at least
   sees the rejection and adapts.
4. **GM prompt hardened.** New CRITICAL sections: “Idempotency — NEVER
   re-do completed actions” (with a worked example: USE herbs on vial
   when herbs are already brewed → empty delta + redirect) and
   “Narration↔delta consistency” (success true implies at least one
   substantive delta field). The recent-events window now shows actual
   payload text (narration, delta notes, action verbs) instead of bare
   event-kind names, and was widened from 10 to 16 entries.
5. **Player prompt updated.** New `Actions you have ALREADY COMPLETED`
   section pulled from the ledger; recent-events window now shows
   narration text and delta notes; anti-loop rules explicitly forbid
   re-attempting anything in the completed-actions ledger.

Tests: `tests/test_completed_actions.py` (10 cases covering
`delta_is_substantive` + ledger add/find/idempotency) and
`tests/test_simulation_consistency.py` (6 async cases covering guard
short-circuit, retry success, retry-fails-fallback, ledger writes, no
log on failure, EXAMINE never guarded). Suite is 90 / 90 green; mock
smoke still escapes the brig in 13 ticks with a 13-entry
`completed_actions` ledger on the final snapshot.

This closes the worst class of bug the BDI overlay couldn't reach —
memory of *belief* is no longer enough; we now have a durable memory of
*action*.

## 2026-05-28 — Phase 4 polish: state digest, per-agent temps, puzzle preconditions

Even with the completed-actions ledger and the consistency retry, a
long Ollama run at `llama3.2:3b` (both agents) still drifted: the GM
repeated narration verbatim and started raising the alarm spuriously.
Three coupled changes shipped today address it from three angles —
memory, model, and rules.

1. **Deterministic state digest in reflection.** Every reflection tick,
   `Reflector` now prepends a one-line digest of the world snapshot
   (location, alarm meter, inventory, object/npc/objective state) to the
   LLM-emitted `new_facts`. The digest is deduplicated against existing
   `known_facts` and the cap grows from 3 to 4 when the digest is
   present. Result: even when the LLM emits garbage and even when the
   context window truncates prior facts, both agents always have at
   least one authoritative “this is the world right now” sentence in
   their prompts.
2. **Per-agent temperatures + bigger default model.** `Settings` gained
   `player_temperature` (env `PLAYER_TEMPERATURE`, default 0.3) and
   `gm_temperature` (env `GM_TEMPERATURE`, default 0.15 — deliberately
   low for adjudication). Both fall back to `LLM_TEMPERATURE` if set.
   `OllamaClient` already supports per-instance temperature override;
   `simulation._build_llms` now uses it. Default `PLAYER_MODEL` and
   `GM_MODEL` are both `qwen2.5:7b` (was `llama3.2`) — 3B-class models
   simply cannot track state across 30+ ticks.
3. **Puzzle preconditions + effects (corpus + validator).** The four
   Act-1 puzzle documents in `data/game.jsonl` now declare structured
   `trigger`, `preconditions`, and `effects`. New module
   `server/agents/puzzle_validator.py` provides:
   - `find_triggered_puzzle(clues, verb, target, args, scope)` — match a
     player action to its puzzle doc.
   - `check_preconditions(puzzle, world)` — returns a list of unmet
     preconditions (inventory_has, object_state, npc_state, discovered).
   - `delta_grants_effect(delta, puzzle)` — does this GM delta hand out
     any of the puzzle’s declared effects?
   - `format_precondition_brief(puzzle)` — one-line summary for prompt
     injection.

   Wired both ways:
   - In `GameMasterAgent._build_user_prompt`: if the player’s action
     triggers a puzzle, the prompt gains a *“Triggered puzzle (FORMAL
     PRECONDITIONS — obey strictly)”* section listing the contract and
     any currently-unmet preconditions, with an explicit instruction to
     emit `success: false` when unmet.
   - In `Simulation._take_turn`: after the existing consistency retry,
     if the GM granted any of the puzzle’s effects while preconditions
     are unmet, the simulation re-prompts the GM once with a hard
     correction. If the retry still won’t comply, the response is
     forced to `success: false` with a *“Cannot complete: ...”* narration
     and a small `time_advance_min` / `alarm_delta` cost. The puzzle’s
     effects can no longer leak into the world before its preconditions
     are met.

Tests: `tests/test_puzzle_validator.py` covers trigger matching
(verb/target/on + scope + case-insensitivity), every precondition type
met + unmet (singly and stacked), each effect-overlap branch, and the
brief formatter. Existing `tests/test_reflection.py` updated to expect
the prepended digest. Suite is 106 / 106 green; mock smoke still
escapes the brig in 13 ticks (mock GM table happens to satisfy
preconditions in the right order, so the validator is a no-op on the
canonical solution — it only fires when the GM tries to cheat).

This is the final layer of the anti-drift stack: memory of belief
(episodic + reflection), memory of action (completed-actions ledger),
deterministic memory of state (digest), and now corpus-grounded memory
of rules (puzzle preconditions). The 3B-vs-7B model question becomes
mostly a quality knob rather than a correctness one.
