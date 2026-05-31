"""Tests for engine/graph_exporter.py — GraphExporter (JSON + GraphML).

Version: 1.0.0
"""

import sys
import json
import tempfile
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.models import GraphNode, GraphEdge, GraphDocument
from engine.graph_exporter import GraphExporter


TMPDIR = Path(tempfile.mkdtemp(prefix="lrc_test_export_"))


def setup_module():
    TMPDIR.mkdir(parents=True, exist_ok=True)


def teardown_module():
    shutil.rmtree(str(TMPDIR), ignore_errors=True)


def make_doc():
    doc = GraphDocument()
    doc.add_node(GraphNode(id="n1", label="doc", properties={"lang": "py"}))
    doc.add_node(GraphNode(id="n2", label="doc", properties={"lang": "js"}))
    doc.add_edge(GraphEdge(id="e1", source="n1", target="n2", label="imports"))
    return doc


def test_export_json():
    doc = make_doc()
    exporter = GraphExporter(doc)
    path = TMPDIR / "test.json"
    result = exporter.export("json", str(path))
    assert result.exists()
    data = json.loads(path.read_text())
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1
    assert data["nodes"][0]["id"] == "n1"


def test_export_graphml():
    doc = make_doc()
    exporter = GraphExporter(doc)
    path = TMPDIR / "test.graphml"
    result = exporter.export("graphml", str(path))
    assert result.exists()
    tree = ET.parse(str(path))
    root = tree.getroot()
    ns = {"g": "http://graphml.graphdrawing.org/xmlns"}
    nodes = root.findall(".//g:node", ns)
    edges = root.findall(".//g:edge", ns)
    assert len(nodes) == 2
    assert len(edges) == 1


def test_export_json_format_with_dot():
    doc = make_doc()
    exporter = GraphExporter(doc)
    path = TMPDIR / "dot.json"
    exporter.export(".json", str(path))
    data = json.loads(path.read_text())
    assert len(data["nodes"]) == 2


def test_export_unsupported_format():
    doc = make_doc()
    exporter = GraphExporter(doc)
    try:
        exporter.export("csv", TMPDIR / "bad.csv")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_export_string_json():
    doc = make_doc()
    s = GraphExporter.export_string(doc, "json")
    data = json.loads(s)
    assert len(data["nodes"]) == 2


def test_export_string_graphml():
    doc = make_doc()
    s = GraphExporter.export_string(doc, "graphml")
    assert '<?xml' in s
    assert 'graphml' in s
    assert 'n1' in s


def test_graphml_node_attributes():
    doc = make_doc()
    exporter = GraphExporter(doc)
    path = TMPDIR / "attrs.graphml"
    exporter.export("graphml", str(path))
    content = path.read_text()
    assert 'lang' in content or 'prop_lang' in content


def test_graphml_edge_attributes():
    doc = GraphDocument()
    doc.add_node(GraphNode(id="a", label="x"))
    doc.add_node(GraphNode(id="b", label="y"))
    doc.add_edge(GraphEdge(id="e1", source="a", target="b",
                           label="ref", properties={"weight": "5"}))
    exporter = GraphExporter(doc)
    path = TMPDIR / "edge_attrs.graphml"
    exporter.export("graphml", str(path))
    content = path.read_text()
    assert 'prop_weight' in content
    assert '5' in content


def test_export_empty_document():
    doc = GraphDocument()
    exporter = GraphExporter(doc)
    path = TMPDIR / "empty.json"
    exporter.export("json", str(path))
    data = json.loads(path.read_text())
    assert data["nodes"] == []
    assert data["edges"] == []


def test_export_many_nodes():
    doc = GraphDocument()
    for i in range(100):
        doc.add_node(GraphNode(id=f"n{i}", label="batch"))
    exporter = GraphExporter(doc)
    path = TMPDIR / "batch.json"
    exporter.export("json", str(path))
    data = json.loads(path.read_text())
    assert len(data["nodes"]) == 100


if __name__ == "__main__":
    setup_module()
    test_export_json()
    test_export_graphml()
    test_export_json_format_with_dot()
    test_export_unsupported_format()
    test_export_string_json()
    test_export_string_graphml()
    test_graphml_node_attributes()
    test_graphml_edge_attributes()
    test_export_empty_document()
    test_export_many_nodes()
    teardown_module()
    print("All exporter tests passed!")
