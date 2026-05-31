"""localRAGcoder — Graph Resident Engine.

A lightweight, embeddable graph database engine for OpenCode IDE workspaces.
Ingests text, builds a knowledge graph (Kùzu or JSON fallback), and exports
to GraphML / JSON for external visualization tools like Gephi.

Version: 1.0.0
Module: engine (package root)
"""

from .main import GraphResidentEngine
from .database import GraphDatabase
from .graph_exporter import GraphExporter

__all__ = ["GraphResidentEngine", "GraphDatabase", "GraphExporter"]
__version__ = "1.0.0"
