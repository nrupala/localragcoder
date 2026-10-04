"""Document lifecycle management.

Handles upload, text extraction, chunking, embedding, and
persistence of documents and their chunks in SQLite.  Also
manages the vector store index for semantic search.

Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from . import db
from . import ingester
from . import vector_store

logger = logging.getLogger(__name__)

CHUNK_SIZE = 512  # words per chunk
CHUNK_OVERLAP = 64


class DocumentManager:
    """Manages document lifecycle — upload, chunk, embed, delete.

    Args:
        db_path: Path to the SQLite database.
        store_path: Path for the vector index files.
    """

    def __init__(self, db_path: str | Path, store_path: str | Path):
        self.db = db.Database(db_path)
        self.vs = vector_store.VectorStore(store_path)

    # ── upload ────────────────────────────────────────────────

    def upload_file(self, file_path: str | Path,
                    title: str | None = None,
                    tags: str | None = None) -> dict:
        """Ingest a file: extract, chunk, embed, persist.

        Args:
            file_path: Path to the file on disk.
            title: Optional display title (defaults to filename).
            tags: Optional comma-separated tags.

        Returns:
            Dict with doc_id, filename, filetype, chunk_count.
        """
        p = Path(file_path)
        result = ingester.ingest_file(
            p, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP
        )
        doc_id = str(uuid.uuid4())
        title = title or p.stem
        filetype = result["filetype"]

        # Persist document in SQLite
        self.db.add_document_full(
            doc_id=doc_id,
            title=title,
            filename=p.name,
            filetype=filetype,
            size_bytes=result["size_bytes"],
            tags=tags or "",
            full_text=result["text"],
        )

        # Persist chunks and embed them
        chunks = result["chunks"]
        vs_items = []
        for i, chunk_text in enumerate(chunks):
            chunk_id = f"{doc_id}_{i}"
            self.db.add_chunk(
                chunk_id=chunk_id,
                doc_id=doc_id,
                index=i,
                text=chunk_text,
            )
            vs_items.append((
                chunk_id,
                chunk_text,
                {"doc_id": doc_id, "index": i, "filename": p.name},
            ))

        if vs_items:
            self.vs.add_items(vs_items)

        return {
            "doc_id": doc_id,
            "filename": p.name,
            "filetype": filetype,
            "chunk_count": len(chunks),
        }

    # ── listing / retrieval ───────────────────────────────────

    def _enrich(self, row: dict | None) -> dict | None:
        if row is None:
            return None
        meta = json.loads(row.get("metadata") or "{}")
        row["title"] = meta.get("title", row.get("filename", ""))
        row["tags"] = meta.get("tags", "")
        return row

    def list_documents(self) -> list[dict]:
        """List all documents with metadata."""
        return [self._enrich(r) for r in self.db.list_documents() if r]

    def get_document(self, doc_id: str) -> dict | None:
        """Get a single document by ID."""
        return self._enrich(self.db.get_document(doc_id))

    def get_chunks(self, doc_id: str) -> list[dict]:
        """Get all chunks for a document."""
        return self.db.get_chunks(doc_id)

    # ── deletion ──────────────────────────────────────────────

    def delete_document(self, doc_id: str) -> bool:
        """Delete a document and its chunks from SQLite and vector store."""
        chunks = self.db.get_chunks(doc_id)
        for ch in chunks:
            self.vs.remove_item(ch["chunk_id"])
        return self.db.delete_document(doc_id)

    # ── search ────────────────────────────────────────────────

    def search_chunks(self, query: str, top_k: int = 5) -> list[dict]:
        """Semantic search over ingested chunks.

        Returns enriched results with doc_id, chunk text, filename.
        """
        results = self.vs.search(query, top_k=top_k)
        enriched = []
        for r in results:
            meta = r.get("metadata", {})
            chunk_id = r["id"]
            doc_id = meta.get("doc_id", "")
            # Pull text from SQLite
            ch = self.db.get_chunk(chunk_id)
            doc = self.get_document(doc_id) if doc_id else None
            enriched.append({
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "index": meta.get("index", -1),
                "filename": meta.get("filename", ""),
                "score": r["score"],
                "text": ch["content"] if ch else "",
                "document_title": doc["title"] if doc else "",
            })
        return enriched
