"""RAG analytics and user analytics tracking.

Tracks events, measures RAG quality, computes performance metrics,
and generates reports.  All data persisted to SQLite.

Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Optional

from . import db

logger = logging.getLogger(__name__)


class Analytics:
    """Analytics engine for RAG performance and user behavior.

    Args:
        database: Database instance.
    """

    def __init__(self, database: db.Database):
        self.db = database

    # ── event tracking ────────────────────────────────────────

    def track_event(self, event_type: str,
                    properties: dict | None = None,
                    user_id: str | None = None,
                    session_id: str | None = None) -> str:
        """Track a user or system event.

        Args:
            event_type: e.g. "document_uploaded", "chat_message_sent",
                       "rag_query", "app_started", "error_occurred".
            properties: Arbitrary JSON-serialisable key-value data.
            user_id: Optional user identifier.
            session_id: Optional session identifier.

        Returns:
            Event ID.
        """
        event_id = str(uuid.uuid4())
        self.db.add_analytics_event(
            event_id=event_id,
            event_type=event_type,
            properties=json.dumps(properties or {}),
            user_id=user_id or "",
            session_id=session_id or "",
        )
        return event_id

    # ── RAG quality evaluation ────────────────────────────────

    def record_rag_evaluation(self, query: str,
                              retrieved_chunks: list[str],
                              answer: str,
                              latency_ms: float,
                              model: str,
                              user_rating: int | None = None,
                              session_id: str | None = None) -> str:
        """Record a RAG query's performance data.

        Args:
            query: The user's query text.
            retrieved_chunks: List of chunk IDs or texts that were retrieved.
            answer: The LLM's generated answer.
            latency_ms: End-to-end query latency in milliseconds.
            model: Model used.
            user_rating: Optional 1-5 rating.
            session_id: Optional session ID.

        Returns:
            Evaluation ID.
        """
        eval_id = str(uuid.uuid4())
        self.db.add_rag_evaluation_full(
            eval_id=eval_id,
            query=query,
            retrieved_chunks=json.dumps(retrieved_chunks),
            answer=answer,
            latency_ms=latency_ms,
            model=model,
            user_rating=user_rating,
            session_id=session_id or "",
        )
        return eval_id

    # ── reports ───────────────────────────────────────────────

    def get_summary(self) -> dict:
        """High-level analytics summary."""
        total_events = self.db.count_analytics_events()
        total_ratings = self.db.count_rag_evaluations()
        avg_latency = self.db.avg_rag_latency()

        # Count by event type
        event_types = self.db.count_events_by_type()

        # Rating distribution
        rating_dist = self.db.rating_distribution()

        return {
            "total_events": total_events,
            "total_rag_queries": total_ratings,
            "avg_latency_ms": round(avg_latency, 2) if avg_latency else 0,
            "events_by_type": event_types,
            "rating_distribution": rating_dist,
            "timestamp": time.time(),
        }

    def get_recent_events(self, limit: int = 50) -> list[dict]:
        return self.db.recent_analytics_events(limit)

    def get_recent_evaluations(self, limit: int = 20) -> list[dict]:
        return self.db.recent_rag_evaluations(limit)

    def get_benchmark(self) -> dict:
        return {
            "per_model": self.db.model_benchmarks(),
            "latency_over_time": self.db.latency_over_time(200),
            "events_over_time": self.db.events_over_time(),
            "documents_over_time": self.db.documents_over_time(),
        }

    # ── convenience wrappers ──────────────────────────────────

    def track_rag_query(self, query: str, latency_ms: float,
                        model: str, session_id: str | None = None) -> str:
        return self.track_event(
            "rag_query",
            {"query": query, "latency_ms": latency_ms, "model": model},
            session_id=session_id,
        )

    def track_document_upload(self, filename: str,
                              filetype: str, size_bytes: int,
                              chunk_count: int) -> str:
        return self.track_event(
            "document_uploaded",
            {"filename": filename, "filetype": filetype,
             "size_bytes": size_bytes, "chunk_count": chunk_count},
        )

    def track_error(self, error_type: str, details: str) -> str:
        return self.track_event(
            "error_occurred",
            {"error_type": error_type, "details": details},
        )

    def track_app_start(self) -> str:
        return self.track_event("app_started", {"version": "1.0.0"})
