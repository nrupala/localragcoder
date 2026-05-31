"""Multi-format file ingestion pipeline.

Extracts text from PDF, DOCX, TXT, MD, HTML, JSON, CSV, ODT, RTF,
and other common document formats.  Chunks the extracted text and
prepares it for embedding and storage.

Version: 1.0.0
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import io
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Optional parsers
try:
    import fitz  # PyMuPDF

    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    import docx

    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

try:
    from bs4 import BeautifulSoup

    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

try:
    import markdown

    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False


class IngestionError(Exception):
    """Raised when a file cannot be ingested."""


# ── format detection ─────────────────────────────────────────

EXTENSION_MAP = {
    ".pdf": "pdf",
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
    ".html": "html",
    ".htm": "html",
    ".json": "json",
    ".csv": "csv",
    ".tsv": "csv",
    ".docx": "docx",
    ".doc": "doc",
    ".odt": "odt",
    ".rtf": "rtf",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".log": "txt",
    ".cfg": "txt",
    ".ini": "txt",
    ".conf": "txt",
    ".py": "txt",
    ".js": "txt",
    ".ts": "txt",
    ".jsx": "txt",
    ".tsx": "txt",
    ".java": "txt",
    ".c": "txt",
    ".cpp": "txt",
    ".h": "txt",
    ".rs": "txt",
    ".go": "txt",
    ".rb": "txt",
    ".php": "txt",
    ".sql": "txt",
    ".sh": "txt",
    ".bat": "txt",
    ".ps1": "txt",
}


def detect_filetype(path: Path) -> str:
    """Detect file type by extension.

    Returns:
        A short type string: "pdf", "docx", "txt", "md", "html",
        "json", "csv", "odt", "rtf", etc.  Defaults to "txt".
    """
    ext = path.suffix.lower()
    return EXTENSION_MAP.get(ext, "txt")


# ── individual extractors ────────────────────────────────────


def _extract_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _extract_md(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if MARKDOWN_AVAILABLE:
        html = markdown.markdown(raw)
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser").get_text()
    return raw


def _extract_html(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if BS4_AVAILABLE:
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    return re.sub(r"<[^>]+>", " ", raw)


def _extract_json(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return json.dumps(data, indent=2, default=str)


def _extract_csv(path: Path) -> str:
    lines = []
    with open(str(path), encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        for row in reader:
            lines.append(" | ".join(row))
    return "\n".join(lines)


def _extract_docx(path: Path) -> str:
    if not DOCX_AVAILABLE:
        raise IngestionError("python-docx not installed")
    doc = docx.Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs]
    # Also extract tables
    for table in doc.tables:
        for row in table.rows:
            paragraphs.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(paragraphs)


def _extract_pdf(path: Path) -> str:
    if not PYMUPDF_AVAILABLE:
        raise IngestionError("PyMuPDF (fitz) not installed — try: pip install pymupdf")
    doc = fitz.open(str(path))
    pages = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        pages.append(page.get_text())
    doc.close()
    return "\n".join(pages)


def _extract_odt(path: Path) -> str:
    """Extract text from ODT by unzipping and parsing content.xml."""
    import zipfile
    try:
        with zipfile.ZipFile(str(path), "r") as z:
            if "content.xml" not in z.namelist():
                raise IngestionError("Invalid ODT file: missing content.xml")
            xml_data = z.read("content.xml").decode("utf-8", errors="replace")
    except zipfile.BadZipFile:
        raise IngestionError("Invalid ODT file (not a zip archive)")
    if BS4_AVAILABLE:
        soup = BeautifulSoup(xml_data, "xml")
        return soup.get_text(separator="\n", strip=True)
    return re.sub(r"<[^>]+>", " ", xml_data)


def _extract_rtf(path: Path) -> str:
    """Crude RTF-to-text extraction."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    # Strip RTF control words and braces
    text = re.sub(r"\\([a-z]+)(-?\d+)?", " ", raw)
    text = re.sub(r"[{}]", " ", text)
    text = re.sub(r"\\'[0-9a-f]{2}", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


EXTRACTORS: dict[str, callable] = {
    "txt": _extract_txt,
    "md": _extract_md,
    "html": _extract_html,
    "htm": _extract_html,
    "json": _extract_json,
    "csv": _extract_csv,
    "tsv": _extract_csv,
    "docx": _extract_docx,
    "doc": _extract_docx,  # best effort for .doc
    "pdf": _extract_pdf,
    "odt": _extract_odt,
    "rtf": _extract_rtf,
}


# ── chunking ─────────────────────────────────────────────────


def chunk_text(text: str, chunk_size: int = 512,
               overlap: int = 64) -> list[str]:
    """Split text into overlapping chunks by word count.

    Args:
        text: The full document text.
        chunk_size: Target number of words per chunk.
        overlap: Number of overlapping words between chunks.

    Returns:
        List of text chunks.
    """
    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return chunks


# ── public API ────────────────────────────────────────────────


def extract_text(path: str | Path, filetype: str | None = None) -> str:
    """Extract text from a file in any supported format.

    Args:
        path: Path to the file.
        filetype: Override file type detection (optional).

    Returns:
        Extracted plain text.

    Raises:
        IngestionError: If the format is unsupported or a required
            library is missing.
    """
    p = Path(path)
    if not p.exists():
        raise IngestionError(f"File not found: {path}")
    if not p.is_file():
        raise IngestionError(f"Not a file: {path}")

    ft = (filetype or detect_filetype(p)).lower().lstrip(".")
    extractor = EXTRACTORS.get(ft)
    if extractor is None:
        raise IngestionError(f"Unsupported file type: {ft}")

    logger.info("Extracting text from %s (%s)", p.name, ft)
    return extractor(p)


def ingest_file(path: str | Path, chunk_size: int = 512,
                overlap: int = 64,
                filetype: str | None = None) -> dict:
    """Full ingestion pipeline for a single file.

    Returns a dict with:
        - filename, filetype, size_bytes
        - text: the full extracted text
        - chunks: list of text chunks
        - chunk_count

    Args:
        path: Path to the file.
        chunk_size: Words per chunk.
        overlap: Overlap between chunks.
        filetype: Override file type detection.

    Raises:
        IngestionError: On failure.
    """
    p = Path(path)
    ft = filetype or detect_filetype(p)
    text = extract_text(p, ft)
    chunks = chunk_text(text, chunk_size, overlap)
    return {
        "filename": p.name,
        "filetype": ft,
        "size_bytes": p.stat().st_size,
        "text": text,
        "chunks": chunks,
        "chunk_count": len(chunks),
    }
