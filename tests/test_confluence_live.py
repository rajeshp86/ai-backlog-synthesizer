"""Tests for `ConfluenceTool` live mode + markdown ↔ storage conversion.

All HTTP is patched. The tests cover:

  1. `get_page` in live mode hits the v2 pages endpoint with storage
     format, surfaces 404 / 401 / 5xx as `ToolError`
  2. `list_spaces` returns the v2 spaces array
  3. `create_page` POSTs the right body shape and parses the response
  4. The Confluence "storage" XHTML stripper unwraps tags and decodes
     HTML entities (`&mdash;`, `&amp;`)
  5. `markdown_to_confluence_storage` correctly converts the dialect
     of markdown the seed_confluence.py script uses
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tools.base import ToolError  # noqa: E402
from tools.confluence_tool import (  # noqa: E402
    ConfluenceTool,
    _strip_confluence_storage_format,
    markdown_to_confluence_storage,
)


# --------------------------------------------------------------- fakes


class _FakeResponse:
    def __init__(self, status: int, payload: dict | None = None, text: str = ""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text or ""

    def json(self):
        return self._payload


def _patch_http(monkeypatch, get_responder=None, post_responder=None):
    """Patch both requests.get and requests.post; capture every call."""
    captured_get: list[tuple[str, dict]] = []
    captured_post: list[tuple[str, dict]] = []

    import requests

    def _fake_get(url, *, params=None, auth=None, headers=None, timeout=None, **kw):
        captured_get.append((url, dict(params or {})))
        if get_responder is None:
            return _FakeResponse(200, {})
        return get_responder(url, params or {}, **kw)

    def _fake_post(url, *, json=None, auth=None, headers=None, timeout=None, **kw):
        captured_post.append((url, dict(json or {})))
        if post_responder is None:
            return _FakeResponse(200, {"id": "999", "_links": {"webui": "/spaces/SD/pages/999/X"}})
        return post_responder(url, json or {}, **kw)

    monkeypatch.setattr(requests, "get", _fake_get)
    monkeypatch.setattr(requests, "post", _fake_post)
    return captured_get, captured_post


def _live_confluence():
    return ConfluenceTool(
        mode="live",
        base_url="https://demo.atlassian.net",
        email="me@example.com",
        api_token="tok",
    )


# --------------------------------------------------------------- storage stripper


def test_strip_storage_format_unwraps_basic_tags():
    body = '<p>Hello <strong>world</strong></p><h2>Section</h2><p>Bye.</p>'
    out = _strip_confluence_storage_format(body)
    assert "Hello world" in out
    assert "Section" in out
    assert "Bye." in out
    # Tags themselves shouldn't survive
    assert "<p>" not in out
    assert "<strong>" not in out


def test_strip_storage_format_decodes_html_entities():
    """The previous bug was that `&mdash;` showed up as literal text. The
    fix routes through `html.unescape`."""
    body = "<p>Quantum Technologies &mdash; Architecture</p><p>You &amp; me</p>"
    out = _strip_confluence_storage_format(body)
    assert "&mdash;" not in out
    assert "—" in out
    assert "&amp;" not in out
    assert "&" in out


def test_strip_storage_format_handles_empty():
    assert _strip_confluence_storage_format("") == ""
    assert _strip_confluence_storage_format(None) == ""


def test_strip_storage_format_collapses_blank_lines():
    body = "<p>One</p>\n\n\n\n<p>Two</p>"
    out = _strip_confluence_storage_format(body)
    # 4+ consecutive newlines collapse to exactly 2.
    assert "\n\n\n" not in out


# --------------------------------------------------------------- md → storage


def test_markdown_headings_become_h_tags():
    md = "# Title\n## Subtitle\n### Heading 3\n"
    out = markdown_to_confluence_storage(md)
    assert "<h1>Title</h1>" in out
    assert "<h2>Subtitle</h2>" in out
    assert "<h3>Heading 3</h3>" in out


def test_markdown_unordered_list_becomes_ul_li():
    md = "- one\n- two\n- three\n"
    out = markdown_to_confluence_storage(md)
    assert out.count("<ul>") == 1
    assert out.count("</ul>") == 1
    assert "<li>one</li>" in out
    assert "<li>two</li>" in out
    assert "<li>three</li>" in out


def test_markdown_ordered_list_becomes_ol_li():
    md = "1. one\n2. two\n"
    out = markdown_to_confluence_storage(md)
    assert "<ol>" in out
    assert "</ol>" in out
    assert "<li>one</li>" in out


def test_markdown_horizontal_rule():
    md = "Top\n\n---\n\nBottom\n"
    out = markdown_to_confluence_storage(md)
    assert "<hr/>" in out


def test_markdown_inline_bold_and_italic_and_code():
    md = "Some **bold** and *italic* and `code` text."
    out = markdown_to_confluence_storage(md)
    assert "<strong>bold</strong>" in out
    assert "<em>italic</em>" in out
    assert "<code>code</code>" in out


def test_markdown_fenced_code_block_becomes_storage_macro():
    md = "```\nfunction foo() { return 42; }\n```\n"
    out = markdown_to_confluence_storage(md)
    # Confluence storage uses the ac:structured-macro for code blocks.
    assert "ac:name=\"code\"" in out
    assert "function foo()" in out


def test_markdown_escapes_lt_gt_in_paragraphs():
    """Raw `<` and `>` in markdown must be escaped so they don't get
    interpreted as XHTML tags."""
    md = "Use `a < b` to test."
    out = markdown_to_confluence_storage(md)
    # The "a < b" inside the code span should be escaped.
    assert "a &lt; b" in out


def test_markdown_empty_input_returns_empty_string():
    assert markdown_to_confluence_storage("") == ""
    assert markdown_to_confluence_storage(None) == ""


# --------------------------------------------------------------- live mode


def test_get_page_live_calls_v2_pages_endpoint(monkeypatch):
    def responder(url, params, **kw):
        return _FakeResponse(200, {
            "title": "Test Page",
            "body": {"storage": {"value": "<p>Hello <strong>world</strong></p>"}},
        })
    captured_get, _ = _patch_http(monkeypatch, get_responder=responder)

    ct = _live_confluence()
    text = ct.get_page("65830")

    assert len(captured_get) == 1
    url, _ = captured_get[0]
    assert "/wiki/api/v2/pages/65830" in url
    assert "body-format=storage" in url
    # Returned text includes the title as an h1 prepended.
    assert "# Test Page" in text
    assert "Hello world" in text


def test_get_page_live_requires_credentials(monkeypatch):
    """Missing creds should raise ToolError up front.

    Clears the CONFLUENCE_* env vars so a developer with real
    credentials in `.env` doesn't accidentally satisfy the check.
    """
    for var in ("CONFLUENCE_BASE_URL", "CONFLUENCE_EMAIL", "CONFLUENCE_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    ct = ConfluenceTool(mode="live", base_url="", email="", api_token="")
    with pytest.raises(ToolError, match="CONFLUENCE_BASE_URL"):
        ct.get_page("65830")


def test_get_page_live_requires_real_page_id():
    """Live mode + page_id='default' is a programmer error — surface clearly."""
    ct = _live_confluence()
    with pytest.raises(ToolError, match="real page_id"):
        ct.get_page("default")


def test_get_page_live_404_raises(monkeypatch):
    def responder(url, params, **kw):
        return _FakeResponse(404, text="Page not found")
    _patch_http(monkeypatch, get_responder=responder)

    ct = _live_confluence()
    with pytest.raises(ToolError, match="not found"):
        ct.get_page("99999")


def test_get_page_live_401_raises_auth_error(monkeypatch):
    def responder(url, params, **kw):
        return _FakeResponse(401, text="bad token")
    _patch_http(monkeypatch, get_responder=responder)

    ct = _live_confluence()
    with pytest.raises(ToolError, match="auth failed"):
        ct.get_page("65830")


def test_get_page_live_5xx_raises_generic(monkeypatch):
    def responder(url, params, **kw):
        return _FakeResponse(503, text="service unavailable")
    _patch_http(monkeypatch, get_responder=responder)

    ct = _live_confluence()
    with pytest.raises(ToolError, match="503"):
        ct.get_page("65830")


def test_list_spaces_returns_results_array(monkeypatch):
    def responder(url, params, **kw):
        assert "/wiki/api/v2/spaces" in url
        return _FakeResponse(200, {"results": [
            {"id": "1", "key": "DEV",  "name": "Development", "type": "global"},
            {"id": "2", "key": "ME",   "name": "My Space",    "type": "personal"},
        ]})
    _patch_http(monkeypatch, get_responder=responder)

    spaces = _live_confluence().list_spaces()
    assert len(spaces) == 2
    assert spaces[0]["key"] == "DEV"
    assert spaces[1]["type"] == "personal"


def test_create_page_posts_storage_format(monkeypatch):
    def post_responder(url, payload, **kw):
        return _FakeResponse(200, {
            "id": "777",
            "_links": {"webui": "/spaces/DEV/pages/777/Test"},
        })
    _, captured_post = _patch_http(monkeypatch, post_responder=post_responder)

    ct = _live_confluence()
    page = ct.create_page(
        space_id="1",
        title="Test Page",
        body_storage="<p>Hello</p>",
    )

    assert page["id"] == "777"
    assert len(captured_post) == 1
    url, body = captured_post[0]
    assert url.endswith("/wiki/api/v2/pages")
    assert body["spaceId"] == "1"
    assert body["title"] == "Test Page"
    assert body["body"]["representation"] == "storage"
    assert body["body"]["value"] == "<p>Hello</p>"


def test_create_page_409_surfaces_conflict(monkeypatch):
    """A page with that title already existing → 409. The error message
    should be clear so seed_confluence.py can recognise it."""
    def post_responder(url, payload, **kw):
        return _FakeResponse(409, text='{"errors":[{"title":"already exists"}]}')
    _patch_http(monkeypatch, post_responder=post_responder)

    ct = _live_confluence()
    with pytest.raises(ToolError, match="rejected"):
        ct.create_page(space_id="1", title="Dup", body_storage="<p>x</p>")


def test_create_page_requires_live_mode():
    """Calling create_page in mock mode should error — there's nothing to write to."""
    ct = ConfluenceTool()  # default mock
    with pytest.raises(ToolError, match="requires CONFLUENCE_MODE=live"):
        ct.create_page(space_id="1", title="x", body_storage="<p>x</p>")


# --------------------------------------------------------------- mock fallback


def test_mock_mode_reads_default_page_path(tmp_path):
    page = tmp_path / "wiki.md"
    page.write_text("# Section\n\nBody.")
    ct = ConfluenceTool(default_page_path=page)
    assert ct.mode == "mock"
    assert "Section" in ct.get_page("ignored")


def test_mock_mode_no_fixture_raises():
    ct = ConfluenceTool()  # no fixture path
    with pytest.raises(ToolError, match="not configured"):
        ct.get_page("ignored")
