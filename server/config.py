"""Environment-driven configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RUNS_DIR = DATA_DIR / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR = DATA_DIR / "chroma"
SCENARIOS_DIR = ROOT / "scenarios"
SCHEMAS_DIR = ROOT / "schemas"


_DEFAULT_SCENARIO = "black_vesper"


def _scenario_id() -> str:
    return os.getenv("SCENARIO", _DEFAULT_SCENARIO)


def scenario_dir(scenario_id: str | None = None) -> Path:
    """Resolve the on-disk directory for the active scenario bundle."""
    return SCENARIOS_DIR / (scenario_id or _scenario_id())


@dataclass
class Settings:
    backend: str = os.getenv("LLM_BACKEND", "mock")  # mock | ollama
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    # Active scenario bundle (directory name under scenarios/).
    scenario: str = _scenario_id()
    # Default to qwen2.5:7b for both agents \u2014 3B-class models drift on state
    # tracking in long (~30+ tick) runs. Override per-agent via PLAYER_MODEL /
    # GM_MODEL when you want to experiment.
    player_model: str = os.getenv("PLAYER_MODEL", "qwen2.5:7b")
    gm_model: str = os.getenv("GM_MODEL", "qwen2.5:7b")
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    # Per-agent temperature overrides. Adjudication is a low-creativity task;
    # narration benefits from slightly warmer sampling. Defaults fall back to
    # LLM_TEMPERATURE if unset.
    player_temperature: float = float(
        os.getenv("PLAYER_TEMPERATURE", os.getenv("LLM_TEMPERATURE", "0.3"))
    )
    gm_temperature: float = float(
        os.getenv("GM_TEMPERATURE", os.getenv("LLM_TEMPERATURE", "0.15"))
    )
    # Optional integer seed for reproducible Ollama runs. Unset = no seed.
    seed: int | None = (
        int(os.environ["LLM_SEED"]) if os.getenv("LLM_SEED", "").strip() else None
    )
    use_chroma: bool = os.getenv("USE_CHROMA", "1") != "0"
    chroma_collection: str = f"escapism_clues__{_scenario_id()}"
    tick_delay_seconds: float = float(os.getenv("TICK_DELAY", "0.8"))
    max_ticks: int = int(os.getenv("MAX_TICKS", "60"))
    # Phase 4 cognition knobs.
    reflect_every: int = int(os.getenv("REFLECT_EVERY", "5"))  # 0 disables reflection
    salty_tier_step: int = int(os.getenv("SALTY_TIER_STEP", "3"))  # repeats per tier escalation


settings = Settings()
