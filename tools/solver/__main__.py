"""CLI for tools.solver.

Usage:
    python -m tools.solver scenarios/<id> [...]
    python -m tools.solver --write-proof scenarios/<id>

Without --write-proof: prints the plan (or the unsolvable reason) for
every bundle and exits non-zero on failure.

With --write-proof: re-solves the bundle and writes
``scenarios/<id>/solver_proof.json`` (as declared by
``manifest.solver_proof`` or defaulting to that name).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .state_search import Plan, Unsolvable, load_bundle, solve

ROOT = Path(__file__).resolve().parent.parent.parent


def _run(bundle: Path, *, write_proof: bool) -> int:
    rel = bundle.relative_to(ROOT) if bundle.is_relative_to(ROOT) else bundle
    try:
        manifest, world, operators = load_bundle(bundle)
    except FileNotFoundError as exc:
        print(f"[FAIL] {rel}: {exc}")
        return 1

    goal = manifest.get("goal") or {}
    result = solve(world, operators, goal)

    if isinstance(result, Unsolvable):
        print(f"[FAIL] {rel}: {result.reason}")
        if result.unmet_goal:
            print(f"        unmet: {json.dumps(result.unmet_goal, indent=2)}")
        return 1

    assert isinstance(result, Plan)
    print(f"[ ok ] {rel}: optimal plan length = {result.length}")
    for i, op in enumerate(result.operators, 1):
        print(f"  {i:>2}. [{op.id}] {op.action_label()}")

    if write_proof:
        proof_name = manifest.get("solver_proof", "solver_proof.json")
        proof_path = bundle / proof_name
        proof_path.write_text(json.dumps(
            result.to_proof(scenario_id=manifest["id"], goal=goal),
            indent=2,
        ) + "\n")
        print(f"        wrote {proof_path.relative_to(ROOT)}")

    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.solver")
    parser.add_argument("bundles", nargs="*", help="One or more scenario directories.")
    parser.add_argument(
        "--write-proof", action="store_true",
        help="Write solver_proof.json into each bundle on success.",
    )
    args = parser.parse_args(argv)

    if not args.bundles:
        scenarios = ROOT / "scenarios"
        bundles = sorted(p for p in scenarios.iterdir() if p.is_dir())
        if not bundles:
            print("no scenarios found under scenarios/", file=sys.stderr)
            return 1
    else:
        bundles = [Path(b).resolve() for b in args.bundles]

    failed = 0
    for bundle in bundles:
        failed += _run(bundle, write_proof=args.write_proof)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
