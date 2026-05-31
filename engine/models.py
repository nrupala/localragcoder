"""Data models for the localRAGcoder graph database.

Defines the core data structures used throughout the engine:
GraphNode, GraphEdge, and GraphDocument. These dataclasses serve as
the universal representation of graph data regardless of the backing
store (Kùzu or JSON fallback).

Version: 1.0.0
"""

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class GraphNode:
    """A single node (vertex) in the knowledge graph.

    Attributes:
        id: Unique identifier for the node (e.g. file path, URI).
        label: Semantic type label (e.g. "document", "code", "concept").
        properties: Arbitrary key-value metadata attached to the node.
    """

    id: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    """A directed edge (relationship) connecting two GraphNodes.

    Attributes:
        id: Unique identifier for the edge.
        source: The id of the source (from) node.
        target: The id of the target (to) node.
        label: Relationship type label (e.g. "references", "imports").
        properties: Arbitrary key-value metadata attached to the edge.
    """

    id: str
    source: str
    target: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphDocument:
    """A complete graph document containing nodes and edges.

    This is the top-level container for graph data and is used as the
    interchange format between the database layer and the export layer.

    Attributes:
        nodes: All nodes in the graph.
        edges: All edges in the graph.
    """

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def add_node(self, node: GraphNode) -> None:
        """Append a node to the document."""
        self.nodes.append(node)

    def add_edge(self, edge: GraphEdge) -> None:
        """Append an edge to the document."""
        self.edges.append(edge)

    def to_dict(self) -> dict:
        """Serialize the entire graph to a plain dictionary.

        Returns:
            dict with keys "nodes" and "edges", each being a list of
            dictionaries produced by dataclasses.asdict().
        """
        return {
            "nodes": [asdict(n) for n in self.nodes],
            "edges": [asdict(e) for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GraphDocument":
        """Deserialize a dictionary back into a GraphDocument.

        Args:
            data: A dict with "nodes" and "edges" keys containing
                  lists of dicts with the same shape as GraphNode/GraphEdge.

        Returns:
            A new GraphDocument populated with the deserialized data.
        """
        doc = cls()
        for n in data.get("nodes", []):
            doc.nodes.append(GraphNode(**n))
        for e in data.get("edges", []):
            doc.edges.append(GraphEdge(**e))
        return doc
