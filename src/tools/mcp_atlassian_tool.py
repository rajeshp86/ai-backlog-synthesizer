"""Atlassian MCP tool adapters — Jira and Confluence via mcp-atlassian.

When ATLASSIAN_MCP_ENABLED=1 is set, these classes launch the `mcp-atlassian`
Python server (pip install mcp-atlassian) via stdio and call its tools instead
of making direct REST API calls. When the env var is unset (or the server is
unavailable) they fall back to the existing JiraTool / ConfluenceTool
implementations transparently.

Setup (one-time):
    pip install mcp-atlassian          # Python 3.10+ required
    # Then set env vars:
    ATLASSIAN_MCP_ENABLED=1
    JIRA_BASE_URL=https://yourcompany.atlassian.net
    JIRA_EMAIL=you@company.com
    JIRA_API_TOKEN=<token from id.atlassian.com>
    JIRA_PROJECT_KEY=MYPROJ

Why mcp-atlassian over direct REST:
    - Handles ADF ↔ markdown conversion automatically
    - Pagination, retries, field normalisation managed by the server
    - Decouples this app from Atlassian REST schema changes
    - Audit log records which MCP tool was called
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from logger_setup import get_logger
from tools.base import ToolError
from tools.jira_tool import JiraTool
from tools.confluence_tool import ConfluenceTool

logger = get_logger(__name__)

_MCP_ENABLED = os.environ.get("ATLASSIAN_MCP_ENABLED", "").strip() == "1"


def _find_mcp_atlassian_binary() -> str:
    """Find the mcp-atlassian executable in the current or venv Python path."""
    # Try the same Python env's bin/ first.
    bin_dir = Path(sys.executable).parent
    for name in ("mcp-atlassian", "mcp_atlassian"):
        candidate = bin_dir / name
        if candidate.exists():
            return str(candidate)
    # Fall back to PATH
    import shutil
    found = shutil.which("mcp-atlassian")
    if found:
        return found
    raise ToolError(
        "mcp-atlassian binary not found. Install it in the active Python env:\n"
        "  pip install mcp-atlassian\n"
        "Requires Python 3.10+"
    )


def _build_server_params():
    """Build StdioServerParameters for mcp-atlassian."""
    from mcp import StdioServerParameters

    binary = _find_mcp_atlassian_binary()
    jira_url   = os.environ.get("JIRA_BASE_URL", "")
    jira_user  = os.environ.get("JIRA_EMAIL", "")
    jira_token = os.environ.get("JIRA_API_TOKEN", "")
    proj_key   = os.environ.get("JIRA_PROJECT_KEY", "")

    args = [
        "--jira-url",      jira_url,
        "--jira-username", jira_user,
        "--jira-token",    jira_token,
        "--transport",     "stdio",
        "--read-only",     # safest default — remove if write tools needed
    ]
    if proj_key:
        args += ["--jira-projects-filter", proj_key]

    # Also wire Confluence using the same credentials
    confluence_url = os.environ.get("CONFLUENCE_BASE_URL", jira_url)
    if confluence_url:
        args += [
            "--confluence-url",      confluence_url + "/wiki",
            "--confluence-username", jira_user,
            "--confluence-token",    jira_token,
        ]

    return StdioServerParameters(command=binary, args=args)


async def _call_mcp_tool_async(tool_name: str, arguments: dict) -> Any:
    """Spawn mcp-atlassian server via stdio, call one tool, return result."""
    try:
        from mcp.client.stdio import stdio_client
        from mcp import ClientSession
    except ImportError as e:
        raise ToolError("The 'mcp' package is not installed: pip install mcp") from e

    server_params = _build_server_params()
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            if result and hasattr(result, "content"):
                texts = [b.text for b in result.content if hasattr(b, "text")]
                return "\n".join(texts)
            return result


def _call_mcp_tool(tool_name: str, arguments: dict) -> Any:
    return asyncio.run(_call_mcp_tool_async(tool_name, arguments))


def _list_available_tools() -> list[str]:
    """Return the tool names the running mcp-atlassian server exposes."""
    async def _list():
        try:
            from mcp.client.stdio import stdio_client
            from mcp import ClientSession
            server_params = _build_server_params()
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    resp = await session.list_tools()
                    return [t.name for t in resp.tools]
        except Exception:  # noqa: BLE001
            return []
    return asyncio.run(_list())


# ──────────────────────────────────────────────────────── Jira MCP

class MCPJiraTool(JiraTool):
    """JiraTool backed by mcp-atlassian when ATLASSIAN_MCP_ENABLED=1.

    Falls back to parent JiraTool (direct REST) on any failure.

    MCP tools used (mcp-atlassian names):
        jira_search_issues   — JQL search
        jira_get_issue       — single issue fetch
        jira_create_issue    — create issue
    """

    name = "mcp_jira"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._use_mcp = _MCP_ENABLED
        if self._use_mcp:
            logger.info("MCPJiraTool: Atlassian MCP mode enabled (mcp-atlassian)")

    def list_all(self) -> list[dict]:
        if not self._use_mcp:
            return super().list_all()
        try:
            project = self._project_key or ""
            jql = f'project = "{project}" ORDER BY created DESC' if project else 'ORDER BY updated DESC'
            return self._mcp_search(jql)
        except Exception as e:  # noqa: BLE001
            logger.warning("MCPJiraTool list_all failed (%s) — falling back to REST", e)
            self._use_mcp = False
            return super().list_all()

    def search(self, query: str) -> list[dict]:
        if not self._use_mcp:
            return super().search(query)
        try:
            return self._mcp_search(query)
        except Exception as e:  # noqa: BLE001
            logger.warning("MCPJiraTool search failed (%s) — falling back to REST", e)
            self._use_mcp = False
            return super().search(query)

    def _mcp_search(self, jql: str) -> list[dict]:
        try:
            from telemetry import child_span as _cs
        except ImportError:
            import contextlib
            def _cs(*_a, **_kw): return contextlib.nullcontext()  # type: ignore[assignment]
        with _cs("tool.jira_search", **{"tool.transport": "atlassian_mcp", "tool.jql": jql[:120]}) as _span:
            raw = _call_mcp_tool("jira_search", {
                "jql": jql,
                "limit": min(self._max_results, 50),
                "fields": "summary,description,status,labels,priority,issuetype,created,updated",
            })
        # Parse outside span (span covers only the MCP call)
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return []
            issues = data if isinstance(data, list) else data.get("issues", [])
        elif isinstance(raw, list):
            issues = raw
        else:
            return []

        # mcp-atlassian returns a flat dict per issue (key, summary, description,
        # status.name…) — NOT the raw Jira REST `fields.*` shape. Normalise to
        # the same internal shape the Gap Detector expects.
        result = []
        for i in issues:
            if not isinstance(i, dict):
                continue
            if "fields" in i:
                # Raw Jira REST shape — use the existing normaliser
                from tools.jira_tool import _normalise_issue
                result.append(_normalise_issue(i))
            else:
                # mcp-atlassian flat shape
                result.append({
                    "id":          i.get("key") or i.get("id", ""),
                    "title":       i.get("summary", ""),
                    "summary":     i.get("summary", ""),
                    "description": i.get("description", "") or "",
                    "status":      (i.get("status") or {}).get("name", "") if isinstance(i.get("status"), dict) else str(i.get("status", "")),
                    "priority":    (i.get("priority") or {}).get("name", "") if isinstance(i.get("priority"), dict) else str(i.get("priority", "")),
                    "labels":      i.get("labels") or [],
                    "raw":         i,
                })
        return result

    def create_issue(
        self, *, summary: str, description_adf: dict,
        issue_type: str = "Task", labels: list[str] | None = None,
        parent_key: str | None = None, project_key: str | None = None,
    ) -> dict:
        if not self._use_mcp:
            return super().create_issue(
                summary=summary, description_adf=description_adf,
                issue_type=issue_type, labels=labels,
                parent_key=parent_key, project_key=project_key,
            )
        try:
            project = project_key or self._project_key
            args: dict[str, Any] = {
                "project_key": project,
                "summary": summary[:250],
                "issue_type": issue_type,
            }
            if labels:
                args["labels"] = labels
            if parent_key:
                args["parent_key"] = parent_key
            raw = _call_mcp_tool("jira_create_issue", args)
            key = ""
            if isinstance(raw, str):
                import re
                m = re.search(r"([A-Z][A-Z0-9]+-\d+)", raw)
                if m:
                    key = m.group(1)
            base = self._base_url or os.environ.get("JIRA_BASE_URL", "")
            return {"key": key, "url": f"{base}/browse/{key}" if key else "",
                    "type": issue_type, "summary": summary}
        except Exception as e:  # noqa: BLE001
            logger.warning("MCPJiraTool create_issue failed (%s) — falling back to REST", e)
            self._use_mcp = False
            return super().create_issue(
                summary=summary, description_adf=description_adf,
                issue_type=issue_type, labels=labels,
                parent_key=parent_key, project_key=project_key,
            )


# ──────────────────────────────────────────────────────── Confluence MCP

class MCPConfluenceTool(ConfluenceTool):
    """ConfluenceTool backed by mcp-atlassian when ATLASSIAN_MCP_ENABLED=1.

    MCP tools used:
        confluence_get_page_content   — fetch page by ID
        confluence_search             — search pages by text
    """

    name = "mcp_confluence"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._use_mcp = _MCP_ENABLED
        if self._use_mcp:
            logger.info("MCPConfluenceTool: Atlassian MCP mode enabled (mcp-atlassian)")

    def get_page(self, page_id: str = "default") -> str:
        if not self._use_mcp or page_id == "default":
            return super().get_page(page_id)
        try:
            raw = _call_mcp_tool("confluence_get_page", {"page_id": page_id})
            if isinstance(raw, str) and raw.strip():
                logger.info("MCPConfluenceTool: fetched page %s via mcp-atlassian (%d chars)",
                            page_id, len(raw))
                return raw
        except Exception as e:  # noqa: BLE001
            logger.warning("MCPConfluenceTool get_page failed (%s) — falling back to REST", e)
        self._use_mcp = False
        return super().get_page(page_id)
