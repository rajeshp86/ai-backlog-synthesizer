"""LangGraph pipeline state definition.

`PipelineState` is the single typed dict that flows through every node in the
LangGraph StateGraph.  Each node receives the full state and returns a partial
dict with only the keys it updated — LangGraph merges the updates automatically.

Key groups:
  - **Inputs**     — set once by the caller before graph.invoke()
  - **Stage outputs** — written by individual agent nodes, read by downstream ones
  - **Runtime**    — non-serializable objects (AuditLog, JiraTool, ConfluenceTool)
                      stored in-memory by MemorySaver; not persisted to SqliteSaver
  - **Metadata**   — aggregated token usage, guardrail findings, error tracking
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict


def _merge_dicts(a: dict, b: dict) -> dict:
    """Reducer for keys written by concurrent fan-out nodes (e.g. stage_errors).

    LangGraph requires a reducer whenever two nodes in the same parallel step
    can both write the same key.  Without it, the runtime raises
    INVALID_CONCURRENT_GRAPH_UPDATE.  This reducer simply merges the two dicts
    so each node can return only its own new entries.
    """
    return {**a, **b}


class PipelineState(TypedDict, total=False):
    # ------------------------------------------------------------------ inputs
    transcript_text: str
    constraint_text: str
    existing_tickets: list[dict]
    vision_attachments: list          # list[VisionAttachment]
    resolved_models: dict[str, str]   # stage_name -> model_id
    use_embeddings_for_duplicates: bool
    persistent_memory: bool
    live_confluence_page_id: str | None
    live_jira: bool
    run_metadata: dict

    # --------------------------------------------------------- identity
    # Populated by the caller (Orchestrator.run) so every node — and the
    # security alert dispatcher — has stable run identity without relying
    # on run_metadata dict access.
    run_id: str      # UUID generated per invocation
    user_email: str  # authenticated user identity (email or "anonymous")

    # ---------------------------------------------------------- stage outputs
    # Populated stage-by-stage; downstream nodes read from here instead of
    # a shared MemoryStore.
    topics: list[dict]
    summary: str
    constraints: list[dict]
    stories: list[dict]
    epics: list[dict]
    gaps: list[dict]
    conflicts: list[dict]
    duplicates: list[dict]

    # --------------------------------------------------------------- runtime
    # These are live objects — kept in MemorySaver (in-process dict).
    # SqliteSaver would require custom serialization; use MemorySaver for now.
    _audit: Any        # AuditLog — accumulates events across all nodes
    _jira: Any         # JiraTool — injected via configurable, set in initialize_node
    _confluence: Any   # ConfluenceTool — same

    # --------------------------------------------------------- error tracking
    # Annotated with _merge_dicts so concurrent fan-out nodes (parse +
    # extract_constraints) can each return their own error entry without
    # triggering LangGraph's INVALID_CONCURRENT_GRAPH_UPDATE.
    stage_errors: Annotated[dict[str, str], _merge_dicts]

    # --------------------------------------------------------- result metadata
    token_usage: dict               # {agent: {input, output}, total: {input, output}}
    guardrail_findings: list[dict]  # quality checks (guardrails.py) + security findings
    security_findings: list[dict]   # injection + PII/toxicity/bias — merged into guardrail_findings by finalize_node
    audit_chain_fingerprint: str
