# Escapism — *The Last Voyage of the Black Vesper*

A narrative-only LLM escape-room PoC. One LLM agent plays **Mira "Ironhand"
Castellanos**, the Quartermaster of a pirate brig. A second LLM agent plays
the **Game Master** — the world's sole mutator and narrator. They speak to
each other in strict JSON, and the resulting story streams to a React chat UI
over WebSocket.

```
┌──────────────────┐    JSON    ┌────────────────────┐
│  Player Agent    │ ─action──▶ │  Game Master Agent │
│  (Mira)          │            │  (validates, narr.)│
└────────┬─────────┘            └─────────┬──────────┘
         │ uses                            │ mutates
         ▼                                 ▼
   ┌──────────────┐                ┌──────────────┐
   │ ClueStore    │◀────grounds────│  WorldState  │
   │ (Chroma + JSONL)              │   (JSONL log)│
   └──────────────┘                └──────────────┘
                                        │ broadcast
                                        ▼
                               ┌──────────────────┐
                               │ FastAPI / WS hub │
                               └─────────┬────────┘
                                         ▼
                               ┌──────────────────┐
                               │  React chat UI   │
                               └──────────────────┘
```

## Layout

```
data/
  game.jsonl          # LLM-facing clue corpus (each line is one document)
  world_initial.json  # starting snapshot
  runs/<ts>.events.jsonl  # append-only event log per run
  runs/<ts>.world.json    # final world snapshot per run
  chroma/             # persistent Chroma index (auto-created)
server/
  config.py           # env-driven settings
  world/              # WorldState + JSONL event store
  memory/clue_store.py    # Chroma + keyword fallback
  llm/                # base, mock (deterministic), ollama
  agents/             # protocol, player, gm
  simulation.py       # turn loop, broadcast
  api.py              # FastAPI + WebSocket hub
  __main__.py         # CLI: `python -m server` | `python -m server smoke`
client/               # Vite + React + TS + Tailwind chat UI
legacy/               # earlier 2D-grid scaffold, preserved for reference
```

## Run the PoC (mock LLMs — no external deps required)

The mock player walks Mira through the canonical Act 1 solution; the mock GM
applies the matching world deltas. Verifies the wiring without Ollama or
Chroma.

```bash
USE_CHROMA=0 LLM_BACKEND=mock python -m server smoke
```

Expected: Mira escapes the brig and reaches `lower_decks`,
`objectives.escape_brig == "complete"`, `game_over == "poc_complete"`.

## Tests

```bash
pip install -r requirements.txt   # pytest is included
USE_CHROMA=0 python -m pytest tests/ -q
```

The suite covers the tolerant JSON parsers, every branch of
`WorldState.apply_delta` (including the auto fail-states for `alarm_max`
and `port_royal_reached`), and the `ClueStore` keyword fallback. The
Chroma path is exercised only when `chromadb` is importable.

## Run the live web app

Terminal 1 — install Python deps (one-time) and start the server:

```bash
source .venv/bin/activate
pip install -r requirements.txt
LLM_BACKEND=mock python -m server          # FastAPI on :8000
```

Terminal 2 — start the client:

```bash
cd client
npm install
npm run dev                                 # Vite on :5173, proxies /ws and /api
```

Open <http://localhost:5173>. The simulation autostarts; the right-hand panel
shows the live world (time, inventory, objectives, alarm). The chat shows
Mira's thoughts (sea-green italic), spoken lines (ember bubbles), action
cards (brass monospace), and GM narration (dark stone).

## Switch to a real LLM (Ollama)

```bash
ollama serve &
ollama pull qwen2.5:7b        # recommended: stronger planner for the Player
ollama pull llama3.2          # adequate for the GM (mostly structured edits)

LLM_BACKEND=ollama \
  PLAYER_MODEL=qwen2.5:7b \
  GM_MODEL=llama3.2 \
  LLM_TEMPERATURE=0.3 \
  LLM_SEED=42 \
  python -m server
```

Both agents request `format=json` from Ollama and parse defensively. The
ClueStore grounds the GM in the JSONL corpus to reduce hallucination; if
ChromaDB is unavailable it falls back to a keyword retriever over the same
corpus. The Chroma index is persisted under `data/chroma/` and is
re-indexed automatically when `data/game.jsonl` changes (mtime check).
Setting `LLM_SEED` makes the Ollama runs reproducible.

**Model picking notes.**
- The **Player** needs multi-step planning (chain inventory items, avoid
  re-examining what it just examined). Small instruct models like
  `llama3.2:3b` will frequently loop on a single EXAMINE; use a 7B+ model
  (`qwen2.5:7b`, `llama3.1:8b`, `mistral:7b-instruct`) here.
- The **GM** mostly emits structured deltas grounded in retrieved clues, so
  `llama3.2:3b` is fine. Upgrade only if narration quality matters.
- The Player prompt enforces an anti-repeat rule and the Simulation injects
  a `system_hint` event when the same `(verb, target)` repeats 3 turns in a
  row, so even smaller models recover from loops eventually.

## Smarter cognition (Phase 4)

The Player loop is layered with four cognitive aids beyond the bare
"propose JSON action" cycle:

- **Episodic memory** — a per-run, in-memory store of GM narrations,
  state deltas, hints, and reflections. Retrieved by keyword + recency
  every turn into the Player's prompt under
  *"From your memory of THIS voyage"*. Distinct from the static
  Chroma-backed `ClueStore` (semantic).
- **BDI overlay** — every turn Mira emits `intent` (one-line current
  goal) and `plan` (1–3 next steps). They are persisted in
  `world.player_bdi` (with an `intent_age` counter) and re-surfaced on
  the next turn. The Player is told to revise her intent if it has not
  progressed in 4 turns.
- **Reflection step** — every `REFLECT_EVERY` ticks (default 5) the GM
  LLM compresses recent events into one summary paragraph + up to three
  new `known_facts` that get merged into the world. The old raw episodes
  are compacted away. Set `REFLECT_EVERY=0` to disable.
- **Salty the parrot (tiered hints)** — when the Player keeps trying the
  same `(verb, target)`, hints escalate through three tiers
  (`SALTY_TIER_STEP`, default 3 repeats per tier): vague nudge →
  corpus `kind=hint, tier≤2` → corpus `kind=hint, tier=3` or
  `kind=puzzle`. Tier shows on the UI hint chip.

## How the architecture fights hallucination

1. **Authoritative world state.** Only the GM may mutate the world, and only
   via a structured `delta` JSON object. The player's free-form prose never
   touches state directly.
2. **Grounded retrieval.** Every GM prompt includes the top-*k* relevant clue
   documents from the ChromaDB index (built from `data/game.jsonl`). The GM
   system rules forbid inventing facts not present in those documents.
3. **Tight JSON contracts.** Both agents are pinned to strict schemas; the
   parser tolerates chatty wrappers but discards anything that isn't a valid
   action/delta.
4. **Per-run event log.** Every player thought, action, GM narration, and
   delta is appended to `data/runs/<ts>.events.jsonl`. Replayable and
   auditable.

## Scope of this PoC

- ✅ Act 1 (the Brig) — fully playable end-to-end with mock and real LLMs.
- 🔒 Acts 2–5 — ingested as clue stubs in `game.jsonl`; not yet driven by the
  mock GM. Use a real LLM and the live UI to explore beyond Act 1.
- See [Roadmap.md](Roadmap.md) for the phased plan.

## Documents

- [ProjectDocument.md](ProjectDocument.md) — vision, architecture, schemas.
- [Journal.md](Journal.md) — decision log.
- [Roadmap.md](Roadmap.md) — phased plan.
- [game.md](game.md) — original human-facing design brief.
- [data/game.jsonl](data/game.jsonl) — the LLM-facing version.
