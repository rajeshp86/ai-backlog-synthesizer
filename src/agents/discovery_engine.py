"""Discovery Engine — extracts distinct topics from raw transcript text.

A topic is a coherent ask, complaint, or observation from the source. The
Story Writer downstream uses topics as anchors so each story traces back
to a specific source quote.

Writes to memory:
  - `topics` — list of {id, raw_quote, theme, summary} dicts
  - `summary` — short overall summary of the transcript

Tools used: `claude_tool` only.


"""

from __future__ import annotations

from agents.base import Agent, AgentError
from memory.audit_log import AuditLog
from memory.store import MemoryStore
from tools.base import Tool, ToolError


class DiscoveryEngine(Agent):
    name = "parser"

    def __init__(
        self,
        claude: Tool | None = None,
        memory: MemoryStore | None = None,
        audit: AuditLog | None = None,
        *,
        tool: Tool | None = None,
    ) -> None:
        # `claude=` kept as the primary kwarg for back-compat with tests and
        # earlier callers; the agent doesn't actually care which provider
        # is behind the tool, only that it exposes `call_for_json(...)`.
        # `tool=` is the new alias the orchestrator can use to make the
        # provider-agnostic intent obvious at call sites.
        super().__init__(memory=memory, audit=audit)
        self.claude = tool or claude
        if self.claude is None:
            raise AgentError("DiscoveryEngine requires an LLM tool (claude= or tool=).")
        self._prompt_template = self.load_prompt("parser_prompt.md")

    def run(
        self,
        transcript_text: str,
        vision_attachments: list | None = None,
    ) -> None:
        self.emit(
            "started",
            payload={
                "input_chars": len(transcript_text),
                "vision_attachment_count": len(vision_attachments or []),
            },
        )

        # When images are present, hint in the prompt so the model knows to
        # treat them as primary source material (whiteboard photos, screen
        # captures) rather than decoration. Image bytes flow through the
        # tool's `images=` kwarg, not through `{{TRANSCRIPT}}`.
        if vision_attachments:
            visual_hint = (
                "\n\n[Visual attachments are included as image content "
                "blocks. Treat them as first-class source material alongside "
                "the text above. Whiteboard photos, screenshots, and "
                "diagrams may contain topics not mentioned in the text.]"
            )
            transcript_text = (transcript_text or "(no text transcript — see attached images)") + visual_hint

        prompt = self._prompt_template.replace("{{TRANSCRIPT}}", transcript_text)
        try:
            # Only the Claude tool exposes the `images=` kwarg today; the
            # Gemini wrapper doesn't. Forward selectively so a stub or
            # different provider doesn't blow up on an unexpected kwarg.
            call = getattr(self.claude, "call_for_json")
            if vision_attachments and "images" in call.__code__.co_varnames:
                parsed, usage = call(prompt, max_tokens=4000, images=vision_attachments)
            else:
                parsed, usage = call(prompt, max_tokens=4000)
        except ToolError as e:
            raise AgentError(f"Parser LLM call failed: {e}") from e

        topics = parsed.get("topics", [])
        summary = parsed.get("summary", "")

        # Assign deterministic IDs
        for i, t in enumerate(topics):
            t["id"] = f"T-{i + 1:02d}"

        self.memory.put("topics", topics)
        if summary:
            self.memory.put("summary", summary)

        import json as _json
        self.audit.record_tool_call(
            agent=self.name,
            tool=getattr(self.claude, "name", "claude"),
            request={"prompt_chars": len(prompt), "max_tokens": 4000},
            response_excerpt=str(parsed)[:300],
            tokens_used=(usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0),
            usage=usage,
            prompt=prompt,
            response_text=_json.dumps(parsed, indent=2),
        )
        self.emit(
            "completed",
            payload={"topic_count": len(topics)},
            reasoning=f"Extracted {len(topics)} distinct topics from the transcript.",
        )
