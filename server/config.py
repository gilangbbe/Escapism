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


@dataclass
class Settings:
    backend: str = os.getenv("LLM_BACKEND", "mock")  # mock | ollama
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    player_model: str = os.getenv("PLAYER_MODEL", "llama3.2")
    gm_model: str = os.getenv("GM_MODEL", "llama3.2")
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    # Optional integer seed for reproducible Ollama runs. Unset = no seed.
    seed: int | None = (
        int(os.environ["LLM_SEED"]) if os.getenv("LLM_SEED", "").strip() else None
    )
    use_chroma: bool = os.getenv("USE_CHROMA", "1") != "0"
    chroma_collection: str = "escapism_clues"
    tick_delay_seconds: float = float(os.getenv("TICK_DELAY", "0.8"))
    max_ticks: int = int(os.getenv("MAX_TICKS", "60"))
    # Phase 4 cognition knobs.
    reflect_every: int = int(os.getenv("REFLECT_EVERY", "5"))  # 0 disables reflection
    salty_tier_step: int = int(os.getenv("SALTY_TIER_STEP", "3"))  # repeats per tier escalation


settings = Settings()
