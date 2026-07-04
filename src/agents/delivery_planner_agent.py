"""Delivery Planner Agent — groups stories into epics and breaks them into tasks.

Reads from memory:
  - `stories` (from Story Writer)

Writes to memory:
  - `epics` — list of:
    {
        id, title, description,
        stories: [
            { ...story fields..., tasks: [{id, title, type}, ...] }
        ]
    }

Tools used: `claude_tool` only.
"""

from __future__ import annotations

import json

from agents.base import Agent, AgentError
from memory.audit_log import AuditLog
from memory.store import MemoryStore
from tools.base import Tool, ToolError


class DeliveryPlannerAgent(Agent):
    name = "epic_decomposer"

    def __init__(
        self,
        claude: Tool | None = None,
        memory: MemoryStore | None = None,
        audit: AuditLog | None = None,
        *,
        tool: Tool | None = None,
    ) -> None:
        super().__init__(memory=memory, audit=audit)
        self.claude = tool or claude
        if self.claude is None:
            raise AgentError("DeliveryPlannerAgent requires an LLM tool (claude= or tool=).")
        self._prompt_template = self.load_prompt("epic_decomposer_prompt.md")

    def run(self) -> None:
        stories = self.memory.get("stories", [])
        if not stories:
            self.emit("skipped", reasoning="No stories in memory; nothing to decompose.")
            return

        self.emit("started", payload={"story_count": len(stories)})

        prompt = self._prompt_template.replace("{{STORIES_JSON}}", json.dumps(stories, indent=2))
        try:
            parsed, usage = self.claude.call_for_json(prompt, max_tokens=8192)
        except ToolError as e:
            raise AgentError(f"Epic Decomposer LLM call failed: {e}") from e

        epics = parsed.get("epics", [])
        for i, epic in enumerate(epics):
            epic.setdefault("id", f"EP-{i + 1:02d}")
            for j, story in enumerate(epic.get("stories", [])):
                # Ensure stories carry an id even if the model dropped it
                story.setdefault("id", f"{epic['id']}-ST-{j + 1:02d}")
                # Tasks should already exist; just assign ids if missing
                for k, task in enumerate(story.get("tasks", [])):
                    task.setdefault("id", f"{story['id']}-TK-{k + 1:02d}")

        self.memory.put("epics", epics)

        total_stories = sum(len(e.get("stories", [])) for e in epics)
        total_tasks = sum(
            len(s.get("tasks", []))
            for e in epics
            for s in e.get("stories", [])
        )

        import json as _json
        self.audit.record_tool_call(
            agent=self.name,
            tool=getattr(self.claude, "name", "claude"),
            request={"prompt_chars": len(prompt), "max_tokens": 8000},
            response_excerpt=str(parsed)[:300],
            tokens_used=(usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0),
            usage=usage,
            prompt=prompt,
            response_text=_json.dumps(parsed, indent=2),
        )
        self.emit(
            "completed",
            payload={"epic_count": len(epics), "story_count": total_stories, "task_count": total_tasks},
            reasoning=f"Grouped {total_stories} stories into {len(epics)} epics with {total_tasks} tasks total.",
        )
