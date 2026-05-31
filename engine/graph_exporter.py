"""Export the localRAGcoder knowledge graph to standard interchange formats.

Supports:
  - **JSON** – a plain nested dict (nodes / edges lists) for programmatic use.
  - **GraphML** – an XML-based standard (ISO/IEC 19757-2) readable by
    Gephi, yEd, Cytoscape, and other graph-visualization tools.

Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .models import GraphDocument

logger = logging.getLogger(__name__)


class GraphExporter:
    """Serializes a GraphDocument to JSON or GraphML.

    Attributes:
        SUPPORTED_FORMATS: Tuple of format strings accepted by export().
        doc: The GraphDocument to export.
    """

    SUPPORTED_FORMATS = ("json", "graphml")

    def __init__(self, graph_doc: GraphDocument):
        self.doc = graph_doc

    def export(self, format: str, output_path: str | Path) -> Path:
        """Write the graph to a file in the requested format.

        Args:
            format: One of ``SUPPORTED_FORMATS`` ("json" or "graphml").
            output_path: Destination file path (parent dirs created as needed).

        Returns:
            The resolved Path to the written file.

        Raises:
            ValueError: If format is not supported.
        """
        format = format.lower().lstrip(".")
        if format not in self.SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported format '{format}'. "
                f"Supported: {', '.join(self.SUPPORTED_FORMATS)}"
            )

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if format == "json":
            return self._export_json(path)
        return self._export_graphml(path)

    # ── private export implementations ────────────────────────────

    def _export_json(self, path: Path) -> Path:
        """Write the graph as a JSON array-of-objects file."""
        data = self.doc.to_dict()
        path.write_text(json.dumps(data, indent=2, default=str))
        logger.info(
            "Exported graph JSON to %s (%d nodes, %d edges)",
            path,
            len(self.doc.nodes),
            len(self.doc.edges),
        )
        return path

    def _export_graphml(self, path: Path) -> Path:
        """Write the graph as a GraphML XML file (ISO/IEC 19757-2).

        Produces a fully standards-compliant GraphML document that can be
        opened directly in Gephi, yEd, or Cytoscape.
        """
        graphml_ns = "http://graphml.graphdrawing.org/xmlns"
        ET.register_namespace("", graphml_ns)

        root = ET.Element(f"{{{graphml_ns}}}graphml")

        # Declare key attributes
        root.append(self._make_key("node_label", "node", "string"))
        root.append(self._make_key("edge_label", "edge", "string"))

        if self.doc.nodes:
            for key in self.doc.nodes[0].properties:
                root.append(self._make_key(f"prop_{key}", "node", "string"))
        if self.doc.edges:
            for key in self.doc.edges[0].properties:
                root.append(self._make_key(f"prop_{key}", "edge", "string"))

        graph = ET.SubElement(
            root, f"{{{graphml_ns}}}graph",
            {"id": "G", "edgedefault": "directed"},
        )

        # Write nodes
        for node in self.doc.nodes:
            node_el = ET.SubElement(
                graph, f"{{{graphml_ns}}}node", {"id": node.id}
            )
            data_el = ET.SubElement(
                node_el, f"{{{graphml_ns}}}data", {"key": "node_label"}
            )
            data_el.text = node.label
            for key, val in node.properties.items():
                pd = ET.SubElement(
                    node_el, f"{{{graphml_ns}}}data", {"key": f"prop_{key}"}
                )
                pd.text = str(val)

        # Write edges
        for edge in self.doc.edges:
            edge_el = ET.SubElement(
                graph, f"{{{graphml_ns}}}edge",
                {
                    "id": str(edge.id),
                    "source": str(edge.source),
                    "target": str(edge.target),
                },
            )
            data_el = ET.SubElement(
                edge_el, f"{{{graphml_ns}}}data", {"key": "edge_label"}
            )
            data_el.text = edge.label
            for key, val in edge.properties.items():
                pd = ET.SubElement(
                    edge_el, f"{{{graphml_ns}}}data", {"key": f"prop_{key}"}
                )
                pd.text = str(val)

        tree = ET.ElementTree(root)
        tree.write(path, encoding="utf-8", xml_declaration=True)
        logger.info(
            "Exported GraphML to %s (%d nodes, %d edges)",
            path,
            len(self.doc.nodes),
            len(self.doc.edges),
        )
        return path

    # ── internal helpers ──────────────────────────────────────────

    @staticmethod
    def _make_key(id: str, for_type: str, attr_type: str) -> ET.Element:
        """Build a GraphML <key> element declaring an attribute schema."""
        graphml_ns = "http://graphml.graphdrawing.org/xmlns"
        return ET.Element(
            f"{{{graphml_ns}}}key",
            {
                "id": id,
                "for": for_type,
                "attr.name": id,
                "attr.type": attr_type,
            },
        )

    @staticmethod
    def export_string(doc: GraphDocument, format: str) -> str:
        """Return the graph as a string (no file I/O).

        Useful for embedding or debugging.

        Args:
            doc: The GraphDocument to serialize.
            format: "json" or "graphml".

        Returns:
            The serialized string content.
        """
        format = format.lower().lstrip(".")
        if format == "json":
            return json.dumps(doc.to_dict(), indent=2, default=str)
        elif format == "graphml":
            exporter = GraphExporter(doc)
            tmp_path = Path("__tmp_export__.graphml")
            try:
                exporter._export_graphml(tmp_path)
                return tmp_path.read_text(encoding="utf-8")
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
        raise ValueError(f"Unsupported format: {format}")
