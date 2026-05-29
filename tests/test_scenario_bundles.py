"""Validate every bundle under scenarios/ against the v1 contract."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_scenario import validate_bundle

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = sorted(p for p in (ROOT / "scenarios").iterdir() if p.is_dir())


@pytest.mark.parametrize("bundle", SCENARIOS, ids=lambda p: p.name)
def test_scenario_bundle_validates(bundle: Path) -> None:
    errors = validate_bundle(bundle)
    assert not errors, "\n".join([f"{bundle.name}:"] + errors)


def test_black_vesper_is_present() -> None:
    """Black Vesper is the regression fixture; it must always be shipped."""
    assert (ROOT / "scenarios" / "black_vesper" / "manifest.json").exists()
