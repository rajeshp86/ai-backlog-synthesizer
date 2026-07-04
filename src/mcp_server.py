"""MCP server — exposes the Backlog Synthesizer pipeline as five FastMCP tools.

Run with:
    python src/mcp_server.py

or mount inside a larger FastAPI app via ``mcp.http_app()``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

RUNS_DIR = ROOT / "logs" / "runs"

try:
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("backlog-synthesizer")
except Exception:  # noqa: BLE001 — mcp may not be installed in all envs
    class _FakeMCP:  # type: ignore[no-redef]
        class _tm:
            _tools: dict = {}
            async def get_tools(self):
                return {}
        _tool_manager = _tm()
        def tool(self, fn=None, **_kw):
            def decorator(f):
                self._tool_manager._tools[f.__name__] = type("T", (), {"fn": f})()
                return f
            return decorator(fn) if fn else decorator
    mcp = _FakeMCP()  # type: ignore[assignment]


@mcp.tool()
def synthesize_backlog(
    transcript: str,
    constraints: str = "",
    existing_tickets_json: str = "[]",
) -> dict[str, Any]:
    """Run the full multi-agent backlog synthesis pipeline.

    Args:
        transcript: Raw meeting notes or feature description.
        constraints: Architecture constraints wiki text (optional).
        existing_tickets_json: JSON array of existing Jira tickets (optional).

    Returns:
        Synthesis result dict with keys: epics, duplicates, gaps, conflicts,
        token_usage, cost_usd.  On error returns {"error": "<message>"}.
    """
    if not (transcript or "").strip():
        return {"error": "transcript is required and must not be empty"}

    try:
        existing_tickets = json.loads(existing_tickets_json) if existing_tickets_json else []
    except json.JSONDecodeError as exc:
        return {"error": f"existing_tickets_json is not valid JSON: {exc}"}

    try:
        from pipeline import Orchestrator
        orch = Orchestrator()
        result = orch.run(
            transcript_text=transcript,
            constraint_text=constraints,
            existing_tickets=existing_tickets,
        )
        return {
            "epics":       result.get("epics") or [],
            "duplicates":  result.get("duplicates") or [],
            "gaps":        result.get("gaps") or [],
            "conflicts":   result.get("conflicts") or [],
            "token_usage": result.get("token_usage") or {},
            "cost_usd":    result.get("cost_usd") or 0.0,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@mcp.tool()
def preview_prompts(stage: str = "") -> dict[str, Any]:
    """Return the rendered system prompts for one or all pipeline stages.

    Args:
        stage: One of parser, constraint, story_writer, epic_decomposer,
               gap_detector.  Omit to get all stages.

    Returns:
        Dict mapping stage_name -> prompt_text.  On error returns {"error": ...}.
    """
    prompts_dir = ROOT / "prompts"
    stage_files = {
        "parser":          "parser_prompt.md",
        "constraint":      "constraint_prompt.md",
        "story_writer":    "story_writer_prompt.md",
        "epic_decomposer": "epic_decomposer_prompt.md",
        "gap_detector":    "gap_detector_prompt.md",
    }
    if stage:
        if stage not in stage_files:
            return {"error": f"Unknown stage '{stage}'. Valid: {list(stage_files)}"}
        path = prompts_dir / stage_files[stage]
        return {stage: path.read_text(encoding="utf-8") if path.exists() else "(not found)"}
    return {
        name: (prompts_dir / fname).read_text(encoding="utf-8")
        if (prompts_dir / fname).exists() else "(not found)"
        for name, fname in stage_files.items()
    }


@mcp.tool()
def get_run_history(limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent synthesis run summaries.

    Args:
        limit: Maximum number of runs to return (default 20).

    Returns:
        List of run summary dicts sorted newest-first.
    """
    if not RUNS_DIR.exists():
        return []
    runs: list[dict] = []
    for user_dir in RUNS_DIR.iterdir():
        if not user_dir.is_dir():
            continue
        for p in user_dir.glob("*.json"):
            try:
                runs.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
    runs.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return runs[:limit]


@mcp.tool()
def get_run_result(run_id: str) -> dict[str, Any]:
    """Load the full synthesis output JSON for a specific run.

    Args:
        run_id: The run_id field from a get_run_history entry.

    Returns:
        The synthesis output dict, or {"error": "not found"}.
    """
    if not RUNS_DIR.exists():
        return {"error": "no runs directory found"}
    for user_dir in RUNS_DIR.iterdir():
        if not user_dir.is_dir():
            continue
        for p in user_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("run_id") == run_id:
                    outputs = data.get("outputs") or {}
                    json_path = outputs.get("synthesis_json")
                    if json_path and Path(json_path).exists():
                        return json.loads(Path(json_path).read_text(encoding="utf-8"))
                    return data
            except (OSError, json.JSONDecodeError):
                continue
    return {"error": f"run '{run_id}' not found"}


@mcp.tool()
def push_to_jira(
    run_id: str,
    project_key: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Push synthesised epics/stories from a completed run to Jira.

    Args:
        run_id: The run_id field from get_run_history.
        project_key: Jira project key (e.g. "NS").
        dry_run: When True (default) validates and returns what would be pushed
                 without creating tickets.

    Returns:
        {"pushed": N, "skipped": N, "dry_run": bool} or {"error": ...}.
    """
    result = get_run_result(run_id)
    if "error" in result:
        return result
    epics = result.get("epics") or []
    stories = [s for e in epics for s in (e.get("stories") or [])]
    if dry_run:
        return {"pushed": 0, "skipped": len(stories), "dry_run": True,
                "would_push": [s.get("title", "") for s in stories]}
    # Live push path — requires JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN
    try:
        from tools.jira_tool import JiraTool
        jira = JiraTool(mode="live")
        pushed = 0
        for story in stories:
            jira.create_issue(
                project_key=project_key,
                summary=story.get("title", "Untitled"),
                description=story.get("description", ""),
                issue_type="Story",
            )
            pushed += 1
        return {"pushed": pushed, "skipped": 0, "dry_run": False}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


if __name__ == "__main__":
    mcp.run()
