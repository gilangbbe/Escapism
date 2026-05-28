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
