"""Model management — list, select, and persist model configurations.

Speaks the OpenAI-compatible chat-completions API
(``POST {BASE}/v1/chat/completions``, ``GET {BASE}/v1/models``), so any
compliant backend works — llama.cpp server, vLLM, or anything else behind
the single HTTP layer. No per-server SDKs.

Configuration (environment):
    LLM_BASE_URL  Base URL of the OpenAI-compatible server.
                  Default: http://localhost:11434  (Ollama also speaks it)
                  llama.cpp server default: http://localhost:8080
    LLM_API_KEY   Optional bearer token. Sent only when set.

Version: 1.1.0
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Iterator, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        h["Authorization"] = f"Bearer {LLM_API_KEY}"
    return h


def _post(path: str, payload: dict, timeout: int = 120):
    """POST JSON to the LLM server. Returns the http response object."""
    body = json.dumps(payload).encode()
    req = Request(f"{LLM_BASE_URL}{path}", data=body, method="POST",
                  headers=_headers())
    try:
        return urlopen(req, timeout=timeout)
    except URLError as e:
        raise ConnectionError(f"Cannot reach LLM server at {LLM_BASE_URL}: {e}") from e


def _map_options(options: dict | None) -> dict:
    """Map Ollama-style options to OpenAI-compatible top-level params."""
    if not options:
        return {}
    out: dict[str, Any] = {}
    if "temperature" in options:
        out["temperature"] = options["temperature"]
    if "top_p" in options:
        out["top_p"] = options["top_p"]
    if "num_predict" in options:
        out["max_tokens"] = options["num_predict"]
    if "max_tokens" in options:
        out["max_tokens"] = options["max_tokens"]
    if "stop" in options:
        out["stop"] = options["stop"]
    return out


def list_models() -> list[dict]:
    """List models available on the OpenAI-compatible server.

    Returns list of dicts with keys: name, modified_at, size,
    digest, details — same shape as before, so callers are untouched.
    """
    try:
        req = Request(f"{LLM_BASE_URL}/v1/models", method="GET",
                      headers=_headers())
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError) as e:
        logger.warning("Cannot reach LLM server: %s", e)
        return []

    models = []
    for m in data.get("data", []):
        models.append({
            "name": m.get("id", "?"),
            "modified_at": str(m.get("created", "")),
            "size": 0,
            "digest": "",
            "details": {"owned_by": m.get("owned_by", "")},
        })
    return models


# Backwards-compatible alias — callers in server.py use this name.
def list_ollama_models() -> list[dict]:
    """Alias for list_models (kept so existing callers keep working)."""
    return list_models()


def pull_model(model_name: str) -> bool:
    """No-op on OpenAI-compatible backends.

    llama.cpp / vLLM load models via server startup args — there is no
    pull API. Returns False with a clear log line instead of pretending.
    """
    logger.warning(
        "pull_model(%s): not supported by OpenAI-compatible servers — "
        "load the model via the server's startup args instead.", model_name)
    return False


def _messages_for(prompt: str, system: str | None) -> list[dict]:
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    return msgs


def generate_text(model: str, prompt: str,
                  system: str | None = None,
                  stream: bool = False,
                  options: dict | None = None) -> dict:
    """Send a prompt and return the response.

    Keeps the previous return contract so callers are untouched:
      non-stream -> {"response": <text>, "model": ..., "done": True, ...}
      stream     -> {"stream": <iterator of NDJSON lines shaped
                               {"response": <delta>} per line>}

    Args:
        model: Model name as known to the server.
        prompt: The user prompt.
        system: Optional system message.
        stream: Enable streaming — caller iterates the returned lines.
        options: Ollama-style options (temperature, top_p, num_predict);
                 mapped to OpenAI-compatible params.

    Raises:
        ConnectionError: If the LLM server is unreachable.
        ValueError: On API error.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": _messages_for(prompt, system),
        "stream": stream,
    }
    payload.update(_map_options(options))

    if stream:
        resp = _post("/v1/chat/completions", payload)
        return {"stream": _openai_sse_to_ndjson(resp)}

    with _post("/v1/chat/completions", payload) as resp:
        try:
            result = json.loads(resp.read().decode())
        except json.JSONDecodeError as e:
            raise ValueError(f"Bad response from LLM server: {e}") from e

    if "error" in result:
        err = result["error"]
        msg = err.get("message", err) if isinstance(err, dict) else err
        raise ValueError(msg)
    try:
        text = result["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"Unexpected chat-completions shape: {e}") from e
    return {
        "model": result.get("model", model),
        "created_at": result.get("created", ""),
        "response": text,
        "done": True,
    }


def _openai_sse_to_ndjson(resp) -> Iterator[bytes]:
    """Translate OpenAI SSE stream into Ollama-shaped NDJSON lines.

    Each yielded line is a JSON object {"response": <delta>} encoded
    as bytes — exactly what chat.py's streaming parser expects, so the
    streaming path works without caller changes.
    """
    try:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                evt = json.loads(data)
            except json.JSONDecodeError:
                continue
            if "error" in evt:
                err = evt["error"]
                msg = err.get("message", err) if isinstance(err, dict) else err
                yield (json.dumps({"error": msg}) + "\n").encode()
                return
            try:
                delta = evt["choices"][0]["delta"].get("content") or ""
            except (KeyError, IndexError, TypeError):
                continue
            if delta:
                yield (json.dumps({"response": delta}) + "\n").encode()
    finally:
        resp.close()


def chat_completion(model: str, messages: list[dict],
                    stream: bool = False,
                    options: dict | None = None) -> dict:
    """Chat completion via the OpenAI-compatible API.

    Keeps the previous return contract: {"message": {"role", "content"},
    "model": ..., "done": True} — callers are untouched.
    Streaming is not supported here (use generate_text for streams).
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    payload.update(_map_options(options))

    with _post("/v1/chat/completions", payload) as resp:
        try:
            result = json.loads(resp.read().decode())
        except json.JSONDecodeError as e:
            raise ValueError(f"Bad response from LLM server: {e}") from e

    if "error" in result:
        err = result["error"]
        msg = err.get("message", err) if isinstance(err, dict) else err
        raise ValueError(msg)
    try:
        message = result["choices"][0]["message"]
        content = message.get("content") or ""
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"Unexpected chat-completions shape: {e}") from e
    return {
        "model": result.get("model", model),
        "created_at": result.get("created", ""),
        "message": {"role": message.get("role", "assistant"),
                    "content": content},
        "done": True,
    }
