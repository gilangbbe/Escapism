"""tools.solver — STRIPS-like BFS solver for scenario bundles.

Reads a scenario bundle (manifest + world_initial + game corpus), treats
every doc with ``trigger`` + ``effects`` as an operator (puzzle / recipe
/ discovery), runs breadth-first search over the discrete state
``(current_location, inventory, object_state, npc_state, objectives,
discovered_items)``, and returns the shortest action sequence that
reaches the manifest's ``goal`` predicate.

If no plan exists, returns :class:`Unsolvable` with the list of goal
sub-conditions never reached \u2014 the build-time signal that the bundle
is broken.

This is Layer 1's correctness oracle: the Layer-1 generator (Phase D)
will call it after every PuzzleDesigner pass and reject bundles the
solver can't solve in the target length window. For hand-authored
scenarios it also catches regressions when the corpus is edited.
"""
from __future__ import annotations

from .state_search import (
    Operator,
    Plan,
    SolverResult,
    Unsolvable,
    load_bundle,
    solve,
)

__all__ = ["Operator", "Plan", "SolverResult", "Unsolvable", "load_bundle", "solve"]
