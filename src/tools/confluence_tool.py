"""Confluence tool — supports both a mocked fixture mode and a live REST mode.

Mock mode (default): reads a local markdown file passed at construction time
and returns it from `get_page()`.

Live mode: hits the Confluence Cloud REST API at
`/wiki/api/v2/pages/{id}` using Basic auth (email + API token). Credentials
come from the environment so the same code runs in CI with mocks and against
a real wiki in dev.

Environment variables read in live mode:
  CONFLUENCE_BASE_URL   e.g. https://your-tenant.atlassian.net
  CONFLUENCE_EMAIL      Atlassian account email
  CONFLUENCE_API_TOKEN  API token from id.atlassian.com/manage-profile/security/api-tokens
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

from logger_setup import get_logger
from tools.base import Tool, ToolError

logger = get_logger(__name__)

Mode = Literal["mock", "live"]


class ConfluenceTool(Tool):
    """Confluence page reader with mock + live modes.

    Defaults to mock so tests / CI / offline demos don't need credentials.
    Switch to live by passing `mode="live"` or by setting CONFLUENCE_MODE=live
    in the environment.
    """

    name = "confluence"

    def __init__(
        self,
        default_page_path: Path | None = None,
        *,
        mode: Mode | None = None,
        base_url: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
    ):
        self._default_page_path = Path(default_page_path) if default_page_path else None
        resolved_mode = (mode or os.environ.get("CONFLUENCE_MODE", "mock")).lower()
        if resolved_mode not in ("mock", "live"):
            raise ToolError(f"CONFLUENCE_MODE must be 'mock' or 'live' (got {resolved_mode!r}).")
        self._mode: Mode = resolved_mode  # type: ignore[assignment]
        self._base_url = (base_url or os.environ.get("CONFLUENCE_BASE_URL") or "").rstrip("/")
        self._email = email or os.environ.get("CONFLUENCE_EMAIL") or ""
        self._api_token = api_token or os.environ.get("CONFLUENCE_API_TOKEN") or ""

    @property
    def mode(self) -> Mode:
        return self._mode

    def get_page(self, page_id: str = "default") -> str:
        """Return the body of a wiki page as plain text.

        In mock mode `page_id` is ignored and the fixture file is returned.
        In live mode `page_id` must be a real Confluence page id.
        """
        if self._mode == "live":
            return self._fetch_live(page_id)
        return self._read_fixture()

    # ----------------------------------------------------- mock

    def _read_fixture(self) -> str:
        if not self._default_page_path or not self._default_page_path.exists():
            raise ToolError(
                "Confluence fixture not configured. Pass --constraints on the CLI "
                "to provide a wiki source, or construct ConfluenceTool with a path, "
                "or set CONFLUENCE_MODE=live with credentials."
            )
        return self._default_page_path.read_text(encoding="utf-8")

    # ----------------------------------------------------- live

    def _fetch_live(self, page_id: str) -> str:
        if not self._base_url or not self._email or not self._api_token:
            raise ToolError(
                "Confluence live mode requires CONFLUENCE_BASE_URL, "
                "CONFLUENCE_EMAIL and CONFLUENCE_API_TOKEN to be set."
            )
        if not page_id or page_id == "default":
            raise ToolError(
                "Live Confluence mode requires a real page_id (numeric or key)."
            )

        # Lazy import — keeps the dep optional for mock-only installs.
        try:
            import requests
        except ImportError as e:  # pragma: no cover
            raise ToolError(
                "The 'requests' package is required for live Confluence mode. "
                "Run: pip install requests"
            ) from e

        url = f"{self._base_url}/wiki/api/v2/pages/{page_id}?body-format=storage"
        try:
            resp = requests.get(
                url,
                auth=(self._email, self._api_token),
                headers={"Accept": "application/json"},
                timeout=20,
            )
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"Confluence request failed: {e}") from e

        if resp.status_code == 404:
            raise ToolError(f"Confluence page {page_id} not found.")
        if resp.status_code in (401, 403):
            raise ToolError(
                f"Confluence auth failed ({resp.status_code}). "
                "Check CONFLUENCE_EMAIL and CONFLUENCE_API_TOKEN."
            )
        if resp.status_code >= 400:
            raise ToolError(
                f"Confluence returned {resp.status_code}: {resp.text[:200]}"
            )

        data = resp.json()
        title = data.get("title", "")
        body = (data.get("body") or {}).get("storage", {}).get("value", "") or ""
        text = _strip_confluence_storage_format(body)
        # Prepend the page title so the constraint extractor has context
        return (f"# {title}\n\n" + text) if title else text

    # ----------------------------------------------------- live write

    def list_spaces(self, *, limit: int = 25) -> list[dict]:
        """Return Confluence spaces visible to the configured account.

        Each result: {id, key, name, type}. Caller uses `id` (or `key` on v1)
        to target a space for page creation. Requires live mode + credentials.
        """
        self._require_live()
        try:
            import requests
        except ImportError as e:  # pragma: no cover
            raise ToolError("'requests' package is required for live mode") from e

        url = f"{self._base_url}/wiki/api/v2/spaces?limit={int(limit)}"
        resp = requests.get(
            url,
            auth=(self._email, self._api_token),
            headers={"Accept": "application/json"},
            timeout=20,
        )
        if resp.status_code >= 400:
            raise ToolError(
                f"Confluence list_spaces returned {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json().get("results", [])

    def create_page(
        self,
        *,
        space_id: str,
        title: str,
        body_storage: str,
        parent_id: str | None = None,
    ) -> dict:
        """Create a Confluence page and return the parsed API response.

        `body_storage` must be Confluence storage-format XHTML. Use
        `markdown_to_confluence_storage()` (in this module) to convert a
        markdown source string before calling.

        Returns the page dict from the API, which includes the new page id
        and a `_links.webui` field — combine with `base_url + "/wiki" +
        webui` for a clickable URL.
        """
        self._require_live()
        try:
            import requests
        except ImportError as e:  # pragma: no cover
            raise ToolError("'requests' package is required for live mode") from e

        url = f"{self._base_url}/wiki/api/v2/pages"
        payload: dict[str, object] = {
            "spaceId": str(space_id),
            "status": "current",
            "title": title,
            "body": {"representation": "storage", "value": body_storage},
        }
        if parent_id:
            payload["parentId"] = str(parent_id)

        resp = requests.post(
            url,
            auth=(self._email, self._api_token),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        if resp.status_code in (400, 409):
            # 409 is the common "title already exists in space" response
            raise ToolError(
                f"Confluence create_page rejected ({resp.status_code}): {resp.text[:300]}"
            )
        if resp.status_code >= 400:
            raise ToolError(
                f"Confluence create_page failed {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json()

    def _require_live(self) -> None:
        if self._mode != "live":
            raise ToolError(
                "This operation requires CONFLUENCE_MODE=live and credentials."
            )
        if not self._base_url or not self._email or not self._api_token:
            raise ToolError(
                "Confluence live mode requires CONFLUENCE_BASE_URL, "
                "CONFLUENCE_EMAIL and CONFLUENCE_API_TOKEN to be set."
            )


# Lightweight HTML stripper — Confluence "storage" format is XHTML-ish.
# We don't ship a real HTML parser dependency just for this; the agent
# downstream is tolerant of extra whitespace and stray markup.
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")
_BLANK_RE = re.compile(r"\n{3,}")


def _strip_confluence_storage_format(body: str) -> str:
    """Remove XHTML tags and collapse whitespace from Confluence storage format.

    Block-level tags (p, h1-h6, li, br, table, tr) become newlines so the
    constraint extractor still sees structural cues; inline tags are dropped.
    """
    if not body:
        return ""
    # Promote block-level tag boundaries to newlines before stripping.
    body = re.sub(r"</?(p|h[1-6]|li|tr|br|table|div)[^>]*>", "\n", body, flags=re.I)
    body = _TAG_RE.sub("", body)
    # Decode common HTML entities, including the typographic dashes /
    # quotes Confluence emits in titles and body copy. Anything we miss
    # falls through unchanged — the constraint extractor is tolerant of
    # the occasional &foo; literal.
    import html as _html
    body = _html.unescape(body)
    body = _WS_RE.sub(" ", body)
    body = _BLANK_RE.sub("\n\n", body)
    return body.strip()


# ------------------------------------------------------------------ CLI helper
# Lets callers fetch a page from a script without instantiating the tool:
#     from tools.confluence_tool import fetch_confluence_text
#     text = fetch_confluence_text("123456789")
def fetch_confluence_text(page_id: str, *, mode: Mode | None = None) -> str:
    """Convenience wrapper for one-shot page fetches."""
    return ConfluenceTool(mode=mode).get_page(page_id)


# ------------------------------------------------------------------ md → storage
# Confluence v2 API accepts "storage" (XHTML-ish) or "atlas_doc_format" (ADF).
# A full markdown processor isn't worth the dependency for the small set of
# constructs the sample files use; this converter handles headings, lists,
# fenced code, paragraphs, and inline emphasis. Anything more exotic falls
# through as escaped text — readable, not pretty.

_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _apply_inline(text: str) -> str:
    """Apply inline markdown (escape first, then re-introduce safe tags)."""
    text = _html_escape(text)
    text = _INLINE_CODE_RE.sub(r"<code>\1</code>", text)
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)
    return text


def markdown_to_confluence_storage(md: str) -> str:
    """Convert a small dialect of markdown to Confluence storage XHTML.

    Supported:
      - ATX headings `#` … `######`
      - Unordered lists with `-` or `*` prefix
      - Ordered lists with `1.` prefix
      - Fenced code blocks ```…```
      - Paragraphs separated by blank lines
      - Inline `**bold**`, `*italic*`, `` `code` ``

    Tables, footnotes, and HTML pass-through aren't supported — they'll
    render as literal text. The two sample wiki files in this repo only
    use the supported subset.
    """
    if not md:
        return ""
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    in_list: str | None = None  # "ul" | "ol" | None

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None

    while i < len(lines):
        line = lines[i]

        # Fenced code blocks — capture until the closing fence.
        if line.lstrip().startswith("```"):
            close_list()
            i += 1
            code_lines: list[str] = []
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            out.append(
                '<ac:structured-macro ac:name="code"><ac:plain-text-body>'
                f'<![CDATA[{chr(10).join(code_lines)}]]>'
                '</ac:plain-text-body></ac:structured-macro>'
            )
            continue

        # Horizontal rule
        if re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", line):
            close_list()
            out.append("<hr/>")
            i += 1
            continue

        # Headings
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            close_list()
            level = len(m.group(1))
            content = _apply_inline(m.group(2).strip())
            out.append(f"<h{level}>{content}</h{level}>")
            i += 1
            continue

        # Ordered list item
        m = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m:
            if in_list != "ol":
                close_list()
                out.append("<ol>")
                in_list = "ol"
            out.append(f"<li>{_apply_inline(m.group(1).strip())}</li>")
            i += 1
            continue

        # Unordered list item
        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m:
            if in_list != "ul":
                close_list()
                out.append("<ul>")
                in_list = "ul"
            out.append(f"<li>{_apply_inline(m.group(1).strip())}</li>")
            i += 1
            continue

        # Blank line — close any open list, paragraph break
        if not line.strip():
            close_list()
            i += 1
            continue

        # Plain paragraph (may span multiple lines until blank or block-start)
        close_list()
        para = [line.strip()]
        i += 1
        while (
            i < len(lines)
            and lines[i].strip()
            and not lines[i].lstrip().startswith(("#", "- ", "* ", "```"))
            and not re.match(r"^\s*\d+\.\s+", lines[i])
        ):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_apply_inline(' '.join(para))}</p>")

    close_list()
    return "\n".join(out)
