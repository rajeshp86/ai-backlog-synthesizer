"""Story Generation Agent — drafts user stories from topics, aware of constraints.

Reads from memory:
  - `topics` (from Parser)
  - `constraints` (from Constraint Extractor) — used as context so the model
    avoids drafting stories that violate them

Writes to memory:
  - `stories` — list of full story dicts:
    {
        id, title, description, user_story, acceptance_criteria, priority,
        priority_rationale, tags, source_topic_id, conflicts_with_constraints
    }


"""

from __future__ import annotations

import json

from agents.base import Agent, AgentError
from memory.audit_log import AuditLog
from memory.store import MemoryStore
from tools.base import Tool, ToolError


class StoryGenerationAgent(Agent):
    name = "story_writer"

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
            raise AgentError("StoryGenerationAgent requires an LLM tool (claude= or tool=).")
        self._prompt_template = self.load_prompt("story_writer_prompt.md")

    def run(self) -> None:
        topics = self.memory.get("topics", [])
        constraints = self.memory.get("constraints", [])

        if not topics:
            self.emit("skipped", reasoning="No topics in memory; nothing to write stories for.")
            return

        self.emit("started", payload={"topic_count": len(topics), "constraint_count": len(constraints)})

        prompt = (
            self._prompt_template
            .replace("{{TOPICS_JSON}}", json.dumps(topics, indent=2))
            .replace("{{CONSTRAINTS_JSON}}", json.dumps(constraints, indent=2))
        )
        try:
            parsed, usage = self.claude.call_for_json(prompt, max_tokens=8000)
        except ToolError as e:
            raise AgentError(f"Story Writer LLM call failed: {e}") from e

        stories = parsed.get("stories", [])
        # Build a lookup from topic id → topic so we can attach the source
        # quote as evidence on every story.
        topics_by_id = {t.get("id"): t for t in topics if isinstance(t, dict)}
        repaired: list[dict] = []
        for i, s in enumerate(stories):
            s.setdefault("id", f"ST-{i + 1:02d}")
            _sid_before = (s.get("source_topic_id") or "").strip()
            self._repair_source_topic_id(s, topics, topics_by_id)
            _sid_after = (s.get("source_topic_id") or "").strip()
            if _sid_before != _sid_after:
                repaired.append({"story_id": s.get("id"), "from": _sid_before, "to": _sid_after})
            self._attach_evidence(s, topics_by_id)

        if repaired:
            try:
                from telemetry import child_span as _cs
                with _cs("story.repair", **{"repair.count": len(repaired)}):
                    pass  # span records the event; detail goes to audit log below
            except Exception:  # noqa: BLE001
                pass
            self.emit(
                "story_repair",
                payload={"repaired_count": len(repaired), "repairs": repaired},
                reasoning=(
                    f"{len(repaired)} story(ies) had invalid source_topic_id values "
                    f"(e.g. '...' or unknown IDs). Auto-repaired by matching story text "
                    f"against topic summaries. Check these stories if grounding accuracy is critical."
                ),
            )

        self.memory.put("stories", stories)

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
            payload={"story_count": len(stories)},
            reasoning=f"Drafted {len(stories)} stories across {len(topics)} topics.",
        )

    @staticmethod
    def _repair_source_topic_id(
        story: dict,
        topics: list[dict],
        topics_by_id: dict,
    ) -> None:
        """Fix invalid source_topic_id values produced by weaker LLMs.

        Weaker models sometimes output "..." or an id that doesn't match any
        parsed topic. This method replaces the bad value with the best-matching
        topic found by word-overlap between the story text and each topic's
        theme/summary/quote. Falls back to the first unmatched topic.
        """
        _PLACEHOLDERS = {"...", "null", "", "none", "n/a", "tbd"}
        sid = (story.get("source_topic_id") or "").strip()

        # Already valid — nothing to do.
        if sid and sid not in _PLACEHOLDERS and sid in topics_by_id:
            return

        if not topics:
            return

        # Score each topic by word overlap with the story text.
        story_text = " ".join(filter(None, [
            story.get("title", ""),
            story.get("description", ""),
            story.get("user_story", ""),
        ])).lower()
        story_words = set(story_text.split())

        best_topic_id: str | None = None
        best_score = -1
        for t in topics:
            if not isinstance(t, dict):
                continue
            topic_text = " ".join(filter(None, [
                t.get("theme", ""),
                t.get("summary", ""),
                t.get("raw_quote", ""),
            ])).lower()
            score = len(story_words & set(topic_text.split()))
            if score > best_score:
                best_score = score
                best_topic_id = t.get("id")

        if best_topic_id:
            story["source_topic_id"] = best_topic_id

    # Placeholder values the LLM sometimes emits instead of real content.
    _PLACEHOLDERS: frozenset[str] = frozenset({
        "...", "…", "null", "none", "n/a", "tbd", "unknown", "—", "-", ""
    })

    @staticmethod
    def _attach_evidence(story: dict, topics_by_id: dict) -> None:
        """Add an `evidence` block to a story citing the source topic.

        Evidence is the parser-extracted raw_quote plus speaker / sentiment.
        Placeholder values ("...", "null", etc.) produced by weaker LLMs are
        treated as missing — the evidence block is left empty so the UI shows
        nothing rather than displaying a meaningless "..." quote.
        """
        sid = story.get("source_topic_id")
        topic = topics_by_id.get(sid) if sid else None
        if not topic:
            story.setdefault("evidence", [])
            return

        raw_quote = (topic.get("raw_quote") or "").strip()
        speaker   = (topic.get("speaker")   or "").strip()
        sentiment = (topic.get("sentiment") or "").strip()

        # Strip placeholder values so they never reach the UI.
        _ph = StoryGenerationAgent._PLACEHOLDERS
        if raw_quote.lower() in _ph:
            raw_quote = ""
        if speaker.lower() in _ph:
            speaker = ""
        if sentiment.lower() in _ph:
            sentiment = ""

        # Only attach evidence when there is a real quote to show.
        if not raw_quote:
            story.setdefault("evidence", [])
            return

        story["evidence"] = [{
            "topic_id":  sid,
            "theme":     topic.get("theme", ""),
            "raw_quote": raw_quote,
            "speaker":   speaker,
            "sentiment": sentiment,
        }]
