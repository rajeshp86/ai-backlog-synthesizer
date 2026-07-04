"""LLM-as-judge qualitative scoring.

The deterministic metrics in `metrics.py` cover countable things: story
counts, topic keywords, duplicate IDs. They can't tell you whether the
acceptance criteria are *genuinely testable*, or whether the priority
rationale actually justifies the priority, or whether the story
descriptions are clear.

For those qualitative aspects we use Claude as a judge: give it the
synthesis output plus a short rubric, ask for a 1-5 score on each
qualitative dimension with a one-sentence reason.

The judge is wired into `run_evaluation.py` behind the `--use-llm-judge`
flag. The scores it returns are normalised to [0, 1] so they can be
aggregated alongside deterministic metric scores.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

# Lazy import: tests don't need the SDK
try:
    from anthropic import Anthropic
except ImportError:  # pragma: no cover - exercised only when SDK is absent
    Anthropic = None


DIMENSIONS: tuple[str, ...] = (
    "ac_quality",
    "priority_justification",
    "story_granularity",
    "tag_accuracy",
    "conflict_reasoning",
)


JUDGE_PROMPT = """You are a senior agile delivery lead grading a draft backlog synthesis produced by an AI system.

Below is the synthesis. Grade it on five qualitative dimensions, each 1-5 (1 = poor, 5 = excellent), with a one-sentence reason for each score.

1. **Acceptance-criteria quality** (ac_quality) — are the criteria genuinely testable (concrete, observable, measurable, ideally in Given/When/Then form)?
2. **Priority justification** (priority_justification) — do the priority_rationale fields actually justify the priorities chosen? Penalise hand-wavy reasoning.
3. **Story granularity** (story_granularity) — are the stories well-sized (single deliverable behaviour, not too broad, not micro)?
4. **Tag accuracy** (tag_accuracy) — are the tags appropriate for the story content and drawn from a consistent vocabulary?
5. **Conflict reasoning** (conflict_reasoning) — for any flagged conflicts, do the reasons cite the specific constraint correctly? If no conflicts are flagged AND none should have been, score 5.

Reply with JSON only, exactly matching this shape:

```json
{
  "scores": {
    "ac_quality": <int 1-5>,
    "priority_justification": <int 1-5>,
    "story_granularity": <int 1-5>,
    "tag_accuracy": <int 1-5>,
    "conflict_reasoning": <int 1-5>
  },
  "reasons": {
    "ac_quality": "<one sentence>",
    "priority_justification": "<one sentence>",
    "story_granularity": "<one sentence>",
    "tag_accuracy": "<one sentence>",
    "conflict_reasoning": "<one sentence>"
  },
  "overall_comment": "<two sentences of holistic feedback>"
}
```

# Synthesis to grade

```json
{{SYNTHESIS_JSON}}
```
"""


@dataclass
class JudgeResult:
    """Structured result of an LLM-as-judge run.

    `scores` are 1-5 ints from the judge; `normalized` rescales each
    dimension to [0, 1] = (score - 1) / 4 so it can be averaged with the
    deterministic metrics. `average_normalized` is the mean across the
    five dimensions.
    """

    scores: dict[str, int]
    reasons: dict[str, str]
    overall_comment: str
    normalized: dict[str, float] = field(default_factory=dict)
    average_normalized: float = 0.0
    raw_response: str = ""

    def to_dict(self) -> dict:
        return {
            "scores": self.scores,
            "reasons": self.reasons,
            "overall_comment": self.overall_comment,
            "normalized": self.normalized,
            "average_normalized": self.average_normalized,
        }


def _project_synthesis_for_judge(synthesis: dict) -> dict:
    """Strip fields the judge doesn't need — keeps the prompt focused and cheap.

    The audit trail and token usage aren't useful for qualitative grading
    of the *output*. Everything else (epics, conflicts, duplicates, gaps)
    is kept so the judge can reason about cross-cutting consistency.
    """
    drop = {"audit_trail", "token_usage", "dry_run_prompts"}
    return {k: v for k, v in synthesis.items() if k not in drop}


def _parse_judge_json(text: str) -> dict:
    """Extract the first JSON object from the judge's reply.

    Tries a fenced ```json block first, then any balanced { ... } region.
    Raises RuntimeError if neither parse succeeds.
    """
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise RuntimeError(f"Judge returned no JSON. Got: {text[:300]}")


def _normalize(raw: dict) -> JudgeResult:
    """Convert the judge's raw dict into a JudgeResult with scores in [0,1]."""
    scores_raw = raw.get("scores") or {}
    reasons = raw.get("reasons") or {}
    overall = raw.get("overall_comment", "")

    scores: dict[str, int] = {}
    normalized: dict[str, float] = {}
    for dim in DIMENSIONS:
        try:
            s = int(scores_raw.get(dim, 0))
        except (TypeError, ValueError):
            s = 0
        # Clamp to the 1-5 range the rubric promises.
        s = max(1, min(5, s)) if s else 0
        scores[dim] = s
        normalized[dim] = round(max(0.0, (s - 1) / 4.0), 4) if s else 0.0

    avg = round(sum(normalized.values()) / len(DIMENSIONS), 4) if normalized else 0.0
    return JudgeResult(
        scores=scores,
        reasons={dim: str(reasons.get(dim, "")) for dim in DIMENSIONS},
        overall_comment=str(overall),
        normalized=normalized,
        average_normalized=avg,
    )


def judge(synthesis: dict, model: str | None = None, *, client=None) -> JudgeResult:
    """Call Claude as a judge on a synthesis. Returns a JudgeResult.

    The `client` kwarg lets tests inject a fake with a `messages.create(...)`
    method that returns an object whose `.content[0].text` is the JSON
    reply. The default is a real `anthropic.Anthropic` client built from
    `ANTHROPIC_API_KEY`.

    Raises RuntimeError if neither a client is provided nor the SDK and
    API key are available, or if the judge returns unparseable output.
    """
    if client is None:
        if Anthropic is None:
            raise RuntimeError("anthropic SDK not installed and no client injected")
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set and no client injected")
        client = Anthropic(api_key=api_key)

    model = model or os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
    projected = _project_synthesis_for_judge(synthesis)
    prompt = JUDGE_PROMPT.replace("{{SYNTHESIS_JSON}}", json.dumps(projected, indent=2))

    response = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in response.content if hasattr(b, "text"))

    raw = _parse_judge_json(text)
    result = _normalize(raw)
    result.raw_response = text
    return result
