"""Model management — list, select, and persist model configurations.

Discovers models from the local Ollama instance and provides
CRUD over user-saved model configs in SQLite.

Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

OLLAMA_BASE = "http://localhost:11434"


def list_ollama_models() -> list[dict]:
    """List models available on the local Ollama instance.

    Returns list of dicts with keys: name, modified_at, size,
    digest, details (family, parameter_size, etc).
    """
    try:
        req = Request(f"{OLLAMA_BASE}/api/tags", method="GET")
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError) as e:
        logger.warning("Cannot reach Ollama: %s", e)
        return []

    models = []
    for m in data.get("models", []):
        models.append({
            "name": m.get("name", "?"),
            "modified_at": m.get("modified_at", ""),
            "size": m.get("size", 0),
            "digest": m.get("digest", ""),
            "details": m.get("details", {}),
        })
    return models


def pull_model(model_name: str) -> bool:
    """Pull (download) a model via Ollama API.

    WARNING: This is a streaming operation that may take minutes.
    Only returns after the full pull completes.
    """
    import socket
    socket.setdefaulttimeout(600)
    try:
        body = json.dumps({"name": model_name}).encode()
        req = Request(f"{OLLAMA_BASE}/api/pull", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=600) as resp:
            for line in resp:
                chunk = json.loads(line)
                status = chunk.get("status", "")
                if status:
                    logger.info("Pull [%s]: %s", model_name, status)
                if chunk.get("error"):
                    logger.error("Pull error: %s", chunk["error"])
                    return False
        return True
    except Exception as e:
        logger.error("Pull failed for %s: %s", model_name, e)
        return False


def generate_text(model: str, prompt: str,
                  system: str | None = None,
                  stream: bool = False,
                  options: dict | None = None) -> dict:
    """Send a prompt to Ollama and return the response.

    Args:
        model: Model name (e.g. "qwen3:8b").
        prompt: The user prompt.
        system: Optional system message.
        stream: Enable streaming (SSE) — caller must handle chunks.
        options: Additional Ollama options (temperature, top_p, etc).

    Returns:
        Response dict with keys: model, created_at, response, done,
        context, total_duration, etc.

    Raises:
        ConnectionError: If Ollama is unreachable.
        ValueError: On API error.
    """
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": stream,
    }
    if system:
        payload["system"] = system
    if options:
        payload["options"] = options

    body = json.dumps(payload).encode()
    req = Request(f"{OLLAMA_BASE}/api/generate", data=body, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req, timeout=120) as resp:
            if stream:
                return {"stream": resp}  # caller iterates over lines
            result = json.loads(resp.read().decode())
    except URLError as e:
        raise ConnectionError(f"Cannot reach Ollama: {e}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"Bad response from Ollama: {e}") from e

    if "error" in result:
        raise ValueError(result["error"])
    return result


def chat_completion(model: str, messages: list[dict],
                    stream: bool = False,
                    options: dict | None = None) -> dict:
    """Chat completion via Ollama.

    Args:
        model: Model name.
        messages: List of {"role": "user"|"assistant"|"system",
                           "content": "..."}
        stream: Enable streaming.
        options: Ollama options.

    Returns:
        Response dict or stream object.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }
    if options:
        payload["options"] = options

    body = json.dumps(payload).encode()
    req = Request(f"{OLLAMA_BASE}/api/chat", data=body, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req, timeout=120) as resp:
            if stream:
                return {"stream": resp}
            result = json.loads(resp.read().decode())
    except URLError as e:
        raise ConnectionError(f"Cannot reach Ollama: {e}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"Bad response from Ollama: {e}") from e

    if "error" in result:
        raise ValueError(result["error"])
    return result
