"""Insight Scanner Agent — finds duplicates, conflicts, and gaps.

Reads from memory:
  - `stories` (from Story Writer)
  - `constraints` (from Constraint Extractor)
  - `existing_tickets` (loaded by orchestrator from --backlog)

Writes to memory:
  - `duplicates` — list of {story_id, existing_id, confidence, reason, _similarity?}
  - `conflicts` — list of {story_id, with, severity, reason}
  - `gaps` — list of {id, title, description, related_ids, evidence}

Tools used:
  - LLM tool (`self.claude`) — judgment for conflicts + gaps
  - `jira_tool` / `github_tool` — search existing tickets (called via
    memory.search_similar)
  - `EmbeddingTool` — local sentence-transformers duplicate detection
    (no LLM call for the duplicate sub-step)

Duplicate detection:
  In normal operation (`use_embeddings_for_duplicates=True`, the default and
  the only mode the orchestrator uses) duplicates are found by local
  embedding similarity and the LLM prompt is scoped to conflicts + gaps only
  — the V2 gap_detector_prompt.md deliberately does not ask the model for
  duplicates. The `use_embeddings_for_duplicates=False` flag is a test/seam
  that instead reads a `duplicates` array from the LLM response; it relies on
  a duplicates-capable prompt or a mocked tool, and is not used in production.
"""

from __future__ import annotations

import json

from agents.base import Agent, AgentError
from memory.audit_log import AuditLog
from memory.store import MemoryStore
from tools.base import Tool, ToolError
from tools.embedding_tool import EmbeddingTool
from tools.jira_tool import JiraTool


TOP_K = 5
# Cosine-similarity threshold for the local embeddings-based duplicate
# detector. Lowered from 0.75 → 0.6 after observing that thematically
# clear matches (e.g. "Recall notification SMS reminder" vs "Notify owner
# when a recall is open") were scoring 0.62-0.70 on
# `all-MiniLM-L6-v2`. 0.75 was leaving real duplicates on the table.
# 0.6 trades a few extra LLM-rerank invocations for materially better
# recall — the LLM downstream still rejects false positives.
DEFAULT_DUPLICATE_THRESHOLD = 0.6


class InsightScannerAgent(Agent):
    name = "gap_detector"

    def __init__(
        self,
        claude: Tool | None = None,
        jira: JiraTool | None = None,
        memory: MemoryStore | None = None,
        audit: AuditLog | None = None,
        *,
        tool: Tool | None = None,
        use_embeddings_for_duplicates: bool = True,
        embedding_tool: EmbeddingTool | None = None,
        duplicate_threshold: float = DEFAULT_DUPLICATE_THRESHOLD,
    ) -> None:
        super().__init__(memory=memory, audit=audit)
        self.claude = tool or claude
        if self.claude is None:
            raise AgentError("InsightScannerAgent requires an LLM tool (claude= or tool=).")
        self.jira = jira
        self._prompt_template = self.load_prompt("gap_detector_prompt.md")
        self.use_embeddings_for_duplicates = use_embeddings_for_duplicates
        self.embedding_tool = embedding_tool
        self.duplicate_threshold = duplicate_threshold

    def run(self) -> None:
        stories = self.memory.get("stories", [])
        constraints = self.memory.get("constraints", [])
        existing_tickets = self.memory.get("existing_tickets", [])

        if not stories:
            self.emit("skipped", reasoning="No stories to compare.")
            return

        self.emit(
            "started",
            payload={
                "story_count": len(stories),
                "existing_ticket_count": len(existing_tickets),
                "constraint_count": len(constraints),
                "duplicate_mode": (
                    "embeddings" if self.use_embeddings_for_duplicates else "llm"
                ),
            },
        )

        # --- Duplicate detection (embeddings OR LLM via the unified prompt) ---
        duplicates_from_embeddings: list[dict] = []
        skip_dupes_in_llm = False
        if self.use_embeddings_for_duplicates and existing_tickets:
            try:
                tool = self.embedding_tool or EmbeddingTool()
                duplicates_from_embeddings = tool.find_duplicates(
                    stories, existing_tickets, threshold=self.duplicate_threshold,
                )
                skip_dupes_in_llm = True
                self.emit(
                    "duplicates_detected_locally",
                    payload={
                        "duplicate_count": len(duplicates_from_embeddings),
                        "threshold": self.duplicate_threshold,
                    },
                    reasoning=(
                        f"Found {len(duplicates_from_embeddings)} duplicate candidates "
                        f"via local sentence-transformers (no LLM call)."
                    ),
                )
            except ToolError as e:
                # Embedding-tool failure shouldn't kill the agent — fall back
                # to LLM-based duplicate detection by leaving `skip_dupes_in_llm`
                # False.
                self.emit(
                    "embedding_unavailable",
                    payload={"error": str(e)[:200]},
                    reasoning="Local embeddings unavailable; falling back to LLM duplicate detection.",
                )

        # Build the vector index over existing tickets (or skip if small)
        used_embeddings = self.memory.index_tickets(existing_tickets)
        self.emit(
            "indexed_tickets",
            payload={"used_embeddings": used_embeddings, "ticket_count": len(existing_tickets)},
            reasoning=(
                "Built semantic index for top-K candidate retrieval."
                if used_embeddings
                else "Too few tickets for embeddings; sending full list to LLM."
            ),
        )

        # Slim payloads and run semantic narrow-down per story
        slim_stories = [
            {"id": s["id"], "title": s.get("title", ""), "description": s.get("description", "")}
            for s in stories
        ]

        candidates_per_story = {}
        for s in slim_stories:
            query = f"{s['title']}. {s['description']}"
            candidates = self.memory.search_similar(query, top_k=TOP_K)
            candidates_per_story[s["id"]] = [
                {
                    "id": c.get("id") or c.get("key") or f"#{c.get('number', '?')}",
                    "title": c.get("title") or c.get("summary") or "",
                    "description": c.get("description") or c.get("body") or "",
                }
                for c in candidates
            ]

        prompt = (
            self._prompt_template
            .replace("{{NEW_STORIES_JSON}}", json.dumps(slim_stories, indent=2))
            .replace("{{CANDIDATES_JSON}}", json.dumps(candidates_per_story, indent=2))
            .replace("{{CONSTRAINTS_JSON}}", json.dumps(constraints, indent=2))
        )

        try:
            parsed, usage = self.claude.call_for_json(prompt, max_tokens=8192)
        except ToolError as e:
            raise AgentError(f"Gap Detector LLM call failed: {e}") from e

        # Conflicts + gaps are always taken from the LLM. Duplicates come
        # from the embedding tool when enabled; otherwise from the LLM.
        if skip_dupes_in_llm:
            duplicates = duplicates_from_embeddings
        else:
            duplicates = parsed.get("duplicates", [])
        conflicts = parsed.get("conflicts", [])
        gaps = parsed.get("gaps", [])

        # Backstop sequential ids on gaps so every artifact carries a stable
        # `id` even if the model omits it — consistent with the parser,
        # constraint, and epic agents.
        for i, g in enumerate(gaps):
            if isinstance(g, dict):
                g.setdefault("id", f"G-{i + 1:02d}")

        self.memory.put("duplicates", duplicates)
        self.memory.put("conflicts", conflicts)
        self.memory.put("gaps", gaps)

        self.audit.record_tool_call(
            agent=self.name,
            tool=getattr(self.claude, "name", "claude"),
            request={"prompt_chars": len(prompt), "max_tokens": 8192},
            response_excerpt=str(parsed)[:300],
            tokens_used=(usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0),
            usage=usage,
            prompt=prompt,
            response_text=json.dumps(parsed, indent=2),
        )
        self.emit(
            "completed",
            payload={
                "duplicate_count": len(duplicates),
                "conflict_count": len(conflicts),
                "gap_count": len(gaps),
                "duplicate_source": "embeddings" if skip_dupes_in_llm else "llm",
            },
            reasoning=(
                f"Found {len(duplicates)} possible duplicates "
                f"({'local embeddings' if skip_dupes_in_llm else 'LLM'}), "
                f"{len(conflicts)} constraint conflicts, "
                f"and {len(gaps)} gaps in coverage."
            ),
        )
