"""Entry point for the single-LLM-agent escape-room PoC.

Usage:
    python3 main.py                  # default: Ollama backend (llama3.2)
    python3 main.py --backend mock   # deterministic, no LLM required
    python3 main.py --backend ollama --model llama3.2
"""

from __future__ import annotations

import argparse

from escape_room import (
    ActionValidator,
    LLMAgent,
    MockLLMClient,
    OllamaClient,
    Ontology,
    PuzzleEngine,
    Simulation,
    TurnTracker,
    WorldState,
    default_escape_puzzle,
    default_solo_persona,
)


LAYOUT = """
#########
#A....#.#
#.###.#.#
#.#.K.#.#
#.#.###.#
#.......D
#########
"""


def build_llm(backend: str, model: str | None):
    if backend == "mock":
        return MockLLMClient()
    if backend == "ollama":
        return OllamaClient(model=model) if model else OllamaClient()
    raise SystemExit(f"Unknown backend: {backend}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Escape Room PoC — single LLM agent.")
    parser.add_argument("--backend", choices=["ollama", "mock"], default="ollama")
    parser.add_argument("--model", default=None, help="LLM model name (Ollama only).")
    parser.add_argument("--max-ticks", type=int, default=40)
    parser.add_argument("--delay", type=float, default=0.0)
    args = parser.parse_args()

    world = WorldState.from_ascii(LAYOUT)
    world.add_body("agent-1", position=(1, 1))

    ontology = Ontology.default()
    validator = ActionValidator(world=world, ontology=ontology)
    puzzles = PuzzleEngine()
    puzzles.register(default_escape_puzzle())
    tracker = TurnTracker()

    llm = build_llm(args.backend, args.model)
    agent = LLMAgent(
        persona=default_solo_persona(),
        llm=llm,
        agent_id="agent-1",
    )

    sim = Simulation(
        world=world,
        ontology=ontology,
        validator=validator,
        puzzles=puzzles,
        turn_tracker=tracker,
        agents=[agent],
        max_ticks=args.max_ticks,
        delay=args.delay,
    )
    sim.run()


if __name__ == "__main__":
    main()
