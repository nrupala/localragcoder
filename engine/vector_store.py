"""Vector store — embeddings + similarity search.

Uses sentence-transformers for embeddings and numpy for fast
cosine-similarity search.  No external vector DB dependency;
everything runs in-process.

Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import threading
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    from sentence_transformers import SentenceTransformer
    ST_AVAILABLE = True
except ImportError:
    ST_AVAILABLE = False

_local = threading.local()


def _get_encoder(model_name: str = "all-MiniLM-L6-v2"):
    """Get or create a thread-local sentence encoder."""
    key = f"_encoder_{model_name}"
    if not hasattr(_local, key) or getattr(_local, key) is None:
        if ST_AVAILABLE:
            setattr(_local, key, SentenceTransformer(model_name))
        else:
            setattr(_local, key, None)
    return getattr(_local, key)


class VectorStore:
    """Lightweight in-process vector store.

    Stores chunk embeddings as numpy arrays and serialises to disk
    as a pickled dict.  All operations are thread-safe.

    Args:
        store_path: Directory path for the vector index files.
    """

    def __init__(self, store_path: str | Path):
        self.store_path = Path(store_path).resolve()
        self.store_path.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._vectors: dict[str, np.ndarray] = {}
        self._metadata: dict[str, dict] = {}
        self._load_index()

    # ── index persistence ──────────────────────────────────────

    def _index_path(self) -> Path:
        return self.store_path / "vectors.pkl"

    def _meta_path(self) -> Path:
        return self.store_path / "metadata.pkl"

    def _load_index(self) -> None:
        ip = self._index_path()
        mp = self._meta_path()
        if ip.exists():
            with open(ip, "rb") as f:
                self._vectors = pickle.load(f)
        if mp.exists():
            with open(mp, "rb") as f:
                self._metadata = pickle.load(f)
        logger.info(
            "VectorStore loaded: %d vectors", len(self._vectors)
        )

    def _save_index(self) -> None:
        with self._lock:
            with open(self._index_path(), "wb") as f:
                pickle.dump(self._vectors, f)
            with open(self._meta_path(), "wb") as f:
                pickle.dump(self._metadata, f)

    # ── embedding ──────────────────────────────────────────────

    def embed(self, texts: list[str],
              model_name: str = "all-MiniLM-L6-v2") -> np.ndarray:
        """Convert a list of texts to embedding vectors."""
        encoder = _get_encoder(model_name)
        if encoder is None:
            logger.warning(
                "sentence-transformers not installed — using random embeddings"
            )
            return np.random.rand(len(texts), 384).astype(np.float32)
        return encoder.encode(texts, normalize_embeddings=True).astype(np.float32)

    # ── CRUD ───────────────────────────────────────────────────

    def add_item(self, item_id: str, text: str,
                 metadata: dict | None = None,
                 model_name: str = "all-MiniLM-L6-v2") -> None:
        """Embed text and store it in the index."""
        vec = self.embed([text], model_name)[0]
        with self._lock:
            self._vectors[item_id] = vec
            self._metadata[item_id] = metadata or {}
        self._save_index()

    def add_items(self, items: list[tuple[str, str, dict]],
                   model_name: str = "all-MiniLM-L6-v2") -> None:
        """Batch add multiple (id, text, metadata) items."""
        texts = [t[1] for t in items]
        vecs = self.embed(texts, model_name)
        with self._lock:
            for (item_id, _, meta), vec in zip(items, vecs):
                self._vectors[item_id] = vec
                self._metadata[item_id] = meta
        self._save_index()

    def remove_item(self, item_id: str) -> None:
        with self._lock:
            self._vectors.pop(item_id, None)
            self._metadata.pop(item_id, None)
        self._save_index()

    def clear(self) -> None:
        with self._lock:
            self._vectors.clear()
            self._metadata.clear()
        self._save_index()

    # ── search ─────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 5,
               model_name: str = "all-MiniLM-L6-v2") -> list[dict]:
        """Semantic search — return top_k results with scores."""
        if not self._vectors:
            return []
        qvec = self.embed([query], model_name)[0]
        ids = list(self._vectors.keys())
        mat = np.array([self._vectors[i] for i in ids], dtype=np.float32)
        scores = mat @ qvec  # cosine similarity (normalized)
        top_idx = np.argsort(scores)[-top_k:][::-1]
        results = []
        for idx in top_idx:
            iid = ids[idx]
            results.append({
                "id": iid,
                "score": float(scores[idx]),
                "metadata": self._metadata.get(iid, {}),
            })
        return results

    # ── introspection ──────────────────────────────────────────

    @property
    def size(self) -> int:
        return len(self._vectors)

    def get_metadata(self, item_id: str) -> dict | None:
        return self._metadata.get(item_id)
