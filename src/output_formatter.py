"""Output formatting for the multi-agent synthesis.

Renders the result of an orchestrator run two ways:
  - synthesis.json  → machine-readable, full data
  - synthesis.md    → human-readable, hierarchical (epics → stories → tasks)

The full result dict has this shape:

    {
        "source_files": {...},
        "topics": [...],
        "constraints": [...],
        "epics": [
            {
                "id": "EP-01",
                "title": "...",
                "description": "...",
                "stories": [
                    {
                        "id": "ST-01",
                        "title": "...",
                        "user_story": "As a ...",
                        "description": "...",
                        "acceptance_criteria": [...],
                        "priority": "High",
                        "tags": ["telemetry", "offline-mode"],
                        "tasks": [
                            {"id": "TK-01", "title": "..."},
                            ...
                        ]
                    }
                ]
            }
        ],
        "gaps": [...],
        "conflicts": [...],
        "duplicates": [...]
    }
"""

import json
from pathlib import Path
from typing import Any


def write_outputs(result: dict[str, Any], out_dir: Path, source_label: str = "") -> tuple[Path, Path]:
    """Write synthesis.json + synthesis.md to out_dir. Returns the two paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "synthesis.json"
    md_path = out_dir / "synthesis.md"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(result, source_label), encoding="utf-8")
    return json_path, md_path


def _render_markdown(result: dict[str, Any], source_label: str = "") -> str:
    lines: list[str] = []
    lines.append("# Backlog Synthesis")
    if source_label:
        lines.append("")
        lines.append(f"*Synthesized from: {source_label}*")
    lines.append("")

    # --- Summary ---
    summary = result.get("summary", "").strip()
    if summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(summary)
        lines.append("")

    # --- Epics → Stories → Tasks ---
    epics = result.get("epics", [])
    if epics:
        lines.append(f"## Epics ({len(epics)})")
        lines.append("")
        for i, epic in enumerate(epics, start=1):
            lines.extend(_render_epic(i, epic))

    # --- Gaps ---
    gaps = result.get("gaps", [])
    if gaps:
        lines.append("## 🔍 Gaps detected")
        lines.append("")
        lines.append("Capabilities implied by the source material that are not represented in the existing backlog.")
        lines.append("")
        for g in gaps:
            lines.append(f"- **{g.get('title', '?')}** — {g.get('description', '')}")
            if g.get("evidence"):
                lines.append(f"  - *Evidence:* {g['evidence']}")
        lines.append("")

    # --- Conflicts ---
    conflicts = result.get("conflicts", [])
    if conflicts:
        lines.append("## ⚠️ Conflicts")
        lines.append("")
        lines.append("New stories that contradict architectural constraints or in-flight work.")
        lines.append("")
        for c in conflicts:
            lines.append(
                f"- **Story {c.get('story_id', '?')}** conflicts with "
                f"**{c.get('with', '?')}** (severity: {c.get('severity', 'unknown')})"
            )
            if c.get("reason"):
                lines.append(f"  - {c['reason']}")
        lines.append("")

    # --- Duplicates ---
    dupes = result.get("duplicates", [])
    if dupes:
        lines.append("## ♻️ Possible duplicates")
        lines.append("")
        lines.append("New stories that overlap with existing JIRA / GitHub tickets.")
        lines.append("")
        for d in dupes:
            lines.append(
                f"- **Story {d.get('story_id', '?')}** overlaps with "
                f"**{d.get('existing_id', '?')}** "
                f"(confidence: {d.get('confidence', 'unknown')})"
            )
            if d.get("reason"):
                lines.append(f"  - {d['reason']}")
        lines.append("")

    return "\n".join(lines)


def _render_epic(i: int, epic: dict) -> list[str]:
    out: list[str] = []
    out.append(f"### Epic {i}: {epic.get('title', 'Untitled')}")
    out.append("")
    if epic.get("description"):
        out.append(epic["description"])
        out.append("")

    stories = epic.get("stories", [])
    for j, story in enumerate(stories, start=1):
        out.extend(_render_story(i, j, story))
    out.append("---")
    out.append("")
    return out


def _render_story(epic_i: int, story_j: int, story: dict) -> list[str]:
    out: list[str] = []
    title = story.get("title", "Untitled story")
    priority = story.get("priority", "Unspecified")
    tags = story.get("tags", [])
    tag_str = " ".join(f"`{t}`" for t in tags) if tags else "`untagged`"

    out.append(f"#### {epic_i}.{story_j} {title}")
    out.append("")
    out.append(f"**Priority:** {priority}   |   **Tags:** {tag_str}")
    out.append("")

    description = story.get("description", "").strip()
    if description:
        out.append(f"> {description}")
        out.append("")

    user_story = story.get("user_story", "").strip()
    if user_story:
        out.append("**User story**")
        out.append(f"- {user_story}")
        out.append("")

    ac = story.get("acceptance_criteria", [])
    if ac:
        out.append("**Acceptance criteria**")
        for crit in ac:
            out.append(f"- {crit}")
        out.append("")

    tasks = story.get("tasks", [])
    if tasks:
        out.append("**Tasks**")
        for tk in tasks:
            out.append(f"- {tk.get('id', '?')}: {tk.get('title', '?')}")
        out.append("")

    return out
