"""Integration tests — end-to-end pipeline using Ollama local models.

Queries real LLMs from D:\\models via the Ollama API to generate content,
ingests the results into the graph database, and exports to GraphML/JSON.

These tests REQUIRE Ollama to be running at http://localhost:11434
with at least one chat-compatible model loaded.

Version: 1.0.0
"""

import sys
import json
import time
import tempfile
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.main import GraphResidentEngine

OLLAMA_BASE = "http://localhost:11434"

# Prefer fast models available from D:\models, fallback to any chat model
PREFERRED_MODELS = [
    "gemma-4-26b-a4b-it-q4_k_m",    # ~10 tok/s, good quality
    "gemma-3-1b-it-qat-q4_0",       # very fast
    "glm-4-7-flash-q4_k_m",         # ~11 tok/s
    "qwen3:8b",                      # available
    "qwen2.5:14b",                   # available
]

TMPDIR = Path(tempfile.mkdtemp(prefix="lrc_int_test_"))


def setup_module():
    TMPDIR.mkdir(parents=True, exist_ok=True)


def teardown_module():
    shutil.rmtree(str(TMPDIR), ignore_errors=True)


def _ollama_request(method: str, endpoint: str, body: dict = None,
                    timeout: int = 300):
    """Make a raw HTTP request to the Ollama API."""
    import http.client
    import urllib.request

    data = json.dumps(body).encode() if body else None
    url = f"{OLLAMA_BASE}/{endpoint}"
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read().decode())


def test_ollama_is_available():
    """Sanity: the Ollama API is reachable."""
    try:
        tags = _ollama_request("GET", "api/tags")
        assert "models" in tags
        print(f"  Ollama OK — {len(tags['models'])} model(s) available")
    except Exception as e:
        pytest.skip(f"Ollama not available: {e}")


def _pick_model() -> str | None:
    """Return the first available preferred model, or None."""
    tags = _ollama_request("GET", "api/tags")
    available = {m["name"] for m in tags["models"]}
    for m in PREFERRED_MODELS:
        if m in available:
            return m
    # Fallback: any model that supports chat
    for m in available:
        if "embed" not in m and "rerank" not in m:
            return m
    return None


def _chat(model: str, prompt: str, max_tokens: int = 256) -> str:
    """Send a chat prompt to the model and return the response text.

    Handles both standard content responses and reasoning-model
    ``thinking`` fields (e.g. Qwen3, DeepSeek-R1).
    """
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": max_tokens,
        },
    }
    try:
        resp = _ollama_request("POST", "api/chat", body)
        msg = resp.get("message", {})
        content = msg.get("content", "")
        # Reasoning models stash the answer in a "thinking" field
        if not content and "thinking" in msg:
            content = msg["thinking"]
        if not content and "reasoning" in msg:
            content = msg["reasoning"]
        return content
    except Exception:
        # Fall back to /api/generate for non-chat models
        gen_body = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": max_tokens},
        }
        resp = _ollama_request("POST", "api/generate", gen_body)
        return resp.get("response", "")


INTEGRATION_MODEL = None


def test_pick_model():
    """Select a model for the integration tests."""
    global INTEGRATION_MODEL
    INTEGRATION_MODEL = _pick_model()
    if not INTEGRATION_MODEL:
        pytest.skip("No chat-capable model available in Ollama")
    print(f"  Using model: {INTEGRATION_MODEL}")


def test_model_generates_text():
    """Verify the model actually produces non-trivial output."""
    text = _chat(INTEGRATION_MODEL, "Say 'Hello World' and nothing else.", 50)
    assert len(text) > 0
    assert "Hello" in text or "hello" in text.lower()
    print(f"  Model response: {text.strip()[:80]}")


def test_integration_ingest_llm_output():
    """End-to-end: prompt LLM → ingest response → export graph."""
    engine = GraphResidentEngine(str(TMPDIR / "e2e"))

    prompt = "Explain what a knowledge graph is in one sentence."
    response = _chat(INTEGRATION_MODEL, prompt, 200)

    assert len(response) > 10, f"Response too short: {response}"

    engine.ingest_text("llm_response_1", response,
                       label="llm_output",
                       properties={"prompt": prompt, "model": INTEGRATION_MODEL})
    engine.ingest_text("prompt_1", prompt,
                       label="prompt",
                       properties={"model": INTEGRATION_MODEL})
    engine.relate("generated_by", "llm_response_1", "prompt_1",
                  "generated_from")

    stats = engine.get_stats()
    assert stats["database"]["node_count"] == 2
    assert stats["database"]["edge_count"] == 1

    # Export and verify
    json_path = TMPDIR / "e2e.json"
    engine.export("json", str(json_path))
    data = json.loads(json_path.read_text())
    assert len(data["nodes"]) == 2

    graphml_path = TMPDIR / "e2e.graphml"
    engine.export("graphml", str(graphml_path))
    content = graphml_path.read_text()
    assert "llm_response_1" in content
    assert "generated_by" in content

    engine.close()
    print(f"  Response: {response.strip()[:100]}")


def test_integration_multi_turn():
    """Multiple LLM interactions building up a richer graph."""
    ws = TMPDIR / "multi"
    engine = GraphResidentEngine(str(ws))

    topics = ["Python", "Rust", "Graph databases"]
    for topic in topics:
        resp = _chat(INTEGRATION_MODEL,
                     f"Define {topic} in 10 words or fewer.", 50)
        engine.ingest_text(f"topic:{topic.lower()}", resp,
                           label="concept",
                           properties={"topic": topic})

    # Link them sequentially
    for i in range(len(topics) - 1):
        engine.relate(
            f"rel_{i}",
            f"topic:{topics[i].lower()}",
            f"topic:{topics[i + 1].lower()}",
            "related_to",
        )

    stats = engine.get_stats()
    assert stats["database"]["node_count"] == len(topics)
    assert stats["database"]["edge_count"] == len(topics) - 1
    engine.close()
    print(f"  Multi-turn graph: {stats['database']['node_count']} nodes, "
          f"{stats['database']['edge_count']} edges")


def test_integration_export_graphml_well_formed():
    """GraphML exported from LLM-ingested data must parse as valid XML."""
    ws = TMPDIR / "xml_valid"
    engine = GraphResidentEngine(str(ws))
    resp = _chat(INTEGRATION_MODEL, "Say 'test123'.", 20)
    engine.ingest_text("valid_test", resp)
    path = engine.export("graphml", str(TMPDIR / "valid.graphml"))
    tree = ET.parse(str(path))
    assert tree.getroot().tag.endswith("graphml")
    engine.close()


def test_integration_empty_export():
    """Exporting an empty graph should produce valid JSON/GraphML."""
    ws = TMPDIR / "empty_export"
    engine = GraphResidentEngine(str(ws))

    j = engine.export("json", str(TMPDIR / "empty_int.json"))
    assert json.loads(j.read_text()) == {"nodes": [], "edges": []}

    g = engine.export("graphml", str(TMPDIR / "empty_int.graphml"))
    tree = ET.parse(str(g))
    assert tree.getroot().tag.endswith("graphml")
    engine.close()


def test_integration_network_off_still_works():
    """Network isolation switch should not block local graph ops."""
    ws = TMPDIR / "no_net"
    engine = GraphResidentEngine(str(ws), network_enabled=False)
    assert not engine.network_enabled
    engine.ingest_text("offline", "local data")
    assert engine.get_stats()["database"]["node_count"] == 1
    engine.close()


if __name__ == "__main__":
    try:
        import pytest
        HAS_PYTEST = True
    except ImportError:
        HAS_PYTEST = False

    setup_module()

    test_ollama_is_available()
    test_pick_model()
    if INTEGRATION_MODEL:
        test_model_generates_text()
        test_integration_ingest_llm_output()
        test_integration_multi_turn()
        test_integration_export_graphml_well_formed()
        test_integration_empty_export()
    test_integration_network_off_still_works()

    teardown_module()
    print("\nAll integration tests passed!")
