"""Tests for engine/models.py — GraphNode, GraphEdge, GraphDocument.

Version: 1.0.0
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.models import GraphNode, GraphEdge, GraphDocument


def test_graph_node_defaults():
    n = GraphNode(id="n1", label="test")
    assert n.id == "n1"
    assert n.label == "test"
    assert n.properties == {}


def test_graph_node_with_properties():
    n = GraphNode(id="n1", label="doc", properties={"lang": "py", "size": 42})
    assert n.properties["lang"] == "py"
    assert n.properties["size"] == 42


def test_graph_edge_defaults():
    e = GraphEdge(id="e1", source="a", target="b", label="link")
    assert e.id == "e1"
    assert e.source == "a"
    assert e.target == "b"
    assert e.label == "link"
    assert e.properties == {}


def test_graph_edge_with_properties():
    e = GraphEdge(id="e1", source="a", target="b", label="imports",
                  properties={"weight": 1.0})
    assert e.properties["weight"] == 1.0


def test_graph_document_empty():
    doc = GraphDocument()
    assert doc.nodes == []
    assert doc.edges == []


def test_graph_document_add():
    doc = GraphDocument()
    doc.add_node(GraphNode(id="n1", label="doc"))
    doc.add_edge(GraphEdge(id="e1", source="n1", target="n2", label="ref"))
    assert len(doc.nodes) == 1
    assert len(doc.edges) == 1


def test_graph_document_to_dict():
    doc = GraphDocument()
    doc.add_node(GraphNode(id="n1", label="doc", properties={"a": 1}))
    d = doc.to_dict()
    assert "nodes" in d
    assert "edges" in d
    assert d["nodes"][0]["id"] == "n1"
    assert d["nodes"][0]["properties"]["a"] == 1


def test_graph_document_from_dict_roundtrip():
    doc = GraphDocument()
    doc.add_node(GraphNode(id="n1", label="doc"))
    doc.add_edge(GraphEdge(id="e1", source="n1", target="n2", label="ref"))
    data = doc.to_dict()
    restored = GraphDocument.from_dict(data)
    assert len(restored.nodes) == 1
    assert len(restored.edges) == 1
    assert restored.nodes[0].id == "n1"
    assert restored.edges[0].source == "n1"


def test_graph_document_json_serializable():
    doc = GraphDocument()
    doc.add_node(GraphNode(id="n1", label="doc", properties={"key": "val"}))
    json_str = json.dumps(doc.to_dict())
    parsed = json.loads(json_str)
    assert parsed["nodes"][0]["id"] == "n1"


def test_graph_node_equality_by_id():
    n1 = GraphNode(id="same", label="a")
    n2 = GraphNode(id="same", label="b")
    assert n1.id == n2.id


def test_graph_edge_repr():
    e = GraphEdge(id="e1", source="a", target="b", label="link")
    r = repr(e)
    assert "e1" in r
    assert "link" in r


if __name__ == "__main__":
    test_graph_node_defaults()
    test_graph_node_with_properties()
    test_graph_edge_defaults()
    test_graph_edge_with_properties()
    test_graph_document_empty()
    test_graph_document_add()
    test_graph_document_to_dict()
    test_graph_document_from_dict_roundtrip()
    test_graph_document_json_serializable()
    test_graph_node_equality_by_id()
    test_graph_edge_repr()
    print("All models tests passed!")
