"""SQLite persistence layer for localRAGcoder.

Stores all user-level data: documents, chat sessions, messages,
model configurations, and analytics events.  Documents live here
independently of which model is active — you can swap models
without losing data.

Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)

local = threading.local()


def _get_conn(db_path: str) -> sqlite3.Connection:
    """Return a thread-local connection."""
    if not hasattr(local, "conn") or local.conn is None:
        local.conn = sqlite3.connect(db_path, check_same_thread=False)
        local.conn.row_factory = sqlite3.Row
        local.conn.execute("PRAGMA journal_mode=WAL")
        local.conn.execute("PRAGMA foreign_keys=ON")
    return local.conn


class LocalDB:
    """Persistent SQLite store for all localRAGcoder user data.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(Path(db_path).resolve())
        self._init_schema()

    # ── schema ─────────────────────────────────────────────────

    def _init_schema(self) -> None:
        conn = _get_conn(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id          TEXT PRIMARY KEY,
                filename    TEXT NOT NULL,
                filetype    TEXT NOT NULL,
                size_bytes  INTEGER NOT NULL DEFAULT 0,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                status      TEXT NOT NULL DEFAULT 'uploaded',
                uploaded_at REAL NOT NULL,
                metadata    TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id          TEXT PRIMARY KEY,
                doc_id      TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                content     TEXT NOT NULL,
                tokens_est  INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS chat_sessions (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL DEFAULT 'New Chat',
                model_id    TEXT,
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                metadata    TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS messages (
                id              TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                role            TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
                content         TEXT NOT NULL,
                sources         TEXT DEFAULT '[]',
                tokens_in       INTEGER NOT NULL DEFAULT 0,
                tokens_out      INTEGER NOT NULL DEFAULT 0,
                latency_ms      INTEGER NOT NULL DEFAULT 0,
                feedback        TEXT,
                created_at      REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS model_configs (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL UNIQUE,
                model_id    TEXT NOT NULL,
                temperature REAL NOT NULL DEFAULT 0.7,
                top_p       REAL NOT NULL DEFAULT 0.9,
                max_tokens  INTEGER NOT NULL DEFAULT 2048,
                system_prompt TEXT DEFAULT 'You are a helpful assistant.',
                embedding_model TEXT DEFAULT 'all-MiniLM-L6-v2',
                chunk_size  INTEGER NOT NULL DEFAULT 512,
                chunk_overlap INTEGER NOT NULL DEFAULT 64,
                top_k       INTEGER NOT NULL DEFAULT 5,
                is_active   INTEGER NOT NULL DEFAULT 0,
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS analytics_events (
                id          TEXT PRIMARY KEY,
                event_type  TEXT NOT NULL,
                session_id  TEXT,
                message_id  TEXT,
                model_id    TEXT,
                metric_name TEXT,
                metric_value REAL,
                payload     TEXT DEFAULT '{}',
                created_at  REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rag_evaluations (
                id              TEXT PRIMARY KEY,
                query           TEXT NOT NULL,
                retrieved_docs  TEXT DEFAULT '[]',
                response        TEXT,
                precision       REAL,
                recall          REAL,
                relevance_score REAL,
                latency_ms      INTEGER,
                tokens_used     INTEGER,
                model_id        TEXT,
                created_at      REAL NOT NULL
            );
        """)
        # Schema migrations for new columns
        for mig in [
            "ALTER TABLE rag_evaluations ADD COLUMN user_rating INTEGER",
        ]:
            try:
                conn.execute(mig)
            except Exception:
                pass
        conn.commit()

    # ── documents ──────────────────────────────────────────────

    def add_document(
        self,
        filename: str,
        filetype: str,
        size_bytes: int = 0,
        metadata: dict | None = None,
    ) -> str:
        doc_id = str(uuid.uuid4())
        conn = _get_conn(self.db_path)
        conn.execute(
            "INSERT INTO documents (id,filename,filetype,size_bytes,uploaded_at,metadata) "
            "VALUES (?,?,?,?,?,?)",
            (doc_id, filename, filetype, size_bytes, time.time(),
             json.dumps(metadata or {})),
        )
        conn.commit()
        logger.info("Document added: %s (%s)", doc_id, filename)
        return doc_id

    def get_document(self, doc_id: str) -> dict | None:
        conn = _get_conn(self.db_path)
        row = conn.execute(
            "SELECT * FROM documents WHERE id=?", (doc_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_documents(self) -> list[dict]:
        conn = _get_conn(self.db_path)
        rows = conn.execute(
            "SELECT * FROM documents ORDER BY uploaded_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_document_status(self, doc_id: str, status: str,
                                chunk_count: int = 0) -> None:
        conn = _get_conn(self.db_path)
        conn.execute(
            "UPDATE documents SET status=?, chunk_count=? WHERE id=?",
            (status, chunk_count, doc_id),
        )
        conn.commit()

    def delete_document(self, doc_id: str) -> None:
        conn = _get_conn(self.db_path)
        conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        conn.commit()
        logger.info("Document deleted: %s", doc_id)

    # ── chunks ─────────────────────────────────────────────────

    def add_chunks(self, doc_id: str, chunks: list[str]) -> list[str]:
        conn = _get_conn(self.db_path)
        ids = []
        for i, content in enumerate(chunks):
            cid = str(uuid.uuid4())
            ids.append(cid)
            conn.execute(
                "INSERT INTO chunks (id,doc_id,chunk_index,content,tokens_est) "
                "VALUES (?,?,?,?,?)",
                (cid, doc_id, i, content, len(content.split())),
            )
        conn.commit()
        return ids

    def get_chunks(self, doc_id: str) -> list[dict]:
        conn = _get_conn(self.db_path)
        rows = conn.execute(
            "SELECT * FROM chunks WHERE doc_id=? ORDER BY chunk_index",
            (doc_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_chunks(self) -> list[dict]:
        conn = _get_conn(self.db_path)
        rows = conn.execute(
            "SELECT c.*, d.filename, d.filetype FROM chunks c "
            "JOIN documents d ON c.doc_id = d.id "
            "WHERE d.status = 'ready' "
            "ORDER BY d.uploaded_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── chat sessions ──────────────────────────────────────────

    def create_session(self, model_id: str | None = None,
                       title: str = "New Chat") -> str:
        sid = str(uuid.uuid4())
        now = time.time()
        conn = _get_conn(self.db_path)
        conn.execute(
            "INSERT INTO chat_sessions (id,title,model_id,created_at,updated_at) "
            "VALUES (?,?,?,?,?)",
            (sid, title, model_id, now, now),
        )
        conn.commit()
        return sid

    def list_sessions(self) -> list[dict]:
        conn = _get_conn(self.db_path)
        rows = conn.execute(
            "SELECT * FROM chat_sessions ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_session(self, session_id: str) -> dict | None:
        conn = _get_conn(self.db_path)
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE id=?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def delete_session(self, session_id: str) -> None:
        conn = _get_conn(self.db_path)
        conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM chat_sessions WHERE id=?", (session_id,))
        conn.commit()

    # ── messages ───────────────────────────────────────────────

    def add_message(self, session_id: str, role: str, content: str,
                    sources: list | None = None,
                    tokens_in: int = 0, tokens_out: int = 0,
                    latency_ms: int = 0) -> str:
        mid = str(uuid.uuid4())
        now = time.time()
        conn = _get_conn(self.db_path)
        conn.execute(
            "INSERT INTO messages (id,session_id,role,content,sources,"
            "tokens_in,tokens_out,latency_ms,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (mid, session_id, role, content, json.dumps(sources or []),
             tokens_in, tokens_out, latency_ms, now),
        )
        conn.execute(
            "UPDATE chat_sessions SET updated_at=?, message_count=message_count+1 WHERE id=?",
            (now, session_id),
        )
        conn.commit()
        return mid

    def get_messages(self, session_id: str) -> list[dict]:
        conn = _get_conn(self.db_path)
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_message_feedback(self, message_id: str, feedback: str) -> None:
        conn = _get_conn(self.db_path)
        conn.execute(
            "UPDATE messages SET feedback=? WHERE id=?",
            (feedback, message_id),
        )
        conn.commit()

    # ── model configs ──────────────────────────────────────────

    def save_model_config(self, name: str, model_id: str,
                           **kwargs) -> str:
        conn = _get_conn(self.db_path)
        existing = conn.execute(
            "SELECT id FROM model_configs WHERE name=?", (name,)
        ).fetchone()
        now = time.time()
        data = {
            "model_id": model_id,
            "temperature": kwargs.get("temperature", 0.7),
            "top_p": kwargs.get("top_p", 0.9),
            "max_tokens": kwargs.get("max_tokens", 2048),
            "system_prompt": kwargs.get("system_prompt", ""),
            "embedding_model": kwargs.get("embedding_model", "all-MiniLM-L6-v2"),
            "chunk_size": kwargs.get("chunk_size", 512),
            "chunk_overlap": kwargs.get("chunk_overlap", 64),
            "top_k": kwargs.get("top_k", 5),
            "updated_at": now,
        }
        if existing:
            data["is_active"] = kwargs.get("is_active", 0)
            pairs = ", ".join(f"{k}=?" for k in data)
            vals = list(data.values()) + [existing["id"]]
            conn.execute(
                f"UPDATE model_configs SET {pairs} WHERE id=?", vals
            )
            cfg_id = existing["id"]
        else:
            cfg_id = str(uuid.uuid4())
            data["id"] = cfg_id
            data["name"] = name
            data["created_at"] = now
            data["is_active"] = kwargs.get("is_active", 1)
            cols = ", ".join(data.keys())
            phs = ", ".join("?" for _ in data)
            conn.execute(
                f"INSERT INTO model_configs ({cols}) VALUES ({phs})",
                list(data.values()),
            )
        conn.commit()
        return cfg_id

    def get_active_config(self) -> dict | None:
        conn = _get_conn(self.db_path)
        row = conn.execute(
            "SELECT * FROM model_configs WHERE is_active=1 ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def set_active_config(self, config_id: str) -> None:
        conn = _get_conn(self.db_path)
        conn.execute("UPDATE model_configs SET is_active=0")
        conn.execute(
            "UPDATE model_configs SET is_active=1 WHERE id=?", (config_id,)
        )
        conn.commit()

    def list_configs(self) -> list[dict]:
        conn = _get_conn(self.db_path)
        rows = conn.execute(
            "SELECT * FROM model_configs ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_config(self, config_id: str) -> None:
        conn = _get_conn(self.db_path)
        conn.execute("DELETE FROM model_configs WHERE id=?", (config_id,))
        conn.commit()

    # ── analytics events ───────────────────────────────────────

    def track_event(self, event_type: str, **payload) -> str:
        eid = str(uuid.uuid4())
        conn = _get_conn(self.db_path)
        conn.execute(
            "INSERT INTO analytics_events "
            "(id,event_type,session_id,message_id,model_id,"
            "metric_name,metric_value,payload,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                eid, event_type,
                payload.get("session_id"),
                payload.get("message_id"),
                payload.get("model_id"),
                payload.get("metric_name"),
                payload.get("metric_value"),
                json.dumps(payload),
                time.time(),
            ),
        )
        conn.commit()
        return eid

    def get_analytics(self, event_type: str | None = None,
                       limit: int = 100) -> list[dict]:
        conn = _get_conn(self.db_path)
        if event_type:
            rows = conn.execute(
                "SELECT * FROM analytics_events WHERE event_type=? "
                "ORDER BY created_at DESC LIMIT ?",
                (event_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM analytics_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_rag_evaluations(self, limit: int = 50) -> list[dict]:
        conn = _get_conn(self.db_path)
        rows = conn.execute(
            "SELECT * FROM rag_evaluations ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_rag_evaluation(self, query: str, retrieved_docs: list,
                            response: str, precision: float = 0,
                            recall: float = 0,
                            relevance_score: float = 0,
                            latency_ms: int = 0,
                            tokens_used: int = 0,
                            model_id: str = "") -> str:
        eid = str(uuid.uuid4())
        conn = _get_conn(self.db_path)
        conn.execute(
            "INSERT INTO rag_evaluations "
            "(id,query,retrieved_docs,response,precision,recall,"
            "relevance_score,latency_ms,tokens_used,model_id,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (eid, query, json.dumps(retrieved_docs), response,
             precision, recall, relevance_score, latency_ms,
             tokens_used, model_id, time.time()),
        )
        conn.commit()
        return eid

    # ── analytics reports ──────────────────────────────────────

    def analytics_report(self) -> dict:
        conn = _get_conn(self.db_path)
        total_docs = conn.execute(
            "SELECT COUNT(*) FROM documents"
        ).fetchone()[0]
        total_chunks = conn.execute(
            "SELECT COUNT(*) FROM chunks"
        ).fetchone()[0]
        total_chats = conn.execute(
            "SELECT COUNT(*) FROM chat_sessions"
        ).fetchone()[0]
        total_messages = conn.execute(
            "SELECT COUNT(*) FROM messages"
        ).fetchone()[0]
        total_evals = conn.execute(
            "SELECT COUNT(*) FROM rag_evaluations"
        ).fetchone()[0]
        avg_precision = conn.execute(
            "SELECT AVG(precision) FROM rag_evaluations"
        ).fetchone()[0] or 0
        avg_recall = conn.execute(
            "SELECT AVG(recall) FROM rag_evaluations"
        ).fetchone()[0] or 0
        avg_relevance = conn.execute(
            "SELECT AVG(relevance_score) FROM rag_evaluations"
        ).fetchone()[0] or 0
        avg_latency = conn.execute(
            "SELECT AVG(latency_ms) FROM rag_evaluations"
        ).fetchone()[0] or 0
        feedback_counts = dict(conn.execute(
            "SELECT feedback, COUNT(*) FROM messages WHERE feedback IS NOT NULL GROUP BY feedback"
        ).fetchall())
        model_usage = [
            dict(r) for r in conn.execute(
                "SELECT model_id, COUNT(*) as count, AVG(tokens_out) as avg_tokens "
                "FROM messages WHERE model_id IS NOT NULL GROUP BY model_id"
            ).fetchall()
        ]
        return {
            "documents": {"total": total_docs, "total_chunks": total_chunks},
            "chat": {"total_sessions": total_chats, "total_messages": total_messages},
            "rag_evaluations": {
                "total": total_evals,
                "avg_precision": round(avg_precision, 3),
                "avg_recall": round(avg_recall, 3),
                "avg_relevance_score": round(avg_relevance, 3),
                "avg_latency_ms": round(avg_latency, 1),
            },
            "feedback": feedback_counts,
            "model_usage": model_usage,
        }

    # ── extra document methods ─────────────────────────────────

    def add_document_full(
        self, doc_id: str, title: str, filename: str, filetype: str,
        size_bytes: int = 0, tags: str = "", full_text: str = "",
    ) -> None:
        conn = _get_conn(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO documents "
            "(id,filename,filetype,size_bytes,status,uploaded_at,metadata) "
            "VALUES (?,?,?,?,?,?,?)",
            (doc_id, filename, filetype, size_bytes, "ready", time.time(),
             json.dumps({"title": title, "tags": tags, "full_text": full_text})),
        )
        conn.commit()

    def delete_document(self, doc_id: str) -> bool:
        conn = _get_conn(self.db_path)
        conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        conn.commit()
        return True

    # ── single chunk methods ───────────────────────────────────

    def add_chunk(self, chunk_id: str, doc_id: str, index: int,
                  text: str) -> None:
        conn = _get_conn(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO chunks "
            "(id,doc_id,chunk_index,content,tokens_est) VALUES (?,?,?,?,?)",
            (chunk_id, doc_id, index, text, len(text.split())),
        )
        conn.commit()

    def get_chunk(self, chunk_id: str) -> dict | None:
        conn = _get_conn(self.db_path)
        row = conn.execute(
            "SELECT * FROM chunks WHERE id=?", (chunk_id,)
        ).fetchone()
        return dict(row) if row else None

    # ── chat session aliases ───────────────────────────────────

    def add_chat_session(self, session_id: str, title: str = "New Chat") -> None:
        conn = _get_conn(self.db_path)
        now = time.time()
        conn.execute(
            "INSERT OR REPLACE INTO chat_sessions "
            "(id,title,model_id,created_at,updated_at) VALUES (?,?,?,?,?)",
            (session_id, title, None, now, now),
        )
        conn.commit()

    def get_chat_session(self, session_id: str) -> dict | None:
        return self.get_session(session_id)

    def list_chat_sessions(self) -> list[dict]:
        return self.list_sessions()

    def delete_chat_session(self, session_id: str) -> bool:
        self.delete_session(session_id)
        return True

    # ── message convenience ──────────────────────────────────

    def add_message_simple(self, session_id: str, role: str, content: str,
                           sources_json: str | None = None) -> str:
        sources = json.loads(sources_json) if sources_json else []
        return self.add_message(session_id, role, content, sources=sources)

    # ── analytics event methods ────────────────────────────────

    def add_analytics_event(self, event_id: str, event_type: str,
                            properties: str = "{}",
                            user_id: str = "",
                            session_id: str = "") -> None:
        conn = _get_conn(self.db_path)
        conn.execute(
            "INSERT INTO analytics_events "
            "(id,event_type,session_id,metric_name,payload,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (event_id, event_type, session_id, user_id, properties, time.time()),
        )
        conn.commit()

    def count_analytics_events(self) -> int:
        conn = _get_conn(self.db_path)
        return conn.execute(
            "SELECT COUNT(*) FROM analytics_events"
        ).fetchone()[0] or 0

    def count_rag_evaluations(self) -> int:
        conn = _get_conn(self.db_path)
        return conn.execute(
            "SELECT COUNT(*) FROM rag_evaluations"
        ).fetchone()[0] or 0

    def avg_rag_latency(self) -> float:
        conn = _get_conn(self.db_path)
        return conn.execute(
            "SELECT AVG(latency_ms) FROM rag_evaluations"
        ).fetchone()[0] or 0.0

    def count_events_by_type(self) -> dict:
        conn = _get_conn(self.db_path)
        rows = conn.execute(
            "SELECT event_type, COUNT(*) as cnt FROM analytics_events GROUP BY event_type"
        ).fetchall()
        return {r["event_type"]: r["cnt"] for r in rows}

    def rating_distribution(self) -> dict:
        conn = _get_conn(self.db_path)
        rows = conn.execute(
            "SELECT user_rating, COUNT(*) as cnt FROM rag_evaluations "
            "WHERE user_rating IS NOT NULL GROUP BY user_rating"
        ).fetchall()
        return {str(r["user_rating"]): r["cnt"] for r in rows}

    def recent_analytics_events(self, limit: int = 50) -> list[dict]:
        conn = _get_conn(self.db_path)
        rows = conn.execute(
            "SELECT * FROM analytics_events ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def recent_rag_evaluations(self, limit: int = 20) -> list[dict]:
        return self.get_rag_evaluations(limit)

    # ── RAG evaluation ────────────────────────────────────────

    # ── benchmark queries ────────────────────────────────────

    def model_benchmarks(self) -> list[dict]:
        conn = _get_conn(self.db_path)
        rows = conn.execute("""
            SELECT model_id,
                   COUNT(*) as query_count,
                   ROUND(AVG(latency_ms), 1) as avg_latency_ms,
                   ROUND(AVG(tokens_used), 0) as avg_tokens,
                   ROUND(AVG(user_rating), 2) as avg_rating
            FROM rag_evaluations
            WHERE model_id IS NOT NULL AND model_id != ''
            GROUP BY model_id
            ORDER BY query_count DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def latency_over_time(self, limit: int = 100) -> list[dict]:
        conn = _get_conn(self.db_path)
        rows = conn.execute("""
            SELECT created_at, latency_ms, model_id, query
            FROM rag_evaluations
            WHERE latency_ms > 0
            ORDER BY created_at ASC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def events_over_time(self) -> list[dict]:
        conn = _get_conn(self.db_path)
        rows = conn.execute("""
            SELECT DATE(created_at, 'unixepoch') as day,
                   event_type,
                   COUNT(*) as cnt
            FROM analytics_events
            GROUP BY day, event_type
            ORDER BY day ASC
        """).fetchall()
        return [dict(r) for r in rows]

    def documents_over_time(self) -> list[dict]:
        conn = _get_conn(self.db_path)
        rows = conn.execute("""
            SELECT DATE(uploaded_at, 'unixepoch') as day,
                   COUNT(*) as cnt
            FROM documents
            GROUP BY day
            ORDER BY day ASC
        """).fetchall()
        return [dict(r) for r in rows]

    def add_rag_evaluation_full(
        self, eval_id: str, query: str, retrieved_chunks: str = "[]",
        answer: str = "", latency_ms: float = 0,
        model: str = "", user_rating: int | None = None,
        session_id: str = "",
    ) -> None:
        conn = _get_conn(self.db_path)
        conn.execute(
            "INSERT INTO rag_evaluations "
            "(id,query,retrieved_docs,response,latency_ms,model_id,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (eval_id, query, retrieved_chunks, answer,
             latency_ms, model, time.time()),
        )
        conn.commit()


Database = LocalDB
