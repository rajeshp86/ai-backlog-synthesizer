"""Cost estimation helpers for the Backlog Synthesizer UI.

Contains the agent-to-stage mapping, model-lookup helper, output-token
budgets, and the pre-run / post-run cost computation functions.
"""

from __future__ import annotations
from pathlib import Path

from pricing import estimate_cost_usd  # noqa: F401 — re-exported for callers

# Mapping table used by both the audit-log token rollup and the
# pipeline-card model badge. Accepts BOTH the agent class name
# ("DiscoveryEngine") and the agent's `.name` attribute ("parser") as input
# — the audit log records the latter, older history entries the former.
# Values are the per-stage keys used by `result["models"]`.
_AGENT_CLASS_TO_STAGE = {
    # Class-name lookups (legacy history entries).
    "DiscoveryEngine":     "parser",
    "ParserAgent":         "parser",  # kept for backward-compat with old audit logs
    "PolicyEngineAgent":   "constraint",
    "ConstraintAgent":     "constraint",  # kept for backward-compat with old audit logs
    "StoryGenerationAgent": "story_writer",
    "StoryWriterAgent":     "story_writer",  # kept for backward-compat with old audit logs
    "DeliveryPlannerAgent": "epic_decomposer",
    "EpicDecomposerAgent": "epic_decomposer",  # kept for backward-compat with old audit logs
    "InsightScannerAgent": "gap_detector",
    "GapDetectorAgent":    "gap_detector",  # kept for backward-compat with old audit logs
    # Stage-name lookups (audit log + token_usage in current runs).
    "parser":              "parser",
    "constraint":          "constraint",
    "story_writer":        "story_writer",
    "epic_decomposer":     "epic_decomposer",
    "gap_detector":        "gap_detector",
}


def _model_for_agent(agent_key: str, models_per_stage: dict) -> str:
    """Return the model id for the given agent identifier.

    `agent_key` can be either the agent class name (`DiscoveryEngine`) or
    the agent's `.name` attribute (`parser`). Returns an empty string
    when neither matches.
    """
    stage = _AGENT_CLASS_TO_STAGE.get(agent_key)
    if stage and models_per_stage:
        return models_per_stage.get(stage, "")
    return ""


# Output-token budget per stage. These are conservative averages from prior
# runs on the bundled sample (`samples/meeting_notes.txt`, 30-ticket backlog).
# Used by the pre-run cost estimator to set expectations BEFORE the user
# clicks Synthesize. The real bill will swing a bit either way; the sidebar
# label is prefixed with "≈" to make that clear.
_PRE_RUN_OUTPUT_BUDGET: dict[str, int] = {
    "parser":          1500,
    "constraint":      1200,
    "story_writer":    4500,
    "epic_decomposer": 3000,
    "gap_detector":    2500,
}


def _estimate_pre_run_cost(
    *,
    transcript_choice: str,
    transcript_upload,
    constraints_choice: str,
    constraints_upload,
    backlog_choice: str,
    backlog_upload,
    models: dict[str, str],
    TRANSCRIPT_OPTIONS: dict,
    CONSTRAINTS_OPTIONS: dict,
    BACKLOG_OPTIONS: dict,
) -> tuple[float, int, int]:
    """Estimate $ cost + input/output tokens before a run.

    Each stage only sees the inputs it actually consumes:
        parser           → transcript
        constraint       → constraints
        story_writer     → parser-output + constraint-output (we treat
                           these as the upstream agents' output budgets)
        epic_decomposer  → story-writer-output
        gap_detector     → story-writer-output + backlog

    This corrects an earlier draft that summed transcript+constraints+
    backlog and fed the lump into every stage — which double-counted
    inputs and pushed the estimate up by ~3x.

    `~4 chars per English token` is the standard back-of-envelope
    ratio. Output token budgets come from `_PRE_RUN_OUTPUT_BUDGET`,
    measured on prior runs of the bundled sample.
    """
    def _chars_of(selected, options: dict, upload) -> int:
        labels = selected if isinstance(selected, list) else ([selected] if selected else [])
        total = 0
        for lbl in labels:
            val = options.get(lbl)
            if val and val != "__upload__":
                try:
                    total += Path(str(val)).stat().st_size
                except OSError:
                    pass
        # Uploads are always combined with the selected samples now.
        ups = upload if isinstance(upload, list) else ([upload] if upload else [])
        total += sum(int(getattr(u, "size", 0) or 0) for u in ups)
        return total

    transcript_chars = _chars_of(transcript_choice, TRANSCRIPT_OPTIONS, transcript_upload)
    constraint_chars = _chars_of(constraints_choice, CONSTRAINTS_OPTIONS, constraints_upload)
    backlog_chars = _chars_of(backlog_choice, BACKLOG_OPTIONS, backlog_upload)

    transcript_tokens = transcript_chars // 4
    constraint_tokens = constraint_chars // 4
    backlog_tokens = backlog_chars // 4

    # Per-stage input tokens, mapping what each agent actually reads.
    parser_in       = transcript_tokens
    constraint_in   = constraint_tokens
    story_writer_in = _PRE_RUN_OUTPUT_BUDGET["parser"] + _PRE_RUN_OUTPUT_BUDGET["constraint"]
    epic_in         = _PRE_RUN_OUTPUT_BUDGET["story_writer"]
    # The Gap Detector sees stories + a sample of the backlog (the
    # vector store caps at ~5 candidates per story, but for a pre-run
    # estimate we model the entire backlog as input to be safe).
    gap_in          = _PRE_RUN_OUTPUT_BUDGET["story_writer"] + backlog_tokens

    stage_inputs = {
        "parser":           parser_in,
        "constraint":       constraint_in,
        "story_writer":     story_writer_in,
        "epic_decomposer":  epic_in,
        "gap_detector":     gap_in,
    }

    total_in = 0
    total_out = 0
    total_cost = 0.0
    for stage, output_tokens in _PRE_RUN_OUTPUT_BUDGET.items():
        model = (models or {}).get(stage) or ""
        if not model:
            continue
        input_tokens = stage_inputs.get(stage, 0)
        c = estimate_cost_usd(model, input_tokens, output_tokens)
        if c is None:
            continue
        total_in += input_tokens
        total_out += output_tokens
        total_cost += c

    return total_cost, total_in, total_out


def _compute_total_cost(token_usage: dict, models_per_stage: dict) -> float:
    """Sum per-agent costs using each agent's stage model rate.

    Skips the `total` row (it's the input/output sum, not a per-agent
    row). Returns 0.0 when no per-agent rows are present or no models
    are known.
    """
    total = 0.0
    if not token_usage:
        return 0.0
    for agent_key, vals in token_usage.items():
        if agent_key == "total":
            continue
        ai = int((vals or {}).get("input", 0) or 0)
        ao = int((vals or {}).get("output", 0) or 0)
        model = _model_for_agent(agent_key, models_per_stage)
        c = estimate_cost_usd(model, ai, ao) if model else None
        if c is not None:
            total += c
    return total
