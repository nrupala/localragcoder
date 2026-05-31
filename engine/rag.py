"""RAG query engine.

Retrieves relevant chunks for a query, builds a context prompt,
calls the LLM, and returns the answer with inline citations.

Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from . import models_manager as mm
from . import document_manager

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_TEMPLATE = """You are a helpful RAG assistant. Answer the user's question
based ONLY on the provided context. If the context doesn't contain
enough information, say so — do not make up information.

Cite your sources by referencing the document filename and chunk
index in parentheses, like: (source: report.pdf, chunk 3).

Context:
{context}
"""


class RAGEngine:
    """Retrieval-Augmented Generation engine.

    Args:
        doc_mgr: DocumentManager instance.
        model: Ollama model name (default: "qwen3:8b").
        system_template: Optional custom system prompt template.
            Must contain {context}.
        top_k: Number of chunks to retrieve.
    """

    def __init__(self, doc_mgr: document_manager.DocumentManager,
                 model: str = "qwen3:8b",
                 system_template: str | None = None,
                 top_k: int = 5):
        self.doc_mgr = doc_mgr
        self.model = model
        self.system_template = system_template or DEFAULT_SYSTEM_TEMPLATE
        self.top_k = top_k

    def retrieve(self, query: str, top_k: int | None = None) -> list[dict]:
        """Retrieve relevant chunks for a query."""
        k = top_k or self.top_k
        return self.doc_mgr.search_chunks(query, top_k=k)

    def _build_context(self, chunks: list[dict]) -> str:
        """Build a context string from retrieved chunks."""
        parts = []
        for i, ch in enumerate(chunks):
            source = f"[{i+1}] (source: {ch['filename'] or 'unknown'}, chunk {ch['index']})"
            parts.append(f"{source}\n{ch['text']}")
        return "\n\n".join(parts)

    def query(self, query: str, top_k: int | None = None,
              options: dict | None = None) -> dict:
        """Full RAG query: retrieve, build context, generate.

        Args:
            query: The user's question.
            top_k: Override default top_k.
            options: Ollama options (temperature, top_p, etc).

        Returns:
            Dict with keys: answer, sources, chunks_raw.
            For reasoning models (qwen3, deepseek-r1, etc), answer
            may contain <thinking>...</thinking> tags.
        """
        chunks = self.retrieve(query, top_k)
        context = self._build_context(chunks)
        system_prompt = self.system_template.format(context=context)

        try:
            result = mm.generate_text(
                model=self.model,
                prompt=query,
                system=system_prompt,
                options=options,
            )
        except (ConnectionError, ValueError) as e:
            return {"answer": f"[LLM error: {e}]", "sources": [], "chunks_raw": chunks}

        raw_response = result.get("response", "")
        answer = raw_response

        sources = list({
            f"{ch['filename']} (chunk {ch['index']})"
            for ch in chunks
        })

        return {
            "answer": answer,
            "sources": sources,
            "chunks_raw": chunks,
        }

    @property
    def embedding_model(self) -> str:
        return self.doc_mgr.vs.embed.__name__ if hasattr(self.doc_mgr.vs, 'embed') else "all-MiniLM-L6-v2"
