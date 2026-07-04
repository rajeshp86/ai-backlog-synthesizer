"""Tests for `JiraTool` live mode.

We never hit the real Atlassian API here — the HTTP calls go through a
patched `requests.get` that returns canned JSON. The goal is to verify:

  1. The tool selects the correct REST endpoint and JQL
  2. Pagination via `nextPageToken` works
  3. The 401/403 path raises `ToolError` with a clear message
  4. `_normalise_issue` flattens Atlassian's response into the
     internal ticket shape every downstream agent expects
  5. ADF descriptions get walked to plain text
  6. Mock mode still reads from the bundled fixture without any HTTP

Tests use `monkeypatch` to swap `requests.get` so they run offline and
without burning Anthropic credit. The full suite finishes in <100ms.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tools.base import ToolError  # noqa: E402
from tools.jira_tool import JiraTool, _adf_to_text, _normalise_issue  # noqa: E402


# --------------------------------------------------------------- fakes


class _FakeResponse:
    """Minimal stand-in for `requests.Response` with the fields jira_tool
    actually touches."""
    def __init__(self, status: int, payload: dict | None = None, text: str = ""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text or ""

    def json(self):
        return self._payload


def _patch_get(monkeypatch, responder):
    """Helper: patch `requests.get` and capture every call.

    `responder(url, params, **kwargs)` is invoked per call and must return
    a `_FakeResponse`. The list of captured `(url, params)` tuples is
    returned so tests can assert on what was requested.
    """
    captured: list[tuple[str, dict]] = []

    import requests

    def _fake_get(url, *, params=None, auth=None, headers=None, timeout=None, **kwargs):
        captured.append((url, dict(params or {})))
        return responder(url, params or {}, **kwargs)

    monkeypatch.setattr(requests, "get", _fake_get)
    return captured


# --------------------------------------------------------------- adapter unit


def test_normalise_issue_flattens_to_internal_shape():
    issue = {
        "key": "AD-101",
        "fields": {
            "summary": "Enable offline playback logging on the TV client",
            "description": {
                "type": "doc",
                "content": [
                    {"type": "paragraph",
                     "content": [{"type": "text", "text": "TV client needs"}]},
                    {"type": "paragraph",
                     "content": [{"type": "text", "text": "local cache fallback."}]},
                ],
            },
            "status":   {"name": "To Do"},
            "priority": {"name": "High"},
            "labels":   ["telemetry", "offline"],
        },
    }
    out = _normalise_issue(issue)
    assert out["id"] == "AD-101"
    assert out["title"] == "Enable offline playback logging on the TV client"
    assert out["summary"] == out["title"]   # both populated for back-compat
    assert "TV client needs" in out["description"]
    assert "local cache" in out["description"]
    assert out["status"] == "To Do"
    assert out["priority"] == "High"
    assert out["labels"] == ["telemetry", "offline"]
    assert out["raw"] is issue   # raw preserved for any caller that needs it


def test_normalise_issue_tolerates_missing_fields():
    """A barely-populated issue must not crash the adapter."""
    out = _normalise_issue({"key": "AD-1", "fields": {"summary": "x"}})
    assert out["id"] == "AD-1"
    assert out["title"] == "x"
    assert out["description"] == ""
    assert out["status"] == ""
    assert out["priority"] == ""
    assert out["labels"] == []


def test_normalise_issue_with_string_description():
    """Some old-API responses use a plain string for description."""
    out = _normalise_issue({"key": "AD-1", "fields": {
        "summary": "x", "description": "Simple text body."
    }})
    assert out["description"] == "Simple text body."


def test_adf_to_text_walks_nested_structure():
    adf = {
        "type": "doc",
        "content": [
            {"type": "heading",
             "content": [{"type": "text", "text": "Acceptance criteria"}]},
            {"type": "bulletList", "content": [
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": [
                        {"type": "text", "text": "When offline, sale completes."}]}
                ]},
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": [
                        {"type": "text", "text": "When online, sync reconciles."}]}
                ]},
            ]},
        ],
    }
    text = _adf_to_text(adf)
    assert "Acceptance criteria" in text
    assert "When offline" in text
    assert "When online" in text


def test_adf_to_text_handles_empty_input():
    assert _adf_to_text(None) == ""
    assert _adf_to_text("") == ""
    assert _adf_to_text({}) == ""


# --------------------------------------------------------------- mock mode


def test_mock_mode_reads_fixture(tmp_path):
    """Mock mode = default. Reads from the bundled JSON. No HTTP."""
    fixture = tmp_path / "tickets.json"
    fixture.write_text(
        '[{"key": "AD-1", "summary": "Test", "description": "x", '
        '"status": "open", "labels": ["test"]}]'
    )
    jt = JiraTool(fixture_path=fixture)
    assert jt.mode == "mock"
    tickets = jt.list_all()
    assert len(tickets) == 1
    assert tickets[0]["key"] == "AD-1"


def test_mock_mode_search_substring(tmp_path):
    fixture = tmp_path / "tickets.json"
    fixture.write_text(
        '[{"summary": "Takedown notification SMS", "description": ""},'
        ' {"summary": "Subscription services email", "description": ""}]'
    )
    jt = JiraTool(fixture_path=fixture)
    out = jt.search("takedown")
    assert len(out) == 1
    assert "Takedown" in out[0]["summary"]


# --------------------------------------------------------------- live mode


def _live_jira(env_token: str = "tok"):
    """Build a JiraTool in live mode with bogus-but-non-empty credentials.

    The HTTP call is mocked, so the credentials never travel anywhere.
    """
    return JiraTool(
        mode="live",
        base_url="https://demo.atlassian.net",
        email="me@example.com",
        api_token=env_token,
        project_key="MM",
    )


def test_live_mode_requires_credentials(monkeypatch):
    """Missing creds should raise ToolError up front, not on first call.

    Clears the JIRA_* env vars so a developer with real credentials in
    `.env` doesn't accidentally satisfy the "missing" check.
    """
    for var in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    jt = JiraTool(mode="live", base_url="", email="", api_token="", project_key="MM")
    with pytest.raises(ToolError, match="JIRA_BASE_URL"):
        jt.list_all()


def test_live_list_all_uses_jql_search_endpoint(monkeypatch):
    """list_all() must POST/GET to /rest/api/3/search/jql with the
    project-scoped JQL the adapter builds."""
    def responder(url, params, **kw):
        return _FakeResponse(200, {
            "issues": [
                {"key": "AD-100", "fields": {"summary": "Test 1", "status": {"name": "To Do"}}},
                {"key": "AD-101", "fields": {"summary": "Test 2", "status": {"name": "Done"}}},
            ],
            # No nextPageToken — single page.
        })
    captured = _patch_get(monkeypatch, responder)

    jt = _live_jira()
    tickets = jt.list_all()

    assert len(captured) == 1
    url, params = captured[0]
    assert url.endswith("/rest/api/3/search/jql")
    assert 'project = "MM"' in params["jql"]
    assert "ORDER BY created DESC" in params["jql"]
    assert "summary" in params["fields"]   # field allowlist applied
    assert len(tickets) == 2
    assert tickets[0]["id"] == "AD-100"
    assert tickets[1]["title"] == "Test 2"


def test_live_list_all_paginates_via_next_page_token(monkeypatch):
    """When the response carries `nextPageToken`, the tool must fetch
    the next page and append. Stops when the token disappears."""
    pages = [
        {"issues": [{"key": f"AD-{i}", "fields": {"summary": f"S{i}"}} for i in range(50)],
         "nextPageToken": "page2"},
        {"issues": [{"key": f"AD-{i}", "fields": {"summary": f"S{i}"}} for i in range(50, 75)]},
    ]
    state = {"call": 0}
    def responder(url, params, **kw):
        out = _FakeResponse(200, pages[state["call"]])
        state["call"] += 1
        return out

    captured = _patch_get(monkeypatch, responder)
    jt = _live_jira()
    tickets = jt.list_all()

    assert len(captured) == 2
    assert "nextPageToken" not in captured[0][1]
    assert captured[1][1].get("nextPageToken") == "page2"
    assert len(tickets) == 75


def test_live_list_all_caps_at_max_results(monkeypatch):
    """The `max_results` constructor cap stops a runaway corpus from
    consuming the orchestrator. Default is 200; we set it lower here so
    the test is fast."""
    # Each page returns 50 issues + always has a nextPageToken, so without
    # the cap the loop would never terminate.
    def responder(url, params, **kw):
        return _FakeResponse(200, {
            "issues": [{"key": f"AD-{i}", "fields": {"summary": "x"}} for i in range(50)],
            "nextPageToken": "more",
        })
    _patch_get(monkeypatch, responder)

    jt = JiraTool(
        mode="live", base_url="https://demo.atlassian.net",
        email="me@example.com", api_token="tok",
        project_key="MM", max_results=120,
    )
    tickets = jt.list_all()
    assert len(tickets) == 120


def test_live_search_wraps_plain_string_in_text_query(monkeypatch):
    """Plain strings should be wrapped as `text ~ "..."` JQL, scoped to
    the configured project. Full JQL strings pass through unchanged."""
    captured_jqls: list[str] = []
    def responder(url, params, **kw):
        captured_jqls.append(params["jql"])
        return _FakeResponse(200, {"issues": []})
    _patch_get(monkeypatch, responder)

    jt = _live_jira()
    jt.search("takedown notification")
    assert 'project = "MM"' in captured_jqls[-1]
    assert 'text ~ "takedown notification"' in captured_jqls[-1]

    # Pass full JQL through unchanged.
    jt.search('project = "MM" AND status = "Done"')
    assert captured_jqls[-1] == 'project = "MM" AND status = "Done"'


def test_live_search_escapes_double_quotes(monkeypatch):
    """A query containing `"` shouldn't break the JQL clause."""
    captured_jqls: list[str] = []
    def responder(url, params, **kw):
        captured_jqls.append(params["jql"])
        return _FakeResponse(200, {"issues": []})
    _patch_get(monkeypatch, responder)

    jt = _live_jira()
    jt.search('say "hello"')
    # Escaped backslash-quote form is what Jira expects.
    assert '\\"hello\\"' in captured_jqls[-1]


def test_live_401_raises_clear_error(monkeypatch):
    def responder(url, params, **kw):
        return _FakeResponse(401, text="not authorised")
    _patch_get(monkeypatch, responder)

    jt = _live_jira()
    with pytest.raises(ToolError, match="auth failed"):
        jt.list_all()


def test_live_400_surfaces_jql_error(monkeypatch):
    """Invalid JQL → 400 with a body explaining why. We surface the body
    head (clipped) so the user sees what Jira complained about."""
    def responder(url, params, **kw):
        return _FakeResponse(400, text="Field 'foo' does not exist")
    _patch_get(monkeypatch, responder)

    jt = _live_jira()
    with pytest.raises(ToolError, match="rejected JQL"):
        jt.search("nope ~ 'bad'")


def test_live_500_raises_generic_error(monkeypatch):
    def responder(url, params, **kw):
        return _FakeResponse(500, text="server is on fire")
    _patch_get(monkeypatch, responder)

    jt = _live_jira()
    with pytest.raises(ToolError, match="500"):
        jt.list_all()


def test_live_caches_first_list_all(monkeypatch):
    """list_all() caches the first call so the orchestrator doesn't
    paginate twice on the same run."""
    call_count = {"n": 0}
    def responder(url, params, **kw):
        call_count["n"] += 1
        return _FakeResponse(200, {
            "issues": [{"key": "AD-1", "fields": {"summary": "x"}}],
        })
    _patch_get(monkeypatch, responder)

    jt = _live_jira()
    jt.list_all()
    jt.list_all()
    assert call_count["n"] == 1, "Second list_all() should hit the cache, not the API"


# --------------------------------------------------------------- write tests

def _patch_post(monkeypatch, responder):
    """Patch `requests.post` and capture each call's JSON body."""
    captured: list[dict] = []
    import requests

    def _fake_post(url, *, json=None, auth=None, headers=None, timeout=None, **kwargs):
        captured.append({"url": url, "fields": (json or {}).get("fields", {})})
        return responder(url, json or {}, **kwargs)

    monkeypatch.setattr(requests, "post", _fake_post)
    return captured


def _live_writer():
    return JiraTool(
        mode="live", base_url="https://t.atlassian.net",
        email="a@b.c", api_token="tok", project_key="MM",
    )


def test_create_issue_success_returns_key_and_url(monkeypatch):
    def responder(url, body, **kw):
        return _FakeResponse(201, {"key": "AD-7"})
    _patch_post(monkeypatch, responder)
    from tools.jira_tool import _text_adf
    out = _live_writer().create_issue(
        summary="Offline playback logging", description_adf=_text_adf("x"),
        issue_type="Story", labels=["telemetry", "offline mode"],
    )
    assert out["key"] == "AD-7"
    assert out["url"] == "https://t.atlassian.net/browse/AD-7"


def test_create_issue_sanitizes_labels(monkeypatch):
    cap = _patch_post(monkeypatch, lambda u, b, **k: _FakeResponse(201, {"key": "AD-8"}))
    from tools.jira_tool import _text_adf
    _live_writer().create_issue(summary="s", description_adf=_text_adf("x"),
                                labels=["offline mode", "telemetry"])
    assert cap[0]["fields"]["labels"] == ["offline-mode", "telemetry"]  # spaces -> hyphens


def test_create_issue_falls_back_when_parent_rejected(monkeypatch):
    # First attempt (with parent) 400s; fallback without parent succeeds.
    seq = [_FakeResponse(400, text="parent not allowed"), _FakeResponse(201, {"key": "AD-9"})]
    _patch_post(monkeypatch, lambda u, b, **k: seq.pop(0))
    from tools.jira_tool import _text_adf
    out = _live_writer().create_issue(summary="s", description_adf=_text_adf("x"),
                                      issue_type="Sub-task", parent_key="AD-1")
    assert out["key"] == "AD-9"


def test_create_issue_auth_failure_raises(monkeypatch):
    _patch_post(monkeypatch, lambda u, b, **k: _FakeResponse(401, text="nope"))
    from tools.jira_tool import _text_adf
    with pytest.raises(ToolError):
        _live_writer().create_issue(summary="s", description_adf=_text_adf("x"))


def test_publish_synthesis_creates_epic_story_subtask(monkeypatch):
    n = {"i": 0}
    def responder(url, body, **kw):
        n["i"] += 1
        return _FakeResponse(201, {"key": f"AD-{100 + n['i']}"})
    cap = _patch_post(monkeypatch, responder)

    result = {"epics": [{
        "id": "EP-01", "title": "Telemetry Offline", "description": "keep logging",
        "stories": [{
            "id": "ST-01", "title": "Offline playback logging", "description": "d",
            "user_story": "As a viewer...", "acceptance_criteria": ["Given... then..."],
            "priority": "High", "priority_rationale": "revenue", "tags": ["telemetry"],
            "source_topic_id": "T-01", "potential_constraint_conflicts": ["C-02"],
            "tasks": [{"id": "ST-01-TK-01", "title": "Embed local cache", "type": "infra"}],
        }],
    }]}
    out = _live_writer().publish_synthesis(result, create_subtasks=True)

    assert out["counts"] == {"epics": 1, "stories": 1, "subtasks": 1}
    types = [c["fields"]["issuetype"]["name"] for c in cap]
    assert types == ["Epic", "Story", "Sub-task"]
    # Story is parented to the epic; sub-task to the story.
    assert cap[1]["fields"]["parent"]["key"] == "AD-101"
    assert cap[2]["fields"]["parent"]["key"] == "AD-102"


def test_publish_synthesis_partial_failure_is_recorded(monkeypatch):
    # The epic fails on *every* fallback (incl. the Task fallback); the story
    # still gets created. Key the failure off the summary so only the epic dies.
    def responder(url, body, **kw):
        if body.get("fields", {}).get("summary") == "E":
            return _FakeResponse(400, text="no epic type")
        return _FakeResponse(201, {"key": "AD-200"})
    _patch_post(monkeypatch, responder)
    result = {"epics": [{"title": "E", "stories": [{"title": "S", "tasks": []}]}]}
    out = _live_writer().publish_synthesis(result, create_subtasks=False)
    assert out["counts"]["stories"] == 1
    assert any("epic" in e.lower() for e in out["errors"])
