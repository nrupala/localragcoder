"""The Resident — localRAGcoder graph engine orchestrator.

GraphResidentEngine is the top-level entry point for working with the
knowledge graph within an OpenCode IDE workspace.  It ties together
the database (Kùzu / JSON fallback), ingestion pipeline, and export
layer.

Version: 1.0.0
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .database import GraphDatabase
from .graph_exporter import GraphExporter
from .models import GraphEdge, GraphNode

logger = logging.getLogger(__name__)


class GraphResidentEngine:
    """Orchestrates graph operations for a workspace.

    Typical workflow:
        1. Instantiate with a workspace root.
        2. Call ``ingest_text()`` one or more times to add nodes.
        3. Call ``relate()`` to wire relationships between nodes.
        4. Call ``export()`` to produce GraphML or JSON files.

    Args:
        workspace_root: Root directory of the workspace.
        db_path: Explicit path for the graph database.  Defaults to
                 ``<workspace_root>/data/graph_store/``.
        network_enabled: Whether external network (web scraper) is allowed.

    Attributes:
        workspace_root: Resolved absolute path to the workspace.
        network_enabled: Current state of the network isolation switch.
        db: The underlying GraphDatabase instance.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        db_path: Optional[str | Path] = None,
        network_enabled: bool = True,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.network_enabled = network_enabled

        if db_path is None:
            db_path = self.workspace_root / "data" / "graph_store"

        self.db = GraphDatabase(db_path)
        logger.info(
            "GraphResidentEngine initialized at %s (network=%s)",
            self.workspace_root,
            network_enabled,
        )

    def ingest_text(
        self,
        source_id: str,
        content: str,
        label: str = "document",
        properties: Optional[dict] = None,
    ) -> bool:
        """Ingest a text fragment as a node in the graph.

        Args:
            source_id: Unique identifier (e.g. file path, chunk hash).
            content: The text content (stored as ``content_preview``, first 200 chars).
            label: Semantic label for the node (default "document").
            properties: Additional metadata key-value pairs.

        Returns:
            True if the node was added/updated successfully.
        """
        node = GraphNode(
            id=source_id,
            label=label,
            properties={
                **(properties or {}),
                "content_preview": content[:200],
                "length": len(content),
            },
        )
        return self.db.add_node(node)

    def relate(
        self,
        edge_id: str,
        source: str,
        target: str,
        label: str = "references",
        properties: Optional[dict] = None,
    ) -> bool:
        """Create a directed relationship between two nodes.

        Args:
            edge_id: Unique identifier for this relationship.
            source: The id of the source node.
            target: The id of the target node.
            label: Semantic label for the relationship.
            properties: Additional metadata key-value pairs.

        Returns:
            True if the edge was added/updated successfully.
        """
        edge = GraphEdge(
            id=edge_id,
            source=source,
            target=target,
            label=label,
            properties=properties or {},
        )
        return self.db.add_edge(edge)

    def export(self, format: str, output_path: str | Path) -> Path:
        """Export the entire knowledge graph to a file.

        Args:
            format: "json" or "graphml".
            output_path: Destination file path.

        Returns:
            The resolved Path to the written file.
        """
        doc = self.db.get_graph_document()
        exporter = GraphExporter(doc)
        return exporter.export(format, output_path)

    def get_stats(self) -> dict:
        """Return operational statistics for the engine and database.

        Returns:
            Dict with workspace path, network state, and database stats.
        """
        return {
            "workspace": str(self.workspace_root),
            "network_enabled": self.network_enabled,
            "database": self.db.stats(),
        }

    def set_network(self, enabled: bool) -> None:
        """Toggle the network isolation switch.

        When disabled, the automated web scraper will be blocked.
        """
        self.network_enabled = enabled
        logger.info("Network isolation switch set to %s", enabled)

    def close(self) -> None:
        """Shut down the engine and release database resources."""
        self.db.close()
        logger.info("GraphResidentEngine shut down")
