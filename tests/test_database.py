"""Tests for engine/database.py — GraphDatabase (JSON fallback backend).

Version: 1.0.0
"""

import sys
import json
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.models import GraphNode, GraphEdge, GraphDocument
from engine.database import GraphDatabase, KUZU_AVAILABLE


TMPDIR = Path(tempfile.mkdtemp(prefix="lrc_test_db_"))


def setup_module():
    TMPDIR.mkdir(parents=True, exist_ok=True)


def teardown_module():
    shutil.rmtree(str(TMPDIR), ignore_errors=True)


def make_db(name="test"):
    path = TMPDIR / name
    path.mkdir(exist_ok=True)
    return GraphDatabase(str(path), create_if_missing=True)


def test_init_creates_directory():
    path = TMPDIR / "init_test"
    db = GraphDatabase(str(path), create_if_missing=True)
    assert path.exists()
    assert db.is_connected
    db.close()


def test_add_node():
    db = make_db("add_node")
    n = GraphNode(id="doc1", label="document", properties={"size": 100})
    ok = db.add_node(n)
    assert ok
    nodes = db.get_all_nodes()
    assert len(nodes) == 1
    assert nodes[0].id == "doc1"
    assert nodes[0].properties["size"] == 100
    db.close()


def test_add_edge():
    db = make_db("add_edge")
    n1 = GraphNode(id="a", label="doc")
    n2 = GraphNode(id="b", label="doc")
    db.add_node(n1)
    db.add_node(n2)
    e = GraphEdge(id="r1", source="a", target="b", label="references")
    ok = db.add_edge(e)
    assert ok
    edges = db.get_all_edges()
    assert len(edges) == 1
    assert edges[0].source == "a"
    assert edges[0].target == "b"
    db.close()


def test_upsert_node_updates_existing():
    db = make_db("upsert")
    db.add_node(GraphNode(id="x", label="old", properties={"v": 1}))
    db.add_node(GraphNode(id="x", label="new", properties={"v": 2}))
    nodes = db.get_all_nodes()
    assert len(nodes) == 1
    assert nodes[0].label == "new"
    assert nodes[0].properties["v"] == 2
    db.close()


def test_upsert_edge_updates_existing():
    db = make_db("upsert_edge")
    db.add_node(GraphNode(id="a", label="doc"))
    db.add_node(GraphNode(id="b", label="doc"))
    db.add_edge(GraphEdge(id="r1", source="a", target="b", label="old"))
    db.add_edge(GraphEdge(id="r1", source="a", target="b", label="new"))
    edges = db.get_all_edges()
    assert len(edges) == 1
    assert edges[0].label == "new"
    db.close()


def test_get_graph_document():
    db = make_db("get_doc")
    db.add_node(GraphNode(id="n1", label="doc"))
    db.add_node(GraphNode(id="n2", label="doc"))
    db.add_edge(GraphEdge(id="e1", source="n1", target="n2", label="link"))
    doc = db.get_graph_document()
    assert len(doc.nodes) == 2
    assert len(doc.edges) == 1
    db.close()


def test_clear():
    db = make_db("clear")
    db.add_node(GraphNode(id="n1", label="doc"))
    db.clear()
    assert len(db.get_all_nodes()) == 0
    assert len(db.get_all_edges()) == 0
    db.close()


def test_stats():
    db = make_db("stats")
    db.add_node(GraphNode(id="n1", label="doc"))
    s = db.stats()
    assert s["node_count"] == 1
    assert s["edge_count"] == 0
    # The engine name reflects whichever backend is actually in use.
    assert s["engine"] == ("kuzu" if KUZU_AVAILABLE else "json_fallback")
    db.close()


def test_is_connected():
    db = make_db("conn")
    assert db.is_connected
    db.close()


def test_add_node_failure_invalid_id():
    """Even with unusual IDs, the engine should handle gracefully."""
    db = make_db("bad_id")
    n = GraphNode(id="", label="empty")
    ok = db.add_node(n)
    assert ok
    db.close()


def test_file_persistence():
    path = TMPDIR / "persist"
    path.mkdir(exist_ok=True)
    db1 = GraphDatabase(str(path))
    db1.add_node(GraphNode(id="keep", label="persistent"))
    db1.close()

    db2 = GraphDatabase(str(path))
    nodes = db2.get_all_nodes()
    assert len(nodes) == 1
    assert nodes[0].id == "keep"
    db2.close()


if __name__ == "__main__":
    setup_module()
    test_init_creates_directory()
    test_add_node()
    test_add_edge()
    test_upsert_node_updates_existing()
    test_upsert_edge_updates_existing()
    test_get_graph_document()
    test_clear()
    test_stats()
    test_is_connected()
    test_add_node_failure_invalid_id()
    test_file_persistence()
    teardown_module()
    print("All database tests passed!")
