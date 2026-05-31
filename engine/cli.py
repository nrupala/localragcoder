"""Command-line interface for the localRAGcoder graph engine.

Provides terminal access to all engine operations:
  - ``python -m engine.cli graph export``
  - ``python -m engine.cli graph stats``
  - ``python -m engine.cli graph add-node``
  - ``python -m engine.cli graph add-edge``
  - ``python -m engine.cli network on|off``

Version: 1.0.0
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .graph_exporter import GraphExporter
from .main import GraphResidentEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(name)s  %(message)s",
)
logger = logging.getLogger("engine.cli")

VERSION = "1.0.0"


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for the CLI.

    Returns:
        A fully configured ArgumentParser with all subcommands.
    """
    parser = argparse.ArgumentParser(
        prog="python -m engine.cli",
        description="localRAGcoder — Graph Resident Engine CLI",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"localRAGcoder v{VERSION}",
    )
    parser.add_argument(
        "--workspace", "-w",
        default=".",
        help="Workspace root directory (default: current dir)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── graph export ──────────────────────────────────────────
    graph_export = sub.add_parser("graph", help="Graph operations")
    graph_sub = graph_export.add_subparsers(dest="action", required=True)

    export = graph_sub.add_parser("export", help="Export the graph database")
    export.add_argument(
        "--format", "-f",
        choices=GraphExporter.SUPPORTED_FORMATS,
        default="json",
        help="Export format (default: json)",
    )
    export.add_argument(
        "--output", "-o",
        required=True,
        help="Output file path",
    )

    # ── graph stats ───────────────────────────────────────────
    graph_sub.add_parser("stats", help="Show graph database statistics")

    # ── graph add-node ────────────────────────────────────────
    add_node = graph_sub.add_parser("add-node", help="Add a node to the graph")
    add_node.add_argument("--id", required=True, help="Node ID (unique identifier)")
    add_node.add_argument("--label", default="node", help="Node semantic label")
    add_node.add_argument(
        "--props", default="{}", help="JSON-encoded properties string"
    )

    # ── graph add-edge ────────────────────────────────────────
    add_edge = graph_sub.add_parser("add-edge", help="Add an edge to the graph")
    add_edge.add_argument("--id", required=True, help="Edge ID (unique identifier)")
    add_edge.add_argument("--source", required=True, help="Source node ID")
    add_edge.add_argument("--target", required=True, help="Target node ID")
    add_edge.add_argument("--label", default="references", help="Edge semantic label")
    add_edge.add_argument(
        "--props", default="{}", help="JSON-encoded properties string"
    )

    # ── network ───────────────────────────────────────────────
    net = sub.add_parser("network", help="Network isolation switch")
    net.add_argument(
        "state",
        choices=["on", "off"],
        help="Enable ('on') or disable ('off') network access",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and dispatch to the engine.

    Args:
        argv: Command-line tokens (defaults to sys.argv[1:]).

    Returns:
        Exit code (0 = success).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    engine = GraphResidentEngine(args.workspace)

    try:
        if args.command == "graph":
            if args.action == "export":
                result = engine.export(args.format, args.output)
                print(f"Exported to {result}")
            elif args.action == "stats":
                stats = engine.get_stats()
                print(json.dumps(stats, indent=2))
            elif args.action == "add-node":
                props = json.loads(args.props)
                ok = engine.ingest_text(
                    source_id=args.id,
                    content=props.pop("content", ""),
                    label=args.label,
                    properties=props,
                )
                print(f"Node {'added' if ok else 'failed'}: {args.id}")
            elif args.action == "add-edge":
                props = json.loads(args.props)
                ok = engine.relate(
                    edge_id=args.id,
                    source=args.source,
                    target=args.target,
                    label=args.label,
                    properties=props,
                )
                print(f"Edge {'added' if ok else 'failed'}: {args.id}")

        elif args.command == "network":
            enabled = args.state == "on"
            engine.set_network(enabled)
            print(f"Network {'enabled' if enabled else 'disabled'}")

    finally:
        engine.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
