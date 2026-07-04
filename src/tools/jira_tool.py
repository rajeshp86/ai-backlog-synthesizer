"""JIRA tool — mocked fixture mode + live REST mode.

Mock mode (default): reads tickets from a local JSON file. Used by tests,
CI, and offline demos.

Live mode: hits the Jira Cloud REST API at `/rest/api/3/search/jql` with a
JQL query, paginates, and normalises every issue into the same dict shape
the Gap Detector expects: `{id, title, description, status, labels, raw}`.

Environment variables read in live mode:
  JIRA_BASE_URL        e.g. https://your-tenant.atlassian.net
  JIRA_EMAIL           Atlassian account email
  JIRA_API_TOKEN       API token from id.atlassian.com/manage-profile/security/api-tokens
  JIRA_PROJECT_KEY     Default project (used when search() is called with a
                       plain string instead of full JQL)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from logger_setup import get_logger
from tools.base import Tool, ToolError

logger = get_logger(__name__)

Mode = Literal["mock", "live"]

DEFAULT_FIXTURE = Path(__file__).parent.parent.parent / "samples" / "jira_backlog.json"


class JiraTool(Tool):
    """JIRA ticket reader with mock and live modes.

    The Gap Detector only needs `list_all()` and `search(query)`; both
    return a list of dicts shaped like the existing fixture. Live mode
    extracts the same fields from Atlassian's response shape so downstream
    code is unaffected by the swap.
    """

    name = "jira"

    def __init__(
        self,
        fixture_path: Path | None = None,
        *,
        mode: Mode | None = None,
        base_url: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
        project_key: str | None = None,
        page_size: int = 50,
        max_results: int | None = None,
    ):
        self._fixture_path = Path(fixture_path) if fixture_path else DEFAULT_FIXTURE
        self._cache: list[dict] | None = None

        resolved_mode = (mode or os.environ.get("JIRA_MODE", "mock")).lower()
        if resolved_mode not in ("mock", "live"):
            raise ToolError(f"JIRA_MODE must be 'mock' or 'live' (got {resolved_mode!r}).")
        self._mode: Mode = resolved_mode  # type: ignore[assignment]
        self._base_url = (base_url or os.environ.get("JIRA_BASE_URL") or "").rstrip("/")
        self._email = email or os.environ.get("JIRA_EMAIL") or ""
        self._api_token = api_token or os.environ.get("JIRA_API_TOKEN") or ""
        self._project_key = project_key or os.environ.get("JIRA_PROJECT_KEY") or ""
        self._page_size = int(page_size)
        # JIRA_MAX_RESULTS: total issues to fetch across all pages.
        # 0 or negative = no cap (fetch every page). Default 200 keeps costs
        # predictable on large backlogs; set JIRA_MAX_RESULTS=0 to lift the cap.
        _env_max = os.environ.get("JIRA_MAX_RESULTS")
        if max_results is not None:
            self._max_results = int(max_results)
        elif _env_max is not None:
            self._max_results = int(_env_max)
        else:
            self._max_results = 200

    @property
    def mode(self) -> Mode:
        return self._mode

    # ----------------------------------------------------- public API

    def list_all(self) -> list[dict]:
        """Return every visible ticket. Cached after first call per instance."""
        if self._cache is None:
            self._cache = self._load_live() if self._mode == "live" else self._load_fixture()
        return list(self._cache)

    def search(self, query: str) -> list[dict]:
        """Substring search in mock; JQL search in live.

        For live mode, a `query` that looks like JQL (contains `=`, `~`,
        `AND`, `ORDER`) is passed through; anything simpler is wrapped in
        a text-search clause scoped to the configured project key.
        """
        if self._mode != "live":
            all_tickets = self.list_all()
            q = query.lower()
            return [
                t for t in all_tickets
                if q in (t.get("summary") or t.get("title") or "").lower()
                or q in (t.get("description") or "").lower()
            ]
        # Live search
        return self._search_live(query)

    # ----------------------------------------------------- write (live)

    def create_issue(
        self,
        *,
        summary: str,
        description_adf: dict,
        issue_type: str = "Task",
        labels: list[str] | None = None,
        parent_key: str | None = None,
        project_key: str | None = None,
    ) -> dict:
        """Create a single Jira issue and return {key, url, type, summary}.

        Defensive, because Jira project configs differ wildly. We try the
        ideal shape first, then progressively drop the parts a project is
        most likely to reject — the `parent` link, then `labels`, then the
        requested `issuetype` (falling back to `Task`). Auth failures are
        raised immediately; they can't be retried away.
        """
        self._require_live_credentials()
        try:
            import requests
        except ImportError as e:  # pragma: no cover
            raise ToolError("'requests' package is required to create Jira issues") from e

        project = project_key or self._project_key
        if not project:
            raise ToolError("Creating Jira issues requires JIRA_PROJECT_KEY (or project_key=).")

        url = f"{self._base_url}/rest/api/3/issue"
        auth = (self._email, self._api_token)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        clean_labels = [_safe_label(x) for x in (labels or []) if x]

        def _attempt(itype: str, with_parent: bool, with_labels: bool):
            fields: dict = {
                "project": {"key": project},
                "summary": (summary or "(no title)")[:250],
                "description": description_adf,
                "issuetype": {"name": itype},
            }
            if with_parent and parent_key:
                fields["parent"] = {"key": parent_key}
            if with_labels and clean_labels:
                fields["labels"] = clean_labels
            return requests.post(url, json={"fields": fields}, auth=auth, headers=headers, timeout=30)

        # Progressive fallback: most-complete shape first.
        plans = [
            (issue_type, True, True),
            (issue_type, True, False),
            (issue_type, False, True),
            (issue_type, False, False),
            ("Task", False, False),
        ]
        last = None
        for itype, wp, wl in plans:
            resp = _attempt(itype, wp, wl)
            if resp.status_code in (401, 403):
                raise ToolError(
                    f"Jira auth failed ({resp.status_code}). Check JIRA_EMAIL / JIRA_API_TOKEN."
                )
            if resp.status_code < 400:
                key = resp.json().get("key", "")
                return {
                    "key": key,
                    "url": f"{self._base_url}/browse/{key}",
                    "type": itype,
                    "summary": summary,
                }
            last = resp
        raise ToolError(
            f"Jira create issue failed ({last.status_code if last else '?'}): "
            f"{last.text[:300] if last else 'no response'}"
        )

    def publish_synthesis(
        self,
        result: dict,
        *,
        project_key: str | None = None,
        create_subtasks: bool = True,
        label: str = "backlog-synth",
        max_issues: int = 300,
        progress=None,
    ) -> dict:
        """Create the synthesized backlog in live Jira as Epic → Story → Sub-task.

        - Each epic  → a `Epic` issue.
        - Each story → a `Story` issue, linked to its epic via `parent`, with
          the user story, acceptance criteria, priority rationale, conflict
          flags, and task list rendered into the description (so nothing is
          lost even if sub-task creation isn't permitted).
        - Each task  → a `Sub-task` under its story (best-effort; skipped for a
          story if the project rejects sub-tasks).

        Returns: {created: [...], errors: [...], counts: {...}, base_url, project}.
        Failures on one item are recorded and the rest continue — a partial
        publish is more useful in a live demo than an all-or-nothing abort.
        """
        self._require_live_credentials()
        project = project_key or self._project_key
        if not project:
            raise ToolError("Publishing to Jira requires JIRA_PROJECT_KEY (or project_key=).")

        def _emit(msg: str):
            if progress:
                try:
                    progress(msg)
                except Exception:  # noqa: BLE001 — a UI hook must never break the publish
                    pass

        created: list[dict] = []
        errors: list[str] = []
        count = 0

        for epic in result.get("epics") or []:
            if count >= max_issues:
                break
            epic_key = None
            try:
                e = self.create_issue(
                    summary=epic.get("title") or "Untitled epic",
                    description_adf=_text_adf(epic.get("description", "")),
                    issue_type="Epic",
                    labels=[label],
                    project_key=project,
                )
                created.append({**e, "level": "epic"})
                epic_key = e["key"]
                count += 1
                _emit(f"Epic {e['key']} — {e['summary'][:60]}")
            except ToolError as ex:
                errors.append(f"epic '{epic.get('title')}': {ex}")

            for story in epic.get("stories") or []:
                if count >= max_issues:
                    break
                story_key = None
                try:
                    s = self.create_issue(
                        summary=story.get("title") or "Untitled story",
                        description_adf=_story_adf(story),
                        issue_type="Story",
                        labels=[label, *(story.get("tags") or [])],
                        parent_key=epic_key,
                        project_key=project,
                    )
                    created.append({**s, "level": "story"})
                    story_key = s["key"]
                    count += 1
                    _emit(f"  Story {s['key']} — {s['summary'][:60]}")
                except ToolError as ex:
                    errors.append(f"story '{story.get('title')}': {ex}")
                    continue

                if create_subtasks and story_key:
                    made = 0
                    for task in story.get("tasks") or []:
                        if count >= max_issues:
                            break
                        try:
                            st = self.create_issue(
                                summary=task.get("title") or "Task",
                                description_adf=_text_adf(f"Type: {task.get('type', 'task')}"),
                                issue_type="Sub-task",
                                parent_key=story_key,
                                labels=[label],
                                project_key=project,
                            )
                            created.append({**st, "level": "subtask"})
                            made += 1
                            count += 1
                        except ToolError:
                            # Sub-tasks are config-sensitive; stop trying for this
                            # story. The tasks are still in the story description.
                            break
                    if made == 0 and (story.get("tasks")):
                        errors.append(
                            f"sub-tasks for {story_key}: project disallows sub-task "
                            f"creation — tasks remain listed in the story description."
                        )

        return {
            "created": created,
            "errors": errors,
            "counts": {
                "epics": sum(1 for c in created if c["level"] == "epic"),
                "stories": sum(1 for c in created if c["level"] == "story"),
                "subtasks": sum(1 for c in created if c["level"] == "subtask"),
            },
            "project": project,
            "base_url": self._base_url,
        }

    # ----------------------------------------------------- two-way sync

    def sync_published_stories(self, publish_result: dict) -> list[dict]:
        """Read back current status of previously published stories from live Jira.

        Given a `publish_result` dict (from `publish_synthesis()`), fetches
        the current status, assignee, and priority for each created story/epic
        so the UI can show live Jira state without the user leaving the app.

        Returns a list of status records:
            [{key, summary, status, assignee, priority, url}, ...]
        """
        self._require_live_credentials()
        created = publish_result.get("created") or []
        keys = [c["key"] for c in created if c.get("key") and c.get("level") in ("epic", "story")]
        if not keys:
            return []

        try:
            import requests
        except ImportError as e:
            raise ToolError("'requests' required for Jira sync") from e

        # Batch fetch via JQL — much faster than one call per issue.
        jql = f'key in ({",".join(keys)})'
        url = f"{self._base_url}/rest/api/3/search/jql"
        resp = requests.get(
            url,
            params={"jql": jql, "fields": "summary,status,assignee,priority", "maxResults": 200},
            auth=(self._email, self._api_token),
            headers={"Accept": "application/json"},
            timeout=20,
        )
        if resp.status_code >= 400:
            raise ToolError(f"Jira sync failed ({resp.status_code}): {resp.text[:200]}")

        statuses = []
        for issue in resp.json().get("issues") or []:
            fields = issue.get("fields") or {}
            statuses.append({
                "key":      issue.get("key", ""),
                "summary":  fields.get("summary", ""),
                "status":   (fields.get("status") or {}).get("name", "Unknown"),
                "assignee": (fields.get("assignee") or {}).get("displayName", "Unassigned"),
                "priority": (fields.get("priority") or {}).get("name", ""),
                "url":      f"{self._base_url}/browse/{issue.get('key', '')}",
            })
        return statuses

    # ----------------------------------------------------- mock

    def _load_fixture(self) -> list[dict]:
        if not self._fixture_path.exists():
            logger.warning("JIRA fixture not found at %s; returning empty list", self._fixture_path)
            return []
        try:
            data = json.loads(self._fixture_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ToolError(f"JIRA fixture is not valid JSON: {e}")
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            data = data["items"]
        if not isinstance(data, list):
            raise ToolError("JIRA fixture must be a list of tickets")
        return data

    # ----------------------------------------------------- live

    def _require_live_credentials(self) -> None:
        if not self._base_url or not self._email or not self._api_token:
            raise ToolError(
                "Jira live mode requires JIRA_BASE_URL, JIRA_EMAIL and "
                "JIRA_API_TOKEN to be set."
            )

    def _load_live(self) -> list[dict]:
        """Pull every non-done issue in the configured project, paginated."""
        self._require_live_credentials()
        # Sensible default: every issue in the project. Caller can pass full
        # JQL via search() to narrow further.
        if self._project_key:
            jql = f'project = "{self._project_key}" ORDER BY created DESC'
        else:
            jql = "ORDER BY created DESC"
        return self._jql_search(jql)

    def _search_live(self, query: str) -> list[dict]:
        """Live JQL search. Wraps plain strings into a text-search clause."""
        self._require_live_credentials()
        q = query.strip()
        looks_like_jql = any(
            tok in q.upper() for tok in (" AND ", " OR ", " = ", " ~ ", "ORDER BY", "PROJECT ")
        )
        if looks_like_jql:
            jql = q
        elif self._project_key:
            # `text ~` is Jira's full-text search across summary + description.
            escaped = q.replace('"', '\\"')
            jql = f'project = "{self._project_key}" AND text ~ "{escaped}"'
        else:
            escaped = q.replace('"', '\\"')
            jql = f'text ~ "{escaped}"'
        return self._jql_search(jql)

    def _jql_search(self, jql: str) -> list[dict]:
        """Paginated JQL search using the v3 enhanced /search/jql endpoint.

        Returns a normalised list capped at `self._max_results`. The Gap
        Detector only needs a representative sample, so the cap keeps the
        first run cheap on large backlogs.
        """
        try:
            import requests
        except ImportError as e:  # pragma: no cover
            raise ToolError("'requests' package is required for live mode") from e

        url = f"{self._base_url}/rest/api/3/search/jql"
        # Field allowlist — Jira returns the whole world by default; we only
        # need a few fields per issue, and trimming them avoids cost surprises.
        fields = ["summary", "description", "status", "labels", "priority",
                  "issuetype", "components", "created", "updated"]

        all_issues: list[dict] = []
        next_token: str | None = None

        while True:
            params: dict[str, object] = {
                "jql": jql,
                "fields": ",".join(fields),
                "maxResults": self._page_size,
            }
            if next_token:
                params["nextPageToken"] = next_token

            resp = requests.get(
                url,
                params=params,
                auth=(self._email, self._api_token),
                headers={"Accept": "application/json"},
                timeout=30,
            )
            if resp.status_code in (401, 403):
                raise ToolError(
                    f"Jira auth failed ({resp.status_code}). "
                    "Check JIRA_EMAIL and JIRA_API_TOKEN."
                )
            if resp.status_code == 400:
                raise ToolError(f"Jira rejected JQL: {resp.text[:300]}")
            if resp.status_code >= 400:
                raise ToolError(
                    f"Jira /search/jql returned {resp.status_code}: {resp.text[:300]}"
                )

            data = resp.json()
            issues = data.get("issues", []) or []
            all_issues.extend(_normalise_issue(i) for i in issues)
            if self._max_results > 0 and len(all_issues) >= self._max_results:
                all_issues = all_issues[: self._max_results]
                logger.info("Jira search hit max_results=%d cap; truncating.", self._max_results)
                break

            # v3 /search/jql uses a cursor (nextPageToken) — present iff more.
            next_token = data.get("nextPageToken")
            if not next_token or not issues:
                break

        logger.info("Jira live fetch returned %d issue(s)", len(all_issues))
        return all_issues


# ----------------------------------------------------- write helpers

def _safe_label(value: str) -> str:
    """Jira labels can't contain spaces. Normalise to a hyphenated token."""
    return "-".join(str(value).split())[:255]


def _adf_text(text: str) -> dict:
    return {"type": "text", "text": str(text)}


def _adf_paragraph(text: str) -> dict:
    return {"type": "paragraph", "content": [_adf_text(text)] if text else []}


def _adf_heading(text: str, level: int = 3) -> dict:
    return {"type": "heading", "attrs": {"level": level}, "content": [_adf_text(text)]}


def _adf_bullets(items: list[str]) -> dict:
    return {
        "type": "bulletList",
        "content": [
            {"type": "listItem", "content": [_adf_paragraph(str(it))]}
            for it in items if str(it).strip()
        ] or [{"type": "listItem", "content": [_adf_paragraph("—")]}],
    }


def _text_adf(text: str) -> dict:
    """Minimal ADF doc from plain text; one paragraph per non-empty line."""
    paras = [_adf_paragraph(line.strip()) for line in (text or "").split("\n") if line.strip()]
    return {"version": 1, "type": "doc", "content": paras or [_adf_paragraph("")]}


def _story_adf(story: dict) -> dict:
    """Render a full story (user story, AC, priority, conflicts, tasks, tags)
    into an ADF document for the Jira issue description. Tasks are always
    listed here so they survive even when sub-task creation isn't permitted."""
    content: list[dict] = []

    if story.get("description"):
        content.append(_adf_paragraph(story["description"]))
    if story.get("user_story"):
        content.append(_adf_paragraph(story["user_story"]))

    ac = story.get("acceptance_criteria") or []
    if ac:
        content.append(_adf_heading("Acceptance criteria"))
        content.append(_adf_bullets(ac))

    pr = story.get("priority")
    if pr:
        rationale = story.get("priority_rationale") or ""
        content.append(_adf_paragraph(f"Priority: {pr}{(' — ' + rationale) if rationale else ''}"))

    conflicts = story.get("potential_constraint_conflicts") or []
    if conflicts:
        content.append(_adf_paragraph("⚠ Potential constraint conflicts: " + ", ".join(map(str, conflicts))))

    tasks = story.get("tasks") or []
    if tasks:
        content.append(_adf_heading("Tasks"))
        content.append(_adf_bullets([
            f"{t.get('title', 'Task')}" + (f"  [{t.get('type')}]" if t.get("type") else "")
            for t in tasks
        ]))

    meta_bits = []
    if story.get("source_topic_id"):
        meta_bits.append(f"source topic {story['source_topic_id']}")
    if story.get("tags"):
        meta_bits.append("tags: " + ", ".join(story["tags"]))
    meta_bits.append("drafted by Backlog Synthesizer (multi-agent)")
    content.append(_adf_paragraph(" · ".join(meta_bits)))

    return {"version": 1, "type": "doc", "content": content or [_adf_paragraph("")]}


# ----------------------------------------------------- adapter

def _normalise_issue(issue: dict) -> dict:
    """Map a Jira REST issue → the internal ticket dict shape.

    Output fields (matching the fixture):
        id, title, summary, description, status, labels, priority, raw

    `summary` is duplicated to `title` because some downstream callers
    use one or the other; keeping both is cheap and avoids surprises.
    """
    fields = issue.get("fields") or {}
    summary = fields.get("summary") or ""
    description = _adf_to_text(fields.get("description"))
    status = (fields.get("status") or {}).get("name", "")
    priority = (fields.get("priority") or {}).get("name", "")
    labels = fields.get("labels") or []
    return {
        "id": issue.get("key", ""),
        "title": summary,
        "summary": summary,
        "description": description,
        "status": status,
        "priority": priority,
        "labels": labels,
        "raw": issue,
    }


def _adf_to_text(adf) -> str:
    """Best-effort flatten of Atlassian Document Format → plain text.

    The Gap Detector reads description as a string for embedding /
    similarity. ADF is a nested JSON structure of typed nodes; we walk it
    depth-first and concatenate every text leaf. Formatting is lost — fine
    for downstream similarity work, not for re-rendering.
    """
    if not adf:
        return ""
    if isinstance(adf, str):
        return adf

    out: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text" and isinstance(node.get("text"), str):
                out.append(node["text"])
            for child in node.get("content", []) or []:
                walk(child)
            if node.get("type") in ("paragraph", "heading", "listItem"):
                out.append("\n")
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(adf)
    text = "".join(out)
    # Collapse extra blank lines for cleanliness
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()
