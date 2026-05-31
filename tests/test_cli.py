"""Tests for engine/cli.py — command-line interface.

Version: 1.0.0
"""

import sys
import json
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.cli import build_parser, main


TMPDIR = Path(tempfile.mkdtemp(prefix="lrc_test_cli_"))


def setup_module():
    TMPDIR.mkdir(parents=True, exist_ok=True)


def teardown_module():
    shutil.rmtree(str(TMPDIR), ignore_errors=True)


def test_build_parser():
    parser = build_parser()
    assert parser is not None


def test_cli_stats():
    code = main(["--workspace", str(TMPDIR / "stats"), "graph", "stats"])
    assert code == 0


def test_cli_add_node():
    ws = TMPDIR / "add_node"
    ws.mkdir(exist_ok=True)
    code = main(["--workspace", str(ws), "graph", "add-node",
                 "--id", "test_doc", "--label", "document",
                 "--props", '{"content":"hello"}'])
    assert code == 0


def test_cli_add_edge():
    ws = TMPDIR / "add_edge"
    ws.mkdir(exist_ok=True)
    main(["--workspace", str(ws), "graph", "add-node",
          "--id", "a", "--label", "doc", "--props", '{}'])
    main(["--workspace", str(ws), "graph", "add-node",
          "--id", "b", "--label", "doc", "--props", '{}'])
    code = main(["--workspace", str(ws), "graph", "add-edge",
                 "--id", "r1", "--source", "a", "--target", "b",
                 "--label", "ref", "--props", '{}'])
    assert code == 0


def test_cli_export_json():
    ws = TMPDIR / "export_json"
    ws.mkdir(exist_ok=True)
    main(["--workspace", str(ws), "graph", "add-node",
          "--id", "n1", "--label", "doc", "--props", '{}'])
    out = TMPDIR / "cli_out.json"
    code = main(["--workspace", str(ws), "graph", "export",
                 "--format", "json", "--output", str(out)])
    assert code == 0
    assert out.exists()


def test_cli_export_graphml():
    ws = TMPDIR / "export_gml"
    ws.mkdir(exist_ok=True)
    main(["--workspace", str(ws), "graph", "add-node",
          "--id", "n1", "--label", "doc", "--props", '{}'])
    out = TMPDIR / "cli_out.graphml"
    code = main(["--workspace", str(ws), "graph", "export",
                 "--format", "graphml", "--output", str(out)])
    assert code == 0
    assert out.exists()


def test_cli_network_on():
    ws = TMPDIR / "net_on"
    ws.mkdir(exist_ok=True)
    code = main(["--workspace", str(ws), "network", "on"])
    assert code == 0


def test_cli_network_off():
    ws = TMPDIR / "net_off"
    ws.mkdir(exist_ok=True)
    code = main(["--workspace", str(ws), "network", "off"])
    assert code == 0


if __name__ == "__main__":
    setup_module()
    test_build_parser()
    test_cli_stats()
    test_cli_add_node()
    test_cli_add_edge()
    test_cli_export_json()
    test_cli_export_graphml()
    test_cli_network_on()
    test_cli_network_off()
    teardown_module()
    print("All CLI tests passed!")
