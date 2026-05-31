"""Tests for engine/main.py — GraphResidentEngine orchestrator.

Version: 1.0.0
"""

import sys
import json
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.main import GraphResidentEngine


TMPDIR = Path(tempfile.mkdtemp(prefix="lrc_test_engine_"))


def setup_module():
    TMPDIR.mkdir(parents=True, exist_ok=True)


def teardown_module():
    shutil.rmtree(str(TMPDIR), ignore_errors=True)


_ws_counter = 0

def make_engine():
    global _ws_counter
    _ws_counter += 1
    ws = TMPDIR / f"ws_{_ws_counter}"
    ws.mkdir(exist_ok=True)
    return GraphResidentEngine(str(ws))


def test_engine_init():
    engine = make_engine()
    assert engine.workspace_root.exists()
    assert engine.network_enabled
    engine.close()


def test_ingest_text():
    engine = make_engine()
    ok = engine.ingest_text("test_doc", "Hello world", label="test")
    assert ok
    stats = engine.get_stats()
    assert stats["database"]["node_count"] == 1
    engine.close()


def test_ingest_text_with_properties():
    engine = make_engine()
    ok = engine.ingest_text("doc2", "Some content here",
                            properties={"author": "test"})
    assert ok
    engine.close()


def test_relate():
    engine = make_engine()
    engine.ingest_text("a", "Node A")
    engine.ingest_text("b", "Node B")
    ok = engine.relate("r1", "a", "b", "references")
    assert ok
    stats = engine.get_stats()
    assert stats["database"]["edge_count"] == 1
    engine.close()


def test_export_json():
    engine = make_engine()
    engine.ingest_text("n1", "content")
    path = engine.export("json", str(TMPDIR / "export.json"))
    assert path.exists()
    data = json.loads(path.read_text())
    assert len(data["nodes"]) == 1
    engine.close()


def test_export_graphml():
    engine = make_engine()
    engine.ingest_text("n1", "content")
    path = engine.export("graphml", str(TMPDIR / "export.graphml"))
    assert path.exists()
    engine.close()


def test_get_stats():
    engine = make_engine()
    stats = engine.get_stats()
    assert "workspace" in stats
    assert "network_enabled" in stats
    assert "database" in stats
    engine.close()


def test_set_network():
    engine = make_engine()
    assert engine.network_enabled
    engine.set_network(False)
    assert not engine.network_enabled
    engine.set_network(True)
    assert engine.network_enabled
    engine.close()


def test_network_off_does_not_block_graph_ops():
    engine = make_engine()
    engine.set_network(False)
    ok = engine.ingest_text("offline_doc", "test")
    assert ok
    engine.close()


def test_full_workflow():
    engine = make_engine()
    engine.ingest_text("file1.py", "def foo(): pass", label="code",
                       properties={"language": "python"})
    engine.ingest_text("file2.py", "from file1 import foo", label="code")
    engine.relate("import_rel", "file2.py", "file1.py", "imports")
    stats = engine.get_stats()
    assert stats["database"]["node_count"] == 2
    assert stats["database"]["edge_count"] == 1
    path = engine.export("json", str(TMPDIR / "full.json"))
    data = json.loads(path.read_text())
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1
    engine.close()


if __name__ == "__main__":
    setup_module()
    test_engine_init()
    test_ingest_text()
    test_ingest_text_with_properties()
    test_relate()
    test_export_json()
    test_export_graphml()
    test_get_stats()
    test_set_network()
    test_network_off_does_not_block_graph_ops()
    test_full_workflow()
    teardown_module()
    print("All engine tests passed!")
