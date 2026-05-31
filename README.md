# localRAGcoder

**Local RAG — chat with your documents, privately.**

A fully local Retrieval-Augmented Generation engine with a PWA frontend. All data (documents, chats, analytics) persists in SQLite. Runs on Windows, Linux, macOS, and deployable to Android/iOS via Chaquopy.

## Quick Start

```bash
pip install -r requirements.txt
python -m engine.server
```

Open http://localhost:8089 in your browser. Requires [Ollama](https://ollama.ai) running on localhost:11434.

## Features

- **Multi-format ingestion** — PDF, DOCX, TXT, MD, HTML, JSON, CSV, ODT, RTF
- **Semantic search** — sentence-transformers embeddings with cosine similarity
- **RAG chat** — retrieve + generate with source citations
- **Model management** — list, select, pull any Ollama model
- **PWA frontend** — installable, works offline after first load
- **Analytics** — latency tracking, model benchmarks, rating distribution
- **Pipeline visualization** — Mermaid flow diagram of the RAG pipeline
- **Cross-platform** — Python backend, deployable to Android/iOS/Desktop

## Architecture

```
User Browser (PWA)  ←→  Python HTTP Server (port 8089)
                             │
                    ┌────────┼────────┐
                    │        │        │
               SQLite    Vector     Ollama
              (chats,   Store     (localhost:
               docs,   (numpy     11434)
               configs) embed)
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Server + Ollama status |
| GET | `/api/chats` | List chat sessions |
| POST | `/api/chats` | Create session |
| GET | `/api/chats/:id/messages` | Get messages |
| POST | `/api/chats/:id/stream` | SSE streaming |
| DELETE | `/api/chats/:id` | Delete session |
| GET | `/api/documents` | List documents |
| POST | `/api/documents/upload` | Upload file(s) |
| DELETE | `/api/documents/:id` | Delete document |
| GET | `/api/models` | List Ollama models |
| POST | `/api/models/select` | Set active model |
| POST | `/api/models/pull` | Pull a model |
| GET | `/api/analytics/summary` | Stats summary |
| GET | `/api/analytics/events` | Recent events |
| GET | `/api/analytics/benchmark` | Per-model benchmarks |

## Packaging

- **Android**: Chaquopy + PWA WebView (`packaging/android/`)
- **PWA**: Installable web app (`packaging/pwa/`)
- **Windows**: PyInstaller EXE (`packaging/windows/`)
- **Linux**: AppImage (`packaging/linux/`)

## Stack

- Python 3.14 (stdlib HTTP server, SQLite)
- sentence-transformers (embeddings)
- Plotly.js + Mermaid.js (frontend charts)
- Ollama (local LLM inference)
