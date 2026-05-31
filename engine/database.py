"""Persistence layer for the localRAGcoder graph database.

Provides a dual-backend GraphDatabase class that uses Kùzu (an embedded
columnar graph DBMS) when available, and transparently falls back to a
JSON file store when the kuzu package is not installed.

Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .models import GraphDocument, GraphEdge, GraphNode

logger = logging.getLogger(__name__)

try:
    import kuzu

    KUZU_AVAILABLE = True
except ImportError:
    KUZU_AVAILABLE = False


class GraphDatabase:
    """Abstraction over Kùzu DB with automatic JSON fallback.

    Manages a local graph store. When Kùzu is installed, all operations
    run against a real embedded columnar graph DB. Otherwise, a simple
    JSON file at ``graph_store/graph.json`` persists the data.

    Args:
        db_path: Directory path for the database files.
        create_if_missing: Create the directory tree if it doesn't exist.

    Attributes:
        db_path: Resolved absolute path to the database directory.
    """

    def __init__(self, db_path: str | Path, create_if_missing: bool = True):
        self.db_path = Path(db_path).resolve()
        self._conn: Any = None
        self._initialized = False

        if create_if_missing:
            self.db_path.mkdir(parents=True, exist_ok=True)

        if KUZU_AVAILABLE:
            self._init_kuzu()
        else:
            logger.info("Kùzu not installed — using JSON-backed fallback store")
            self._init_fallback()

    # ── internal initializers ─────────────────────────────────────

    def _init_kuzu(self) -> None:
        """Initialize a Kùzu in-process database and create schema."""
        self._db = kuzu.Database(str(self.db_path))
        self._conn = kuzu.Connection(self._db)
        self._conn.execute(
            "CREATE NODE TABLE IF NOT EXISTS Node "
            "(id STRING, label STRING, properties STRING, PRIMARY KEY (id))"
        )
        self._conn.execute(
            "CREATE REL TABLE IF NOT EXISTS Edge "
            "(FROM Node TO Node, id STRING, label STRING, properties STRING)"
        )
        self._initialized = True
        logger.info("Kùzu database initialized at %s", self.db_path)

    def _init_fallback(self) -> None:
        """Initialize (or load) the JSON fallback file."""
        self._fallback_file: Path = self.db_path / "graph.json"
        if not self._fallback_file.exists():
            self._fallback_file.write_text(
                json.dumps({"nodes": [], "edges": []}, indent=2)
            )
        self._initialized = True
        logger.info("Fallback JSON store initialized at %s", self._fallback_file)

    # ── fallback I/O helpers ──────────────────────────────────────

    def _load_fallback(self) -> GraphDocument:
        """Deserialize the JSON fallback file into a GraphDocument."""
        raw = json.loads(self._fallback_file.read_text())
        return GraphDocument.from_dict(raw)

    def _save_fallback(self, doc: GraphDocument) -> None:
        """Serialize a GraphDocument to the JSON fallback file."""
        self._fallback_file.write_text(
            json.dumps(doc.to_dict(), indent=2, default=str)
        )

    # ── public mutation API ───────────────────────────────────────

    def add_node(self, node: GraphNode) -> bool:
        """Insert or update a node in the graph.

        Uses MERGE (upsert) semantics so repeated calls with the same
        ``node.id`` update the existing node rather than creating a duplicate.

        Args:
            node: The GraphNode to persist.

        Returns:
            True on success, False on error.
        """
        try:
            if KUZU_AVAILABLE:
                self._conn.execute(
                    "MERGE INTO Node (id, label, properties) "
                    "VALUES ($id, $label, $props)",
                    parameters={
                        "id": node.id,
                        "label": node.label,
                        "props": json.dumps(node.properties),
                    },
                )
            else:
                doc = self._load_fallback()
                existing = [n for n in doc.nodes if n.id == node.id]
                if not existing:
                    doc.nodes.append(node)
                else:
                    existing[0].properties = node.properties
                    existing[0].label = node.label
                self._save_fallback(doc)
            return True
        except Exception as e:
            logger.error("Failed to add node %s: %s", node.id, e)
            return False

    def add_edge(self, edge: GraphEdge) -> bool:
        """Insert or update an edge in the graph.

        Uses MERGE (upsert) semantics similar to add_node.

        Args:
            edge: The GraphEdge to persist.

        Returns:
            True on success, False on error.
        """
        try:
            if KUZU_AVAILABLE:
                self._conn.execute(
                    "MERGE INTO Edge (id, label, properties) "
                    "VALUES ($id, $label, $props)",
                    parameters={
                        "id": edge.id,
                        "label": edge.label,
                        "props": json.dumps(edge.properties),
                    },
                )
            else:
                doc = self._load_fallback()
                existing = [e for e in doc.edges if e.id == edge.id]
                if not existing:
                    doc.edges.append(edge)
                else:
                    existing[0].label = edge.label
                    existing[0].source = edge.source
                    existing[0].target = edge.target
                    existing[0].properties = edge.properties
                self._save_fallback(doc)
            return True
        except Exception as e:
            logger.error("Failed to add edge %s: %s", edge.id, e)
            return False

    # ── public read API ───────────────────────────────────────────

    def get_all_nodes(self) -> list[GraphNode]:
        """Return every node currently in the database.

        Returns:
            A list of GraphNode objects (may be empty).
        """
        if KUZU_AVAILABLE:
            result = self._conn.execute("MATCH (n:Node) RETURN n.*")
            nodes = []
            while result.has_next():
                row = result.get_next()
                nodes.append(
                    GraphNode(
                        id=row[0],
                        label=row[1],
                        properties=json.loads(row[2]) if row[2] else {},
                    )
                )
            return nodes
        doc = self._load_fallback()
        return doc.nodes

    def get_all_edges(self) -> list[GraphEdge]:
        """Return every edge currently in the database.

        Returns:
            A list of GraphEdge objects (may be empty).
        """
        if KUZU_AVAILABLE:
            result = self._conn.execute(
                "MATCH (s:Node)-[e:Edge]->(t:Node) "
                "RETURN e.id, s.id, t.id, e.label, e.properties"
            )
            edges = []
            while result.has_next():
                row = result.get_next()
                edges.append(
                    GraphEdge(
                        id=row[0],
                        source=row[1],
                        target=row[2],
                        label=row[3],
                        properties=json.loads(row[4]) if row[4] else {},
                    )
                )
            return edges
        doc = self._load_fallback()
        return doc.edges

    def get_graph_document(self) -> GraphDocument:
        """Convenience: return a single GraphDocument with all data.

        Returns:
            A GraphDocument containing every node and edge.
        """
        return GraphDocument(
            nodes=self.get_all_nodes(),
            edges=self.get_all_edges(),
        )

    # ── lifecycle ─────────────────────────────────────────────────

    def clear(self) -> None:
        """Remove all nodes and edges from the database."""
        if KUZU_AVAILABLE:
            self._conn.execute("MATCH (n:Node) DELETE n")
        else:
            self._save_fallback(GraphDocument())
        logger.info("Graph database cleared")

    def close(self) -> None:
        """Shut down the database connection (Kùzu only)."""
        if KUZU_AVAILABLE and hasattr(self, "_db"):
            self._db.close()
        self._initialized = False

    # ── properties / introspection ────────────────────────────────

    @property
    def is_connected(self) -> bool:
        """True if the database has been initialized."""
        return self._initialized

    def stats(self) -> dict:
        """Return a summary dict of database statistics.

        Returns:
            Keys: node_count, edge_count, db_path, engine ("kuzu" | "json_fallback").
        """
        nodes = self.get_all_nodes()
        edges = self.get_all_edges()
        return {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "db_path": str(self.db_path),
            "engine": "kuzu" if KUZU_AVAILABLE else "json_fallback",
        }
