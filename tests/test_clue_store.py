"""Tests for ClueStore — keyword fallback always, Chroma path when available."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from server.memory.clue_store import ClueStore


SAMPLE_DOCS = [
    {"id": "loc.brig", "kind": "location", "scope": ["act1"],
     "title": "The Brig",
     "text": "A small iron cell on the lower deck where Mira and the crew are held."},
    {"id": "item.keyring", "kind": "item", "scope": ["act1"],
     "title": "Hal's keyring",
     "text": "An iron ring of keys hanging from Crooked Hal's belt outside the cell."},
    {"id": "puzzle.sedate_hal", "kind": "puzzle", "scope": ["act1"],
     "title": "Sedate Crooked Hal",
     "text": "Slip a sleeping draught into Hal's rum mug while he dozes at the desk."},
    {"id": "loc.deck", "kind": "location", "scope": ["act2"],
     "title": "The Upper Deck",
     "text": "Salt wind and rigging. The watch paces here in the small hours."},
]


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch) -> Path:
    """Write sample docs to a temp JSONL and point Chroma at a fresh tmp dir."""
    path = tmp_path / "game.jsonl"
    path.write_text("\n".join(json.dumps(d) for d in SAMPLE_DOCS))

    # Isolate Chroma to a per-test tmp dir.
    monkeypatch.setattr("server.memory.clue_store.CHROMA_DIR", tmp_path / "chroma")
    return path


# ------------------------------------------------------------- loading
class TestLoading:
    def test_loads_all_documents(self, corpus, monkeypatch):
        monkeypatch.setenv("USE_CHROMA", "0")
        # Re-import settings to pick up env (or just construct with chroma disabled)
        from server import config as cfg
        cfg.settings.use_chroma = False
        store = ClueStore(corpus)
        assert len(store.docs) == len(SAMPLE_DOCS)

    def test_skips_malformed_lines(self, tmp_path, monkeypatch):
        from server import config as cfg
        cfg.settings.use_chroma = False
        path = tmp_path / "bad.jsonl"
        path.write_text('{"id": "ok", "kind": "lore", "text": "fine"}\nnot json\n{"id": "ok2", "text": "also fine"}')
        store = ClueStore(path)
        assert len(store.docs) == 2

    def test_by_scope(self, corpus, monkeypatch):
        from server import config as cfg
        cfg.settings.use_chroma = False
        store = ClueStore(corpus)
        act1 = store.by_scope("act1")
        ids = {d["id"] for d in act1}
        assert "loc.brig" in ids and "item.keyring" in ids and "loc.deck" not in ids


# ------------------------------------------------------------- keyword fallback
class TestKeywordFallback:
    @pytest.fixture
    def store(self, corpus, monkeypatch):
        from server import config as cfg
        cfg.settings.use_chroma = False
        return ClueStore(corpus)

    def test_returns_relevant_doc(self, store):
        results = store.query("keyring belt outside", k=3, scope="act1")
        assert len(results) >= 1
        assert results[0]["id"] == "item.keyring"

    def test_respects_scope(self, store):
        results = store.query("deck salt wind watch", k=5, scope="act1")
        # act2 doc must not appear when scope=act1
        assert all("act2" not in (d.get("scope") or []) for d in results)

    def test_empty_query_returns_empty(self, store):
        assert store.query("", k=3) == []

    def test_no_match_returns_empty(self, store):
        assert store.query("zzzzzzz qqqqqqq", k=3, scope="act1") == []

    def test_ranks_by_score(self, store):
        results = store.query("sleeping draught rum mug", k=4, scope="act1")
        assert results[0]["id"] == "puzzle.sedate_hal"


# ------------------------------------------------------------- chroma path (optional)
@pytest.mark.skipif(
    pytest.importorskip("chromadb", reason="chromadb not installed") is None,
    reason="chromadb not installed",
)
class TestChromaPath:
    def test_chroma_index_built_and_queried(self, corpus, monkeypatch):
        from server import config as cfg
        cfg.settings.use_chroma = True
        store = ClueStore(corpus)
        # If chroma actually initialised:
        if store._collection is None:
            pytest.skip("chroma init failed in this environment")
        results = store.query("keys ring hanging from belt", k=3)
        assert any(d["id"] == "item.keyring" for d in results)
