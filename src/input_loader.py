"""Input loading: text, markdown, PDF, and JSON ticket exports.

Same shape as the v1 loader, but with an extra `load_tickets` helper that
returns a list of dicts whether the source is JIRA-style or GitHub-style.
"""

from __future__ import annotations

import json
from pathlib import Path

from logger_setup import get_logger

logger = get_logger(__name__)

SUPPORTED_TEXT_EXTS = {".txt", ".md", ".markdown"}


class InputError(Exception):
    """Raised when an input file can't be read or has the wrong format."""


def load_text(path_str: str) -> str:
    """Load a transcript / wiki / strategy doc as raw text. Supports txt, md, pdf."""
    path = Path(path_str)
    if not path.exists():
        raise InputError(f"File not found: {path}")
    if not path.is_file():
        raise InputError(f"Not a file: {path}")

    suffix = path.suffix.lower()
    if suffix in SUPPORTED_TEXT_EXTS:
        return _read_text(path)
    if suffix == ".pdf":
        return _read_pdf(path)
    raise InputError(f"Unsupported file type: {suffix!r}. Supported: .txt, .md, .pdf")


def load_tickets(path_str: str) -> list[dict]:
    """Load existing JIRA or GitHub tickets from a JSON file.

    Supported shapes:
      - JIRA-style: `[{"key": "AD-101", "summary": "...", "description": "...", ...}, ...]`
      - GitHub-style: `[{"number": 42, "title": "...", "body": "...", ...}, ...]`
      - Wrapper object: `{"items": [...]}`

    Returns a normalized list of dicts with at minimum `id`, `title`, `description`.
    """
    path = Path(path_str)
    if not path.exists():
        raise InputError(f"Ticket file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise InputError(f"Ticket file is not valid JSON: {e}")

    if isinstance(data, dict) and isinstance(data.get("items"), list):
        data = data["items"]
    if not isinstance(data, list):
        raise InputError("Ticket file must be a JSON list, or an object with an 'items' list.")

    normalized = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            logger.warning("Skipping ticket %d: not an object", i)
            continue
        normed = _normalize_ticket(item)
        if normed is None:
            logger.warning("Skipping ticket %d: missing title/summary", i)
            continue
        normalized.append(normed)
    return normalized


def _normalize_ticket(item: dict) -> dict | None:
    """Normalize JIRA- or GitHub-shaped ticket into a common dict."""
    title = item.get("title") or item.get("summary")
    description = item.get("description") or item.get("body") or ""
    if not title:
        return None
    return {
        "id": item.get("key") or item.get("id") or f"#{item.get('number', '?')}",
        "title": title,
        "description": description,
        "status": item.get("status", "unknown"),
        "labels": item.get("labels", []),
        "raw": item,
    }


# -------------------------------------------------------------------- helpers

def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise InputError(
            "pypdf is required for PDF input. Run: pip install -r requirements.txt"
        ) from e

    try:
        reader = PdfReader(str(path))
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"--- Page {i + 1} ---\n{text}")
        if not pages:
            raise InputError(
                f"No extractable text in {path}. The PDF may be image-based and require OCR."
            )
        return "\n\n".join(pages)
    except InputError:
        raise
    except Exception as e:
        raise InputError(f"Could not read PDF {path}: {e}") from e
