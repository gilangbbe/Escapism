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
