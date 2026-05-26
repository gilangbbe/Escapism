"""Clue store. Wraps ChromaDB with a tag-based fallback so the system still runs
when chromadb is not installed or embeddings cannot be computed."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import settings, CHROMA_DIR, DATA_DIR


class ClueStore:
    """Vector-search clue retriever with a keyword fallback."""

    def __init__(self, jsonl_path: Path) -> None:
        self.jsonl_path = jsonl_path
        self.docs: list[dict[str, Any]] = []
        self._load_jsonl()
        self._collection = None
        if settings.use_chroma:
            try:
                self._init_chroma()
            except Exception as exc:  # noqa: BLE001
                print(f"[clue_store] Chroma unavailable, falling back to keyword search: {exc}")
                self._collection = None

    # --------------------------------------------------------------- loading
    def _load_jsonl(self) -> None:
        for line in self.jsonl_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                self.docs.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"[clue_store] skipped malformed line: {exc}")

    def _init_chroma(self) -> None:
        import chromadb  # type: ignore

        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        # Use chromadb's default embedder (ONNX MiniLM) so we don't depend on Ollama embeddings.
        collection = client.get_or_create_collection(settings.chroma_collection)
        if collection.count() == 0:
            ids = [d["id"] for d in self.docs]
            metadatas = [{k: _stringify(v) for k, v in d.items() if k != "text"} for d in self.docs]
            documents = [self._compose_text(d) for d in self.docs]
            collection.add(ids=ids, documents=documents, metadatas=metadatas)
            print(f"[clue_store] indexed {len(ids)} clue documents into Chroma")
        self._collection = collection

    @staticmethod
    def _compose_text(doc: dict[str, Any]) -> str:
        bits = [doc.get("title", ""), doc.get("text", "")]
        if doc.get("kind"):
            bits.insert(0, f"[{doc['kind']}]")
        return " | ".join(b for b in bits if b)

    # --------------------------------------------------------------- query
    def query(self, prompt: str, *, k: int = 6, scope: str | None = None) -> list[dict[str, Any]]:
        if self._collection is not None:
            try:
                where = {"scope": {"$in": [scope]}} if scope else None  # may not match list scopes
                result = self._collection.query(query_texts=[prompt], n_results=k)
                ids = result.get("ids", [[]])[0]
                return [self._by_id(i) for i in ids if self._by_id(i)]
            except Exception as exc:  # noqa: BLE001
                print(f"[clue_store] chroma query failed, falling back: {exc}")
        return self._keyword_fallback(prompt, k=k, scope=scope)

    def get(self, ids: list[str]) -> list[dict[str, Any]]:
        return [d for d in self.docs if d["id"] in ids]

    def by_scope(self, scope: str) -> list[dict[str, Any]]:
        return [d for d in self.docs if scope in (d.get("scope") or [])]

    def _by_id(self, doc_id: str) -> dict[str, Any] | None:
        for d in self.docs:
            if d["id"] == doc_id:
                return d
        return None

    def _keyword_fallback(self, prompt: str, *, k: int, scope: str | None) -> list[dict[str, Any]]:
        tokens = {t.strip(".,'\"").lower() for t in prompt.split() if len(t) > 3}
        scored: list[tuple[int, dict[str, Any]]] = []
        for d in self.docs:
            if scope and scope not in (d.get("scope") or []):
                continue
            text = self._compose_text(d).lower()
            score = sum(1 for t in tokens if t in text)
            if score:
                scored.append((score, d))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [d for _, d in scored[:k]]


def _stringify(v: Any) -> str:
    if isinstance(v, (list, tuple)):
        return ",".join(str(x) for x in v)
    if isinstance(v, (dict,)):
        return json.dumps(v)
    return str(v)
