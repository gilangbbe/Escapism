# Scenario bundle schemas — v1

Frozen contract between Layer 1 (Generator) and Layer 2 (Simulator).
See [docs/Research-2026-05-28-two-layer-architecture.md](../../docs/Research-2026-05-28-two-layer-architecture.md).

Every scenario directory under `scenarios/<id>/` must contain:

| File | Schema | Purpose |
|---|---|---|
| `manifest.json` | [manifest.schema.json](manifest.schema.json) | Bundle metadata; pins `schema_version`. Declares `goal`, `optimal_solution_length`, `solver_proof`. |
| `world_initial.json` | [world_initial.schema.json](world_initial.schema.json) | Starting `WorldState`. |
| `game.jsonl` | [game_doc.schema.json](game_doc.schema.json) (one validation per line) | LLM-facing clue corpus. Docs with `kind` in {`puzzle`, `recipe`, `discovery`} act as STRIPS-like operators (`trigger` + `preconditions` + `effects`). |
| `solver_proof.json` | — | BFS-derived canonical plan that reaches `manifest.goal`. Written by `python -m tools.solver --write-proof`. Re-derivable from the other three files. |

Validate with:

```bash
python -m scripts.validate_scenario scenarios/black_vesper
```

Prove solvability with:

```bash
python -m tools.solver scenarios/black_vesper             # print plan
python -m tools.solver --write-proof scenarios/black_vesper  # freeze solver_proof.json
```

CI runs `validate_scenario` against every directory under `scenarios/`, and `tests/test_solver.py` re-derives the Black Vesper plan and asserts it matches both the manifest's `optimal_solution_length` and the committed proof file.
