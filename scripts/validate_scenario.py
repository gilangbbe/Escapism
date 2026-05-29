"""Validate a scenario bundle against the v1 contract.

Usage:
    python -m scripts.validate_scenario scenarios/black_vesper [scenarios/foo ...]

Exits 0 if every bundle validates, 1 otherwise. Prints a one-line summary
per bundle plus a detailed error block for each failure.

The schemas live in :mod:`schemas.v1`. The simulator refuses to load a
bundle whose ``manifest.schema_version`` it does not know about; this
script is the build-time equivalent of that check.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas" / "v1"


def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMAS_DIR / name).read_text())


def _format_errors(errors: list[Any], *, label: str) -> list[str]:
    out: list[str] = []
    for err in errors:
        path = "/".join(str(p) for p in err.absolute_path) or "(root)"
        out.append(f"    [{label}] {path}: {err.message}")
    return out


def validate_bundle(bundle: Path) -> list[str]:
    """Return a list of error strings. Empty list = bundle is valid."""
    errors: list[str] = []

    manifest_path = bundle / "manifest.json"
    if not manifest_path.exists():
        return [f"missing {manifest_path.relative_to(ROOT)}"]
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        return [f"manifest.json is not valid JSON: {exc}"]

    manifest_validator = Draft202012Validator(_load_schema("manifest.schema.json"))
    errors += _format_errors(list(manifest_validator.iter_errors(manifest)), label="manifest.json")

    if manifest.get("schema_version") != 1:
        errors.append(
            f"manifest.schema_version={manifest.get('schema_version')!r}; this validator only knows v1"
        )

    if manifest.get("id") and manifest["id"] != bundle.name:
        errors.append(
            f"manifest.id={manifest['id']!r} does not match directory name {bundle.name!r}"
        )

    world_name = manifest.get("world_initial", "world_initial.json")
    world_path = bundle / world_name
    if not world_path.exists():
        errors.append(f"missing world initial: {world_path.relative_to(ROOT)}")
    else:
        try:
            world = json.loads(world_path.read_text())
            world_validator = Draft202012Validator(
                _load_schema("world_initial.schema.json")
            )
            errors += _format_errors(
                list(world_validator.iter_errors(world)), label=world_name,
            )
        except json.JSONDecodeError as exc:
            errors.append(f"{world_name} is not valid JSON: {exc}")

    corpus_name = manifest.get("game_corpus", "game.jsonl")
    corpus_path = bundle / corpus_name
    if not corpus_path.exists():
        errors.append(f"missing corpus: {corpus_path.relative_to(ROOT)}")
    else:
        doc_validator = Draft202012Validator(_load_schema("game_doc.schema.json"))
        ids_seen: dict[str, int] = {}
        for lineno, raw in enumerate(corpus_path.read_text().splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{corpus_name}:{lineno}: invalid JSON ({exc})")
                continue
            line_errors = list(doc_validator.iter_errors(doc))
            errors += _format_errors(line_errors, label=f"{corpus_name}:{lineno}")
            doc_id = doc.get("id")
            if isinstance(doc_id, str):
                if doc_id in ids_seen:
                    errors.append(
                        f"{corpus_name}:{lineno}: duplicate id {doc_id!r} "
                        f"(first seen on line {ids_seen[doc_id]})"
                    )
                else:
                    ids_seen[doc_id] = lineno

    return errors


def main(argv: list[str]) -> int:
    if not argv:
        # Default: validate every bundle under scenarios/.
        scenarios_root = ROOT / "scenarios"
        bundles = sorted(p for p in scenarios_root.iterdir() if p.is_dir())
        if not bundles:
            print("no scenarios found under scenarios/", file=sys.stderr)
            return 1
    else:
        bundles = [Path(a).resolve() for a in argv]

    failed = 0
    for bundle in bundles:
        errors = validate_bundle(bundle)
        rel = bundle.relative_to(ROOT) if bundle.is_relative_to(ROOT) else bundle
        if errors:
            failed += 1
            print(f"[FAIL] {rel} ({len(errors)} error(s))")
            for line in errors:
                print(line)
        else:
            print(f"[ ok ] {rel}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
