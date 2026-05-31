"""Chat session management with streaming support.

Wraps the RAG engine in a chat interface that maintains message
history, supports multiple sessions, and streams responses via
SSE for a smooth UI experience.

Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Optional

from . import db
from . import models_manager as mm
from .rag import RAGEngine

logger = logging.getLogger(__name__)


class ChatSession:
    """A single chat session with message history.

    Args:
        session_id: Unique session identifier.
        title: Optional display title.
    """

    def __init__(self, session_id: str, title: str = "New Chat"):
        self.session_id = session_id
        self.title = title
        self.created_at = time.time()
        self.messages: list[dict] = []

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "message_count": len(self.messages),
            "messages": self.messages,
        }

    def add_message(self, role: str, content: str,
                    sources: list[str] | None = None) -> dict:
        msg = {
            "role": role,
            "content": content,
            "timestamp": time.time(),
        }
        if sources:
            msg["sources"] = sources
        self.messages.append(msg)
        return msg


class ChatManager:
    """Manages multiple chat sessions backed by SQLite.

    Args:
        rag_engine: RAGEngine instance.
        database: Database instance for persistence.
    """

    def __init__(self, rag_engine: RAGEngine, database: db.Database):
        self.rag = rag_engine
        self.db = database
        self._sessions: dict[str, ChatSession] = {}

    # ── session lifecycle ─────────────────────────────────────

    def create_session(self, title: str = "New Chat") -> ChatSession:
        session_id = str(uuid.uuid4())
        session = ChatSession(session_id, title)
        self._sessions[session_id] = session
        # Persist to SQLite
        self.db.add_chat_session(session_id, title)
        return session

    def get_session(self, session_id: str) -> ChatSession | None:
        if session_id in self._sessions:
            return self._sessions[session_id]

        # Load from SQLite
        row = self.db.get_chat_session(session_id)
        if row:
            session = ChatSession(session_id, row.get("title", "Chat"))
            session.created_at = row.get("created_at", time.time())
            # Load messages
            msgs = self.db.get_messages(session_id)
            session.messages = msgs
            self._sessions[session_id] = session
            return session
        return None

    def list_sessions(self) -> list[dict]:
        rows = self.db.list_chat_sessions()
        # Merge with in-memory sessions
        seen = set()
        result = []
        for r in rows:
            seen.add(r["session_id"])
            result.append(r)
        for sid, s in self._sessions.items():
            if sid not in seen:
                result.append({
                    "session_id": sid,
                    "title": s.title,
                    "created_at": s.created_at,
                    "message_count": len(s.messages),
                })
        return sorted(result, key=lambda x: x["created_at"], reverse=True)

    def delete_session(self, session_id: str) -> bool:
        self._sessions.pop(session_id, None)
        return self.db.delete_chat_session(session_id)

    # ── messaging ─────────────────────────────────────────────

    def send_message(self, session_id: str, text: str,
                     use_rag: bool = True,
                     options: dict | None = None) -> dict:
        """Send a message, run RAG or direct LLM, return response.

        Args:
            session_id: Target session.
            text: User message.
            use_rag: If True, use RAG retrieval; otherwise direct LLM.
            options: Ollama options.

        Returns:
            Dict with role, content, sources (if RAG), session_id.
        """
        session = self.get_session(session_id)
        if session is None:
            return {"error": f"Session not found: {session_id}"}

        # Save user message
        user_msg = session.add_message("user", text)
        self.db.add_message_simple(session_id, "user", text)

        # Build conversation history
        history = []
        for msg in session.messages[:-1]:  # exclude current user msg
            history.append({
                "role": msg["role"],
                "content": msg.get("content", ""),
            })

        if use_rag:
            result = self.rag.query(text, options=options)
            answer = result["answer"]
            sources = result["sources"]
        else:
            try:
                resp = mm.chat_completion(
                    model=self.rag.model,
                    messages=history + [{"role": "user", "content": text}],
                    options=options,
                )
                answer = resp.get("message", {}).get("content", "")
            except (ConnectionError, ValueError) as e:
                answer = f"[LLM error: {e}]"
            sources = []

        # Save assistant message
        assistant_msg = session.add_message("assistant", answer, sources or None)
        self.db.add_message_simple(session_id, "assistant", answer,
                                   json.dumps(sources) if sources else None)

        return {
            "session_id": session_id,
            "role": "assistant",
            "content": answer,
            "sources": sources,
        }

    def stream_message(self, session_id: str, text: str,
                       use_rag: bool = True,
                       options: dict | None = None):
        """Generator that streams the response and yields SSE chunks.

        Each yield is a dict with keys: type ("chunk" | "done" | "error"),
        content, sources (on done).
        """
        session = self.get_session(session_id)
        if session is None:
            yield {"type": "error", "content": f"Session not found: {session_id}"}
            return

        # Save user message
        session.add_message("user", text)
        self.db.add_message_simple(session_id, "user", text)

        # Build history
        history = [{"role": m["role"], "content": m.get("content", "")}
                   for m in session.messages[:-1]]

        if use_rag:
            chunks = self.rag.retrieve(text)
            context = self.rag._build_context(chunks)
            system = self.rag.system_template.format(context=context)
            sources = list({
                f"{ch['filename']} (chunk {ch['index']})"
                for ch in chunks
            })
        else:
            system = None
            sources = []

        try:
            stream_resp = mm.generate_text(
                model=self.rag.model,
                prompt=text,
                system=system,
                stream=True,
                options=options,
            )
            raw_stream = stream_resp.get("stream")
            if raw_stream is None:
                yield {"type": "error", "content": "No stream returned"}
                return

            full_response = []
            for line in raw_stream:
                chunk = json.loads(line.decode())
                if "error" in chunk:
                    yield {"type": "error", "content": chunk["error"]}
                    return
                content = chunk.get("response", "")
                full_response.append(content)
                yield {"type": "chunk", "content": content}

            answer = "".join(full_response)
        except Exception as e:
            yield {"type": "error", "content": str(e)}
            return

        # Save assistant message
        session.add_message("assistant", answer, sources or None)
        self.db.add_message_simple(session_id, "assistant", answer,
                                   json.dumps(sources) if sources else None)

        yield {"type": "done", "content": answer, "sources": sources}
