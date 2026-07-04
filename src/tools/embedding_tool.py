"""Local sentence-transformers embedding tool.

Used by the Gap Detector to find duplicate tickets without an LLM call.
Mirrors the pattern in V2's `src/retriever.py`:

    1. Embed each new story (title + description).
    2. Embed each existing ticket (title/summary + description/body).
    3. Compute cosine similarity (normalized embeddings → dot product).
    4. For each new story, emit any existing ticket above `threshold`.

Why local embeddings:
    No extra API key, no per-call cost. The default model
    (`sentence-transformers/all-MiniLM-L6-v2`) is ~80 MB on first download
    and produces 384-d vectors — plenty for ticket-similarity.

Design choices mirror V2:
    - Lazy model load: nothing is downloaded until `encode()` is first called,
      so importing this module is cheap and the dry-run path never triggers
      the download.
    - L2-normalized vectors so cosine == dot product.
    - Numpy for similarity rather than a vector DB — backlogs are small.
"""

from __future__ import annotations

from typing import Any

from logger_setup import get_logger
from tools.base import Tool, ToolError

logger = get_logger(__name__)

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingTool(Tool):
    """Lazy-loaded sentence-transformers wrapper for local embeddings."""

    name = "embedding"

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model = None  # SentenceTransformer instance, lazy
        self._np = None

    # ---------------------------------------------------- internals

    def _ensure_loaded(self) -> None:
        """Import deps + load the model on first use."""
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            import numpy as np
        except ImportError as e:  # pragma: no cover
            raise ToolError(
                "Local embeddings require sentence-transformers and numpy. "
                "Run: pip install -r requirements.txt"
            ) from e
        self._np = np
        logger.info("Loading embedding model %s (first run downloads ~80MB)", self.model_name)
        self._model = SentenceTransformer(self.model_name)

    # ---------------------------------------------------- public

    def encode(self, texts: list[str]):
        """Encode `texts` to L2-normalized embeddings. Returns numpy array."""
        self._ensure_loaded()
        return self._model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

    @staticmethod
    def _story_text(story: dict) -> str:
        """Build embedding text for a new story (title + description)."""
        title = (story.get("title") or "").strip()
        desc = (story.get("description") or "").strip()
        if title and desc:
            return f"{title}. {desc}"
        return title or desc

    @staticmethod
    def _ticket_text(ticket: dict) -> str:
        """Build embedding text for an existing ticket.

        Existing tickets carry inconsistent field names (`title` or `summary`,
        `description` or `body`) depending on whether they came from JIRA or
        GitHub. Prefer the human-facing fields and merge whichever pair we
        find.
        """
        title = (
            ticket.get("title")
            or ticket.get("summary")
            or ""
        ).strip()
        desc = (
            ticket.get("description")
            or ticket.get("body")
            or ""
        ).strip()
        if title and desc:
            return f"{title}. {desc}"
        return title or desc

    @staticmethod
    def _existing_id(ticket: dict) -> str:
        for key in ("id", "key", "number"):
            v = ticket.get(key)
            if v is not None:
                return str(v)
        return "?"

    def find_duplicates(
        self,
        new_stories: list[dict],
        existing_tickets: list[dict],
        threshold: float = 0.75,
    ) -> list[dict]:
        """For each new story, find existing tickets with cosine sim >= threshold.

        Returns a list of dicts in the same shape the LLM-based gap detector
        emits, plus a `similarity` field:
            {
                "story_id": <new story id>,
                "existing_id": <existing ticket id/key/number>,
                "confidence": "high" | "medium" | "low",
                "reason": "<short why>",
                "similarity": 0.83,
            }

        Confidence buckets (heuristic):
            >= 0.85  → "high"
            >= 0.78  → "medium"
            else     → "low"
        """
        if not new_stories or not existing_tickets:
            return []

        new_texts = [self._story_text(s) for s in new_stories]
        existing_texts = [self._ticket_text(t) for t in existing_tickets]

        # Skip embedding any item with no text — they can't be matched.
        valid_new_idx = [i for i, t in enumerate(new_texts) if t]
        valid_existing_idx = [i for i, t in enumerate(existing_texts) if t]
        if not valid_new_idx or not valid_existing_idx:
            return []

        new_vecs = self.encode([new_texts[i] for i in valid_new_idx])
        existing_vecs = self.encode([existing_texts[i] for i in valid_existing_idx])

        # Cosine similarity matrix: (num_new, num_existing). Both sides
        # are normalized, so dot product = cosine similarity.
        sim_matrix = new_vecs @ existing_vecs.T

        out: list[dict[str, Any]] = []
        np = self._np
        for row_idx, sim_row in enumerate(sim_matrix):
            new_story = new_stories[valid_new_idx[row_idx]]
            story_id = new_story.get("id") or f"ST-{valid_new_idx[row_idx] + 1:02d}"
            # Sort candidates by similarity descending so the first match
            # listed for any story is the strongest one.
            order = np.argsort(-sim_row)
            for col_pos in order:
                sim = float(sim_row[col_pos])
                if sim < threshold:
                    # `order` is sorted descending — no further candidate
                    # for this story can be above threshold.
                    break
                existing = existing_tickets[valid_existing_idx[int(col_pos)]]
                existing_id = self._existing_id(existing)
                if sim >= 0.85:
                    confidence = "high"
                elif sim >= 0.78:
                    confidence = "medium"
                else:
                    confidence = "low"
                out.append({
                    "story_id": story_id,
                    "existing_id": existing_id,
                    "confidence": confidence,
                    "reason": (
                        f"Local-embedding cosine similarity {sim:.2f} — "
                        f"new story title/description overlaps existing ticket "
                        f"\"{(existing.get('title') or existing.get('summary') or '')[:80]}\"."
                    ),
                    "similarity": round(sim, 3),
                })
        return out
