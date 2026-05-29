# Roadmap

Status legend: `[x]` done · `[~]` in progress · `[ ]` not started

---

## Phase 0 — Toy gridworld (archived)

- [x] Single-file gridworld escape room (BFS agent)

## Phase 1 — LLM agent scaffold on a grid (archived)

- [x] Layered environment / memory / llm / model / ui packages
- [x] JSON action protocol; mock + Ollama backends; ASCII chat UI
- [x] Moved to `legacy/` when the goal pivoted to pure narrative

## Phase 2 — Narrative PoC: Player + GM agents on the web (current)

- [x] Solo-Mira clue corpus (`data/game.jsonl`)
- [x] WorldState + JSONL event log
- [x] ClueStore with ChromaDB and keyword fallback
- [x] LLM clients (mock + Ollama) shared by both agents
- [x] Game Master agent (validator + narrator, JSON delta protocol)
- [x] Player agent (JSON action protocol)
- [x] Simulation orchestrator + per-run JSONL log
- [x] FastAPI + WebSocket server
- [x] React + Vite + TS + Tailwind chat UI
- [x] Mock end-to-end smoke test passes (Mira escapes the brig)
- [x] Docs updated (README, ProjectDocument, Journal, Roadmap)
- [ ] Smoke run against a real Ollama model (`ollama serve` + `ollama pull llama3.2`)
- [ ] Verify ChromaDB indexes the corpus and grounds the GM in practice (real LLM)
- [ ] Capture a recorded run video / GIF for the README

## Phase 3 — Hardening (current)

- [x] Unit tests: protocol parsers (tolerant JSON), delta application
- [x] Unit tests: ClueStore (Chroma path + fallback path)
- [x] Add `LLM_SEED` env var; existing `LLM_TEMPERATURE` already wired
- [x] Persist Chroma between runs; re-index on `game.jsonl` mtime change
- [ ] Mock GM coverage for Acts 2–5 happy paths
- [ ] Inbound WebSocket messages (player notes, GM hint requests via Salty)

## Phase 4 — Smarter cognition

- [x] Reflection step: GM compresses recent events into new `known_facts`
- [x] Episodic / semantic memory split for the Player Agent (in-memory episodic store; Chroma stays semantic)
- [x] BDI overlay (Belief / Desire / Intention) above the action loop
- [x] Salty parrot as an in-game tiered hint provider (Tier 1/2/3 from the design doc)
- [x] Completed-actions ledger + idempotency guard + narration↔delta consistency retry
  (anti state-drift hardening on top of the BDI loop)
- [x] Reflection emits a deterministic state digest (location, alarm, inventory, object/npc/objective state) every reflection tick so long runs cannot “forget” state even when the LLM context is truncated
- [x] Per-agent temperature knobs (`PLAYER_TEMPERATURE`, `GM_TEMPERATURE`); default models bumped to `qwen2.5:7b` for both agents (3B class models drift on 30+ tick runs)
- [x] Corpus-declared puzzle preconditions & effects (`trigger`, `preconditions`, `effects` on `kind=puzzle` docs in `game.jsonl`) + server-side validator: GM cannot grant a puzzle’s effects when its preconditions are unmet — enforced by `server/agents/puzzle_validator.py`

## Phase 5 — Multi-agent + replayability

- [ ] Add a second Player Agent (one of the other roles wakes from the rum)
- [ ] Per-agent chat lanes in the UI; shared world + chat history
- [ ] Co-op locks (puzzles requiring two simultaneous actions)
- [ ] Branching endings driven by Act 5 confrontation
- [ ] Replay viewer: load a saved `runs/<ts>.events.jsonl` and replay frame-by-frame

## Phase 6 — Observability & evaluation

- [ ] Metrics: ticks-to-escape, tokens used, failed-action rate, alarm spikes
- [ ] Batch runner: sweep models / personas / seeds; aggregate success rates
- [ ] Trace explorer in the UI: jump to any tick, inspect the world at that point

## Phase 7 — Generator (Layer 1): procedurally generated scenarios

The Simulator is Layer 2 of a two-layer architecture. Layer 1 is an LLM
pipeline that generates entire scenarios (world, puzzles, prose) as
*scenario bundles* the Simulator can boot from. See
[docs/Research-2026-05-28-two-layer-architecture.md](docs/Research-2026-05-28-two-layer-architecture.md).

### Phase A — Freeze the contract

- [x] JSON-Schemas for manifest, world_initial, and game-doc kinds (`schemas/v1/`)
- [x] Migrate the hand-authored Black Vesper corpus to `scenarios/black_vesper/`
- [x] `SCENARIO` env var + `scenario_dir(...)` path indirection in the loader
- [x] `python -m scripts.validate_scenario [<bundle>...]` CLI
- [x] CI test (`tests/test_scenario_bundles.py`) validates every bundle under `scenarios/`
- [x] Per-scenario Chroma collection name so bundles cannot cross-contaminate the index

### Phase B — Solver (PCG soundness)

- [x] `tools/solver/state_search.py`: BFS over `{inventory, object_state, npc_state, location}`
- [x] CLI: `python -m tools.solver scenarios/<id>` → optimal plan length or `Unsolvable(reason)`
- [x] Black Vesper solves under the solver (optimal length **10**; mock smoke takes 13 ticks because three info-only EXAMINE turns are valid play but not strict-state operators)
- [x] Emit `solver_proof.json` into the bundle (canonical plan)
- [x] Round-trip test: committed `solver_proof.json` matches a fresh solve
- [x] New `discovery` operator kind in `game_doc.schema.json` (trigger + effects, no preconditions required)

### Phase C — Affordance engine

- [x] `server/world/affordances.py`: enumerate legal `(verb, target, on)` tuples from world + bundle
- [x] Surface the menu in the Player prompt; tighten `PlayerAction` so the verb/target must come from the menu (hybrid: validator rejects off-menu, resamples once with correction, then auto-picks top entry)
- [x] Eliminate the action-space hallucination class (e.g. invented composite target ids) — `op_id` now flows through `completed_actions` so spent operators are filtered, and EXAMINE/SEARCH repeats are annotated `⚠ tried Nx, no new info`

### Phase D — Generator pipeline (LLM)

- [ ] `tools/generator/setting_writer.py` (theme + tone bible + locations)
- [ ] `tools/generator/puzzle_designer.py` → STRIPS-like puzzle graph JSON
- [ ] Solver-in-the-loop retries until solvable in `[diff_min, diff_max]`
- [ ] `tools/generator/narrative_editor.py` (prose wrapper)
- [ ] `tools/generator/critic.py` + `tools/generator/qa_player.py`
- [ ] `tools/generator/orchestrator.py` (the full DAG, with bundle freezing)

### Phase E — Deployment

- [ ] `POST /api/scenarios/generate { theme, difficulty }`
- [ ] Scenario picker in the client UI
- [ ] `POST /api/runs/new { scenario_id }`
