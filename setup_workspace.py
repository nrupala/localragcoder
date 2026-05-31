"""Workspace Matrix Initializer for localRAGcoder.

Creates the full folder hierarchy, installs dependencies, verifies
imports, creates default VS Code settings, and bootstraps the graph
database — all in one shot.

Usage:
    python setup_workspace.py

Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("setup")


def run() -> None:
    """Execute the full workspace initialization routine.

    Steps:
        1. Create directory hierarchy (engine/, .vscode/, data/, exports/).
        2. Install Python dependencies from requirements.txt.
        3. Verify that the engine package imports cleanly.
        4. Create ``.vscode/settings.json`` with sensible defaults.
        5. Bootstrap the graph database so it is ready on first use.
    """
    root = Path(__file__).parent.resolve()

    logger.info("=== localRAGcoder — Workspace Matrix Initializer ===\n")

    # ── 1. Create folder hierarchy ────────────────────────────
    dirs = [
        root / "engine",
        root / ".vscode",
        root / "data" / "vector_store",
        root / "data" / "graph_store",
        root / "exports",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        logger.info("  \u2713  %s", d.relative_to(root))

    # ── 2. Install Python dependencies ────────────────────────
    req = root / "requirements.txt"
    if req.exists():
        logger.info("\n  Installing dependencies...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-r", str(req)]
            )
            logger.info("  \u2713  Dependencies installed")
        except Exception as e:
            logger.warning(
                "  \u26a0  Pip install failed (%s) — Kùzu not available, "
                "using JSON fallback",
                e,
            )

    # ── 3. Verify engine imports ──────────────────────────────
    logger.info("\n  Verifying engine imports...")
    try:
        from engine.main import GraphResidentEngine  # noqa: F401

        logger.info("  \u2713  Engine imports OK")
    except Exception as e:
        logger.warning("  \u26a0  Engine import failed: %s", e)

    # ── 4. Create .vscode/settings.json if missing ────────────
    settings_path = root / ".vscode" / "settings.json"
    if not settings_path.exists():
        settings = {
            "engine.network.enabled": True,
            "engine.model.size": "small",
            "engine.embedding.path": "${workspaceFolder}/data/vector_store",
            "files.watcherExclude": {
                "**/engine/**": True,
                "**/data/**": True,
            },
        }
        settings_path.write_text(json.dumps(settings, indent=4) + "\n")
        logger.info("  \u2713  .vscode/settings.json created")
    else:
        logger.info("  \u00b7  .vscode/settings.json already exists")

    # ── 5. Initialize the graph database ──────────────────────
    logger.info("\n  Initializing graph database...")
    try:
        engine = GraphResidentEngine(root)
        stats = engine.get_stats()
        engine.close()
        logger.info(
            "  \u2713  Graph store ready (%s engine)",
            stats["database"]["engine"],
        )
    except Exception as e:
        logger.warning("  \u26a0  Graph init failed: %s", e)

    logger.info("\n=== Setup complete ===")
    logger.info(
        "Run `python -m engine.cli --help` to see available commands."
    )


if __name__ == "__main__":
    run()
