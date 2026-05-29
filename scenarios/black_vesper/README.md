# `black_vesper`

The original hand-authored scenario for *Escapism*. As of 2026-05-28
this is the **regression fixture** for the Layer-1 scenario generator:
every change to the generator pipeline must produce a bundle that
loads and plays at least as well as this one, and Black Vesper itself
must keep solving in 13 ticks under the mock smoke test.

See [docs/Research-2026-05-28-two-layer-architecture.md](../../docs/Research-2026-05-28-two-layer-architecture.md)
for the full two-layer design and
[schemas/v1/README.md](../../schemas/v1/README.md) for the file contract.

## Files

- `manifest.json` \u2014 bundle metadata, pins `schema_version: 1`.
- `world_initial.json` \u2014 starting `WorldState` (tick 0, brig, Hal asleep).
- `game.jsonl` \u2014 the LLM-facing clue corpus (40 docs: meta/lore/rule/
  objective/location/item/npc/hint/puzzle).

## Validate

```bash
python -m scripts.validate_scenario scenarios/black_vesper
```

## Play

```bash
# default \u2014 SCENARIO defaults to "black_vesper"
USE_CHROMA=0 LLM_BACKEND=mock python -m server smoke
```
