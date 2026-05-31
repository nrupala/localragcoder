"""Web server — exposes the RAG engine over HTTP.

Binds the localRAGcoder engine to a lightweight HTTP API so the PWA
frontend can chat, manage documents, configure models, and view
analytics from a browser.

Endpoints:
  Chat:
    GET  /api/chats              → list sessions
    POST /api/chats              → create session
    GET  /api/chats/:id/messages → get messages
    POST /api/chats/:id/stream   → stream response (SSE)

  Documents:
    GET  /api/documents          → list documents
    POST /api/documents/upload   → upload file(s)
    DELETE /api/documents/:id    → delete document

  Models:
    GET  /api/models             → list Ollama models
    POST /api/models/select      → set active model
    POST /api/models/pull        → pull a model

  Analytics:
    GET  /api/analytics/summary  → summary stats
    GET  /api/analytics/events   → recent events

  Graph (legacy):
    GET  /api/stats              → graph statistics
    POST /api/ingest             → ingest text into graph
    POST /api/relate             → create relationship
    GET  /api/nodes              → list all graph nodes
    GET  /api/edges              → list all graph edges
    GET  /api/export/json        → export graph as JSON
    GET  /api/export/graphml     → export graph as GraphML

Version: 1.0.0
"""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import tempfile
import time
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from engine.main import GraphResidentEngine
from engine.db import LocalDB, Database
from engine.document_manager import DocumentManager
from engine.rag import RAGEngine
from engine.chat import ChatManager
from engine.analytics import Analytics
from engine import models_manager as mm

logger = logging.getLogger("engine.server")

HERE = Path(__file__).resolve().parent
PWA_DIR = HERE.parent / "packaging" / "pwa"
DB_PATH = HERE.parent / "data" / "lrag.db"
STORE_PATH = HERE.parent / "data" / "vectors"

FALLBACK_PWA: str | None = None
_server_start_time: float = 0.0


def _load_fallback_pwa() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>localRAGcoder</title><style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,sans-serif;background:#1a1a2e;color:#eee;display:flex;justify-content:center;padding:2rem}
#app{max-width:640px;width:100%}
h1{font-size:1.8rem;margin-bottom:.25rem}
p{color:#888;margin-bottom:1.5rem}
textarea{min-height:120px;padding:.75rem;border-radius:8px;border:1px solid #333;background:#16213e;color:#eee;font-family:monospace;width:100%}
button{padding:.6rem 1.2rem;border:none;border-radius:6px;background:#0f3460;color:#eee;font-size:.95rem;cursor:pointer;margin-right:.5rem;margin-top:.5rem}
button:hover{background:#1a5276}
pre{margin-top:1rem;padding:.75rem;background:#0d1b2a;border-radius:6px;min-height:60px;font-size:.85rem;white-space:pre-wrap}
</style></head>
<body><div id="app">
<h1>localRAGcoder</h1><p>Local RAG Engine</p>
<textarea id="input" placeholder="Enter text..."></textarea>
<div>
<button onclick="fetch('/api/stats').then(r=>r.text()).then(t=>document.getElementById('output').textContent=t)">Stats</button>
</div>
<pre id="output">Ready.</pre>
</div></body></html>"""


class EngineHandler(BaseHTTPRequestHandler):
    engine: GraphResidentEngine | None = None
    doc_mgr: DocumentManager | None = None
    rag: RAGEngine | None = None
    chat_mgr: ChatManager | None = None
    analytics: Analytics | None = None

    # ── helpers ───────────────────────────────────────────────

    def _send_json(self, data: Any, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, default=str).encode())

    def _send_text(self, text: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(text.encode())

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_text("Not Found", 404)
            return
        mime, _ = mimetypes.guess_type(str(path))
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        with open(str(path), "rb") as f:
            self.wfile.write(f.read())

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode())

    def _read_multipart(self) -> list[tuple[str, bytes, str]]:
        """Parse multipart/form-data. Returns list of (filename, data, field_name)."""
        ct = self.headers.get("Content-Type", "")
        boundary = None
        for part in ct.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[9:].strip('"')
                break
        if not boundary:
            return []

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        parts = []
        for block in raw.split(("--" + boundary).encode()):
            if block in (b"--\r\n", b"--\n", b"--", b"", b"\r\n", b"\n"):
                continue
            idx = block.find(b"\r\n\r\n")
            if idx == -1:
                idx = block.find(b"\n\n")
            if idx == -1:
                continue
            headers_raw = block[:idx].decode("utf-8", errors="replace")
            data = block[idx + 2:].strip(b"\r\n").strip(b"\n")
            # Strip trailing boundary markers
            if data.endswith(b"\r\n--"):
                data = data[:-4]
            elif data.endswith(b"\n--"):
                data = data[:-3]
            elif data.endswith(b"--"):
                data = data[:-2]

            filename = ""
            content_disp = ""
            for hdr in headers_raw.split("\r\n"):
                hdr = hdr.strip()
                if hdr.lower().startswith("content-disposition:"):
                    content_disp = hdr
                    for seg in hdr.split(";"):
                        seg = seg.strip()
                        if seg.startswith('filename="'):
                            filename = seg[9:-1]
                        elif seg.startswith("filename="):
                            filename = seg[9:]
            if data.strip():
                parts.append((filename, data, content_disp))
        return parts

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - %s", self.client_address[0], fmt % args)

    # ── routing ───────────────────────────────────────────────

    def _route(self, method: str, parts: list[str]) -> None:
        # Serve PWA at root
        if method == "GET" and parts == [""]:
            index = PWA_DIR / "index.html"
            if index.exists():
                self._send_file(index)
            else:
                self._send_text(FALLBACK_PWA, 200)
            return

        if not parts or parts[0] != "api":
            self._send_text("Not Found", 404)
            return

        sub = parts[1:] if len(parts) > 1 else []

        # ── Health ────────────────────────────────────────────
        if method == "GET" and sub == ["health"]:
            ollama_ok = False
            models = []
            try:
                models = mm.list_ollama_models()
                ollama_ok = True
            except Exception:
                pass
            self._send_json({
                "status": "ok",
                "ollama": ollama_ok,
                "ollama_models": len(models),
                "db_docs": len(self.doc_mgr.list_documents()) if self.doc_mgr else 0,
                "version": "1.0.0",
                "uptime": time.time() - _server_start_time,
            })

        # ── Chat ──────────────────────────────────────────────
        if method == "GET" and sub == ["chats"]:
            self._send_json(self.chat_mgr.list_sessions())

        elif method == "POST" and sub == ["chats"]:
            body = self._read_body()
            session = self.chat_mgr.create_session(body.get("title", "New Chat"))
            self._send_json(session.to_dict())

        elif method == "GET" and len(sub) == 3 and sub[0] == "chats" and sub[2] == "messages":
            sid = sub[1]
            session = self.chat_mgr.get_session(sid)
            if session:
                self._send_json(session.messages)
            else:
                self._send_json({"error": "Session not found"}, 404)

        elif method == "POST" and len(sub) == 3 and sub[0] == "chats" and sub[2] == "stream":
            sid = sub[1]
            body = self._read_body()
            text = body.get("message", "")
            use_rag = body.get("use_rag", True)
            self._handle_stream(sid, text, use_rag)

        elif method == "DELETE" and len(sub) == 2 and sub[0] == "chats":
            sid = sub[1]
            ok = self.chat_mgr.delete_session(sid)
            self._send_json({"ok": ok})

        # ── Documents ─────────────────────────────────────────
        elif method == "GET" and sub == ["documents"]:
            docs = self.doc_mgr.list_documents()
            self._send_json(docs)

        elif method == "POST" and sub == ["documents", "upload"]:
            files = self._read_multipart()
            results = []
            for filename, data, _ in files:
                if not filename:
                    continue
                tmp = Path(tempfile.gettempdir()) / f"lrag_{int(time.time()*1e6)}_{filename}"
                tmp.write_bytes(data)
                try:
                    result = self.doc_mgr.upload_file(str(tmp))
                    results.append(result)
                except Exception as e:
                    results.append({"filename": filename, "error": str(e)})
                finally:
                    tmp.unlink(missing_ok=True)
            self._send_json(results)

        elif method == "DELETE" and len(sub) == 2 and sub[0] == "documents":
            doc_id = sub[1]
            ok = self.doc_mgr.delete_document(doc_id)
            self._send_json({"ok": ok})

        # ── Models ────────────────────────────────────────────
        elif method == "GET" and sub == ["models"]:
            models = mm.list_ollama_models()
            # Tag the active model
            active = None
            try:
                cfg = self.doc_mgr.db.get_active_config()
                if cfg:
                    active = cfg.get("model_id")
            except Exception:
                pass
            for m in models:
                m["active"] = m["name"] == active
            self._send_json(models)

        elif method == "POST" and sub == ["models", "select"]:
            body = self._read_body()
            name = body.get("name", "")
            self.doc_mgr.db.save_model_config(name, name, is_active=1)
            if self.rag:
                self.rag.model = name
            self._send_json({"ok": True, "model": name})

        elif method == "POST" and sub == ["models", "pull"]:
            body = self._read_body()
            name = body.get("name", "")
            ok = mm.pull_model(name)
            self._send_json({"ok": ok, "model": name})

        # ── Analytics ─────────────────────────────────────────
        elif method == "GET" and sub == ["analytics", "summary"]:
            summary = self.analytics.get_summary()
            docs = self.doc_mgr.list_documents()
            sessions = self.chat_mgr.list_sessions()
            total_msgs = sum(s.get("message_count", 0) for s in sessions)
            total_chunks = sum(d.get("chunk_count", 0) for d in docs)
            summary["total_documents"] = len(docs)
            summary["total_document_chunks"] = total_chunks
            summary["total_chat_sessions"] = len(sessions)
            summary["total_messages"] = total_msgs
            self._send_json(summary)

        elif method == "GET" and sub == ["analytics", "events"]:
            qs = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(qs)
            limit = int(params.get("limit", [50])[0])
            events = self.analytics.get_recent_events(limit)
            self._send_json(events)

        elif method == "GET" and sub == ["analytics", "benchmark"]:
            self._send_json(self.analytics.get_benchmark())

        # ── Graph (legacy) ────────────────────────────────────
        elif method == "GET" and sub == ["stats"]:
            self._send_json(self.engine.get_stats())

        elif method == "GET" and sub == ["nodes"]:
            doc_ = self.engine.db.get_graph_document()
            self._send_json([n.__dict__ for n in doc_.nodes])

        elif method == "GET" and sub == ["edges"]:
            doc_ = self.engine.db.get_graph_document()
            self._send_json([e.__dict__ for e in doc_.edges])

        elif method == "POST" and sub == ["ingest"]:
            body = self._read_body()
            ok = self.engine.ingest_text(
                source_id=body.get("source_id", "web"),
                content=body.get("content", ""),
                label=body.get("label", "web_ingest"),
                properties=body.get("properties"),
            )
            self._send_json({"ok": ok, "source_id": body.get("source_id")})

        elif method == "POST" and sub == ["relate"]:
            body = self._read_body()
            ok = self.engine.relate(
                edge_id=body.get("edge_id"),
                source=body.get("source"),
                target=body.get("target"),
                label=body.get("label", "references"),
                properties=body.get("properties"),
            )
            self._send_json({"ok": ok, "edge_id": body.get("edge_id")})

        elif method == "GET" and sub == ["export", "json"]:
            path = self.engine.export("json", self._tmp_path("json"))
            self._send_file(path)

        elif method == "GET" and sub == ["export", "graphml"]:
            path = self.engine.export("graphml", self._tmp_path("graphml"))
            self._send_file(path)

        else:
            self._send_text("Not Found", 404)

    def _handle_stream(self, session_id: str, text: str, use_rag: bool) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            for event in self.chat_mgr.stream_message(
                session_id, text, use_rag=use_rag
            ):
                line = f"data: {json.dumps(event)}\n\n"
                try:
                    self.wfile.write(line.encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionError):
                    break
        except Exception as e:
            err = {"type": "error", "content": str(e)}
            try:
                self.wfile.write(f"data: {json.dumps(err)}\n\n".encode())
            except Exception:
                pass

    def _tmp_path(self, ext: str) -> Path:
        p = Path(tempfile.gettempdir()) / f"lrag_export.{ext}"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # ── HTTP method dispatchers ───────────────────────────────

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        self._route("GET", parts)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        self._route("POST", parts)

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        parts = parsed.path.strip("/").split("/")
        self._route("DELETE", parts)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def serve(port: int = 8089, workspace: str | None = None) -> None:
    """Start the localRAGcoder web server.

    Args:
        port: HTTP port to bind to (default 8089).
        workspace: Workspace root path.
    """
    ws = Path(workspace or os.getcwd()).resolve()
    db_dir = ws / "data"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "lrag.db"
    store_path = db_dir / "vectors"

    # Initialise components
    engine = GraphResidentEngine(str(ws))
    database = Database(str(db_path))
    doc_mgr = DocumentManager(str(db_path), str(store_path))
    rag = RAGEngine(doc_mgr, model="qwen3:8b")
    chat_mgr = ChatManager(rag, database)
    analytics = Analytics(database)

    # Load active model config
    try:
        cfg = database.get_active_config()
        if cfg:
            rag.model = cfg.get("model_id", "qwen3:8b")
    except Exception:
        pass

    EngineHandler.engine = engine
    EngineHandler.doc_mgr = doc_mgr
    EngineHandler.rag = rag
    EngineHandler.chat_mgr = chat_mgr
    EngineHandler.analytics = analytics

    global FALLBACK_PWA, _server_start_time
    _server_start_time = time.time()
    FALLBACK_PWA = _load_fallback_pwa()

    server = HTTPServer(("0.0.0.0", port), EngineHandler)
    logger.info(
        "localRAGcoder server listening on http://0.0.0.0:%d  (workspace: %s)",
        port, ws,
    )
    logger.info("Open http://localhost:%d in your browser", port)

    analytics.track_app_start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        engine.close()
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="localRAGcoder web server")
    parser.add_argument("--port", "-p", type=int, default=8089,
                        help="Port (default: 8089)")
    parser.add_argument("--workspace", "-w", default=None,
                        help="Workspace directory")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s  %(name)s  %(message)s",
    )
    serve(args.port, args.workspace)


if __name__ == "__main__":
    main()
