"""CLI entrypoints for the Escapism server.

Usage:
    python -m server               # run FastAPI on :8000
    python -m server smoke         # run a headless mock simulation and exit
"""
from __future__ import annotations

import asyncio
import sys


def _run_server() -> None:
    import uvicorn

    uvicorn.run("server.api:app", host="0.0.0.0", port=8000, reload=False)


def _run_smoke() -> None:
    from .simulation import Simulation

    sim = Simulation.build()

    async def runner() -> None:
        await sim.run_loop()
        print("\n--- final world snapshot ---")
        import json
        print(json.dumps(sim.world.snapshot(), indent=2))

    asyncio.run(runner())


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        _run_smoke()
    else:
        _run_server()


if __name__ == "__main__":
    main()
