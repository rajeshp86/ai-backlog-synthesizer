"""Streamlit UI for the Backlog Synthesizer.

Single-file app on purpose — no auth, no role gating, no compare mode.
The multi-agent system is the product; the UI just makes the three
inputs / five outputs visible without a terminal.

To run:
    streamlit run app.py

The UI reads the same `orchestrator.Orchestrator` the CLI does, so any
synthesis you can run via `python src/main.py` you can also run here.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import queue as _queue
import re
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


class _PipelineCancelled(Exception):
    """Raised inside the run thread when the user clicks Cancel."""

import streamlit as st
from dotenv import load_dotenv

# -------------------------------------------------------- bootstrap

ROOT = Path(__file__).resolve().parent
# .env is for local development only. In production, set env vars via the
# deployment platform (Azure Container Apps secrets / Azure Key Vault).
load_dotenv(ROOT / ".env")

# Configurable client / org name shown on the login page and in the UI.
# Override with CLIENT_NAME env var — no code change needed for redeployment.
CLIENT_NAME: str = os.environ.get("CLIENT_NAME", "Quantum Technologies")

# --- Persistent-storage directories (overridable via env vars for Azure) ---
# In Azure, a single Azure Files share is mounted at /app/backlog-data; the
# env vars point logs and outputs to subdirectories inside that mount so all
# persistent data lands on the durable share rather than the ephemeral container
# layer.  Locally these default to ROOT/logs and ROOT/outputs as before.
LOGS_DIR    = Path(os.environ.get("LOGS_DIR",    str(ROOT / "logs")))
OUTPUTS_DIR = Path(os.environ.get("OUTPUTS_DIR", str(ROOT / "outputs")))

# --- Graceful shutdown (container SIGTERM) ---
# entrypoint.sh writes this flag file when it receives SIGTERM.
# The synthesis polling loop checks it and cancels the active run between
# LLM stages so the call is never abandoned mid-stream.
_SHUTDOWN_FLAG = Path(os.environ.get("SHUTDOWN_FLAG_PATH", "/tmp/.shutdown_requested"))

# Same Atlassian tenant — same credentials work for Jira and Confluence.
for _conf, _jira in (
    ("CONFLUENCE_BASE_URL", "JIRA_BASE_URL"),
    ("CONFLUENCE_EMAIL", "JIRA_EMAIL"),
    ("CONFLUENCE_API_TOKEN", "JIRA_API_TOKEN"),
):
    if not os.environ.get(_conf) and os.environ.get(_jira):
        os.environ[_conf] = os.environ[_jira]

sys.path.insert(0, str(ROOT / "src"))

# Streamlit's hot-reload re-executes app.py in the same process without clearing
# sys.modules. Evict every module sourced from src/ so we always get the current
# version on each run — prevents stale-module errors after code changes.
#
# Excluded: modules that hold process-level singletons that cannot be
# re-initialised without side effects:
#   metrics        — Prometheus REGISTRY is process-global; re-registering the
#                    same metric names raises ValueError.
#   circuit_breaker — CLAUDE_CB / GEMINI_CB state must persist across runs so
#                    the breaker doesn't reset on every Streamlit hot-reload.
_src_prefix = str(ROOT / "src")
_EVICT_SKIP = {"metrics", "circuit_breaker"}
for _mod_name in [k for k, v in sys.modules.items()
                  if getattr(v, "__file__", None) and
                  str(getattr(v, "__file__", "")).startswith(_src_prefix) and
                  k.split(".")[-1] not in _EVICT_SKIP and
                  k not in _EVICT_SKIP]:
    del sys.modules[_mod_name]

from input_loader import load_text, load_tickets, InputError  # noqa: E402
from pipeline import Orchestrator  # noqa: E402
from output_formatter import write_outputs  # noqa: E402
from ui.styling import get_css  # noqa: E402
from ui.cost import (  # noqa: E402
    estimate_cost_usd,
    _model_for_agent,
    _AGENT_CLASS_TO_STAGE,
    _PRE_RUN_OUTPUT_BUDGET,
    _estimate_pre_run_cost,
    _compute_total_cost,
)
from ui.run_history import (  # noqa: E402
    RUNS_DIR, DAILY_BUDGET_USD,
    _user_runs_dir, _save_run_to_disk, _load_run_history,
    _user_today_spend, _load_all_user_runs,
    show_run_history_dialog,
)
from startup_check import check_required_secrets, get_configured_integrations, check_python_version, check_secret_formats  # noqa: E402

# Per-user request rate limits (independent of $ budget).
# 0 = disabled for that window.
MAX_SYNTHESES_PER_HOUR: int = int(os.environ.get("MAX_SYNTHESES_PER_HOUR", "0"))
MAX_SYNTHESES_PER_DAY:  int = int(os.environ.get("MAX_SYNTHESES_PER_DAY",  "0"))
from metrics import (  # noqa: E402
    start_metrics_server,
    record_synthesis_start,
    record_synthesis_end,
)
from memory.store import preload_embedder  # noqa: E402
from memory.audit_log import AuditLog  # noqa: E402
from budget_store import (  # noqa: E402
    get_today_spend, record_spend, is_over_budget,
    try_reserve, settle_reservation,
    check_rate_limit, increment_request_count, get_request_counts,
)

# -------------------------------------------------------- startup validation
# Runs once per Streamlit session. Hard-fails on missing ANTHROPIC_API_KEY;
# surfaces warnings for partial optional configs as an info banner.
_startup_warnings: list[str] = check_python_version()
try:
    _startup_warnings += check_required_secrets()
except RuntimeError as _startup_err:
    st.error(f"**Configuration error:** {_startup_err}")
    st.info("Set the required environment variables and restart the app. See `.env.example`.")
    st.stop()
try:
    _startup_warnings += check_secret_formats()
except Exception:  # noqa: BLE001 — format checks must never crash startup
    pass

# -------------------------------------------------------- Metrics server
# Start once per process (idempotent inside start_metrics_server).
# Runs on METRICS_PORT (default 9090) in a daemon thread, independently
# of Streamlit. Point Prometheus at http://<host>:9090/metrics.
start_metrics_server()
# Pre-warm the sentence-transformer in a background thread so the first
# synthesis that needs duplicate detection does not pay the ~300ms load cost.
preload_embedder()
# Purge audit log rows older than AUDIT_LOG_RETENTION_DAYS (0 = keep forever).
# Runs once per Streamlit process start, not on every hot-reload.
if "audit_purge_done" not in st.session_state:
    threading.Thread(
        target=AuditLog.purge_old_runs,
        daemon=True,
        name="audit-retention-purge",
    ).start()
    st.session_state["audit_purge_done"] = True

# -------------------------------------------------------- Synthesis concurrency guard
# Semaphore allows up to MAX_CONCURRENT_SYNTHESES pipelines to run in the same
# process simultaneously (e.g. 3 users on a single container). Increase it when
# horizontal scaling is not available; set to 1 to force strict serialization.
_MAX_CONCURRENT_SYNTHESES = int(os.environ.get("MAX_CONCURRENT_SYNTHESES", "3"))
_SYNTHESIS_SEMAPHORE = threading.Semaphore(_MAX_CONCURRENT_SYNTHESES)
# Maximum wall-clock seconds a synthesis may run before it is auto-cancelled.
# Protects against orphaned threads when the browser disconnects mid-run.
_SYNTHESIS_TIMEOUT = int(os.environ.get("SYNTHESIS_TIMEOUT_SECONDS", "600"))

# -------------------------------------------------------- Upload safety limits
# Hard cap on user-uploaded file size. A 50 MB transcript would pass through
# all 5 LLM stages, generating unbounded API cost. Default: 512 KB.
_MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(512 * 1024)))

# Injection scanning is delegated entirely to security.InputSanitizer, which
# is the single source of truth for all 8 injection rules.  The old duplicate
# _INJECTION_PATTERNS list has been removed to prevent the two code paths from
# diverging when rules are updated.

st.set_page_config(
    page_title="Backlog Synthesizer · Quantum Technologies",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Inject CSS ──────────────────────────────────────────────────────────────
st.markdown(get_css(), unsafe_allow_html=True)

sys.path.insert(0, str(ROOT / "src"))

_current_user: str = "local"
_current_role: str = "contributor"
_display_name: str = "local"


def _is_admin() -> bool:
    """Admin role removed — all authenticated users are treated as contributor."""
    return False


def _can_run() -> bool:
    """All authenticated users can run synthesis."""
    return True


def _can_push_jira() -> bool:
    """All authenticated users can push to Jira (subject to feature flag)."""
    return True


def _can_use_live_atlassian() -> bool:
    return True


# CSS already injected above (before auth) — no duplicate needed here.

# -------------------------------------------------------- helpers


def _esc(value: Any) -> str:
    """Minimal HTML escape so user content doesn't escape its container."""
    if value is None:
        return ""
    s = str(value)
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;").replace("'", "&#x27;")
    )


def _pri_class(priority: str) -> str:
    p = (priority or "").strip().lower()
    if p == "high":
        return "pri-high"
    if p in ("medium", "med"):
        return "pri-medium"
    if p == "low":
        return "pri-low"
    return "pri-medium"


# Five-stage pipeline visualization.
# Each entry: (number, display name, description, agent class name used by
# the orchestrator — used to look up per-stage token counts from token_usage).
_STAGES = [
    ("01", "Discovery",       "Extract topics, actors, and requirements from the transcript",       "DiscoveryEngine"),
    ("02", "Policy Engine",   "Pull engineering rules and constraints from the architecture wiki",  "PolicyEngineAgent"),
    ("03", "Story Generation", "Generate user stories with Given/When/Then acceptance criteria",    "StoryGenerationAgent"),
    ("04", "Delivery Planner", "Group stories into themed epics and break each into tasks",         "DeliveryPlannerAgent"),
    # Gap Detector is a hybrid stage: local sentence-transformers embeddings
    # handle the duplicate-detection sub-step (no LLM cost), and an LLM
    # call judges conflicts and gaps. The model badge on this card refers
    # to the LLM used for conflicts/gaps only.
    ("05", "Insight Scanner", "Local embeddings find duplicates; LLM judges conflicts + gaps",      "InsightScannerAgent"),
]


def _fmt_tokens(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _render_pipeline(
    stage_states: list[str] | None = None,
    model: str | None = None,
    token_usage: dict | None = None,
    models_per_stage: dict | None = None,
) -> None:
    """Render the 5 stage cards.

    `stage_states[i]` is one of: "idle" (default), "active", "done",
    "failed", "skipped". When None, all stages render as idle. The
    `.stage.active` class drives the glow/pulse animation defined in
    `ui/styling.py`.

    `models_per_stage` — preferred: a `{stage_name: model_id}` dict.
    Each card shows ITS stage's model. Falls back to the summary
    `model` string only when the per-stage dict isn't provided.

    `token_usage` — if set, completed stages show their input/output tokens.
    Tokens are looked up by BOTH the agent class name and the stage
    name (token_usage in current orchestrator runs uses stage names).
    """
    if stage_states is None:
        stage_states = ["idle"] * len(_STAGES)
    token_usage = token_usage or {}
    models_per_stage = models_per_stage or {}
    cells = []
    for i, (num, name, sub, agent_cls) in enumerate(_STAGES):
        state = stage_states[i] if i < len(stage_states) else "idle"
        cls_map = {
            "idle": "stage",
            "active": "stage active",
            "done": "stage done",
            "failed": "stage error",
            "skipped": "stage skipped",
        }
        cls = cls_map.get(state, "stage")
        glyph = {
            "active": "●",
            "done": "✓",
            "failed": "!",
            "skipped": "—",
        }.get(state, "")
        glyph_html = (
            f'<span class="stage-glyph">{glyph}</span>' if glyph else ""
        )

        # Model badge: prefer the per-stage model (so each card shows
        # the model that stage actually used); fall back to the summary
        # string only when we don't have the per-stage dict.
        stage_model = _model_for_agent(agent_cls, models_per_stage)
        badge_text = stage_model or model or ""
        # For the Gap Detector card specifically, append a small "+embed"
        # hint so the user knows the duplicate sub-step is local (no LLM).
        embed_hint = (
            ' <span style="font-size:0.62rem;color:var(--violet);'
            'padding:1px 5px;border-radius:6px;background:var(--violet-glow);'
            'margin-left:0.3rem;">+embed</span>'
            if agent_cls == "InsightScannerAgent" else ""
        )
        model_html = (
            f'<div class="stage-model"><span class="stage-model-dot"></span>'
            f'{_esc(badge_text)}{embed_hint}</div>'
        ) if badge_text else ""

        # Token badge: look up by both class name and stage name so this
        # works against current runs and any legacy history rows.
        tokens_html = ""
        if state in ("done", "failed"):
            stage_key = _AGENT_CLASS_TO_STAGE.get(agent_cls, agent_cls)
            usage = token_usage.get(agent_cls) or token_usage.get(stage_key) or {}
            ai = int(usage.get("input") or 0)
            ao = int(usage.get("output") or 0)
            if ai or ao:
                tokens_html = (
                    f'<div class="stage-tokens">'
                    f'<span class="stage-tokens-in">↓ {_fmt_tokens(ai)}</span>'
                    f'<span class="stage-tokens-out">↑ {_fmt_tokens(ao)}</span>'
                    f'</div>'
                )

        cells.append(
            f'<div class="{cls}">{glyph_html}'
            f'<div class="stage-num">STAGE {num}</div>'
            f'<div class="stage-name">{_esc(name)}</div>'
            f'<div class="stage-sub">{_esc(sub)}</div>'
            f'{model_html}{tokens_html}</div>'
        )
    st.markdown(f'<div class="pipeline">{"".join(cells)}</div>', unsafe_allow_html=True)


def _render_kpis(result: dict) -> None:
    epics = result.get("epics", []) or []
    n_epics = len(epics)
    n_stories = sum(len(e.get("stories", []) or []) for e in epics)
    n_gaps = len(result.get("gaps", []) or [])
    n_conflicts = len(result.get("conflicts", []) or [])
    n_dups = len(result.get("duplicates", []) or [])

    html = f"""
    <div class="kpi-grid">
      <div class="kpi"><div class="kpi-label">Epics</div>
        <div class="kpi-value">{n_epics}</div>
        <div class="kpi-meta">top-level themes</div></div>
      <div class="kpi"><div class="kpi-label">Stories</div>
        <div class="kpi-value">{n_stories}</div>
        <div class="kpi-meta">with acceptance criteria</div></div>
      <div class="kpi amber"><div class="kpi-label">Gaps</div>
        <div class="kpi-value">{n_gaps}</div>
        <div class="kpi-meta">{'capabilities missing' if n_gaps else 'none detected'}</div></div>
      <div class="kpi rose"><div class="kpi-label">Conflicts</div>
        <div class="kpi-value">{n_conflicts}</div>
        <div class="kpi-meta">{'vs. constraints' if n_conflicts else 'no constraint clashes'}</div></div>
      <div class="kpi violet"><div class="kpi-label">Duplicates</div>
        <div class="kpi-value">{n_dups}</div>
        <div class="kpi-meta">{'overlap with backlog' if n_dups else 'no overlap with backlog'}</div></div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def _flatten_stories_for_editor(epics: list[dict]) -> list[dict]:
    """Flatten epic.stories into a flat rows list for st.data_editor.

    Returns rows that include the parent epic id + index so writes can
    round-trip back into the nested epic structure on save.
    """
    rows: list[dict] = []
    for ei, ep in enumerate(epics):
        for si, s in enumerate(ep.get("stories", []) or []):
            ac = s.get("acceptance_criteria") or []
            rows.append({
                "epic": ep.get("title", "")[:60],
                "id": s.get("id", ""),
                "summary": s.get("title", ""),
                "description": s.get("description", "") or "",
                "priority": (s.get("priority") or "Medium").strip().capitalize(),
                "category": (s.get("tags") or ["feature"])[0] if s.get("tags") else "feature",
                "acceptance_criteria": "\n".join(ac) if isinstance(ac, list) else str(ac or ""),
                # Hidden bookkeeping — used to write edits back.
                "_epic_idx": ei,
                "_story_idx": si,
            })
    return rows


def _apply_editor_edits(epics: list[dict], edited_rows: list[dict]) -> list[dict]:
    """Merge edits from the data editor back into the epics structure."""
    out = json.loads(json.dumps(epics))  # deep copy
    for row in edited_rows:
        ei = row.get("_epic_idx")
        si = row.get("_story_idx")
        if ei is None or si is None:
            continue
        if ei >= len(out) or si >= len(out[ei].get("stories", []) or []):
            continue
        s = out[ei]["stories"][si]
        s["title"] = (row.get("summary") or "").strip()
        s["description"] = (row.get("description") or "").strip()
        pri = (row.get("priority") or "Medium").strip()
        s["priority"] = pri or "Medium"
        cat = (row.get("category") or "").strip()
        if cat:
            # Store category as the first tag (matches what _flatten reads).
            tags = s.get("tags") or []
            if tags:
                tags[0] = cat
            else:
                tags = [cat]
            s["tags"] = tags
        ac_text = (row.get("acceptance_criteria") or "").strip()
        s["acceptance_criteria"] = [
            line.strip() for line in ac_text.splitlines() if line.strip()
        ]
    return out


def _render_epics_tab(result: dict) -> None:
    """Render epics either as cards (view) or as a data_editor (edit).

    Edits flow back into `st.session_state.result["epics"]` so the
    download buttons pick them up automatically.
    """
    epics = result.get("epics", []) or []
    total_stories = sum(len(e.get("stories") or []) for e in epics)
    if not epics or total_stories == 0:
        # Special-case the hallucination-check sample: zero stories is the
        # *expected* outcome (negative test), so frame it as a guardrail
        # PASS rather than a generic empty-result message.
        src = (st.session_state.get("source_label") or "").lower()
        if "hallucination_check" in src or "hallucination-check" in src:
            st.markdown(
                """
                <div class="guardrail-pass">
                    <div class="guardrail-pass-tag">✓  Hallucination guardrail · PASS</div>
                    <div class="guardrail-pass-title">
                        Zero stories produced — exactly the expected outcome.
                    </div>
                    <div class="guardrail-pass-body">
                        This run used a deliberately off-topic transcript (no engineering content).
                        The agent prompts instruct each model to return an empty list when there's
                        nothing legitimate to extract, instead of inventing stories. The same input
                        is asserted in the evaluation harness — every change to the prompts
                        re-verifies this behavior.
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.info(
                "Zero stories extracted. This happens when the input is too short, off-topic, "
                "or has no actionable content — the agent prompts instruct each model to return "
                "an empty list rather than hallucinate. If you expected stories, double-check the "
                "source text."
            )
        return

    # Edit / view toggle + reset button.
    c1, c2, c3 = st.columns([1, 1, 4])
    with c1:
        view_active = not bool(st.session_state.get("stories_edit_mode"))
        if st.button(
            ("● View" if view_active else "  View"),
            key="stories_view_btn",
            use_container_width=True,
            help="Read-only display.",
        ):
            st.session_state.stories_edit_mode = False
    with c2:
        edit_active = bool(st.session_state.get("stories_edit_mode"))
        if st.button(
            ("● Edit" if edit_active else "  Edit"),
            key="stories_edit_btn",
            use_container_width=True,
            help="Fix story fields before exporting. Edits flow into JSON / MD downloads.",
        ):
            st.session_state.stories_edit_mode = True
    with c3:
        if edit_active and st.session_state.get("epics_original") is not None:
            if st.button(
                "↺ Reset to original",
                key="stories_reset_btn",
                help="Restore the original LLM output and discard your edits.",
            ):
                st.session_state.result["epics"] = json.loads(
                    json.dumps(st.session_state.epics_original)
                )
                st.rerun()

    if st.session_state.get("stories_edit_mode"):
        rows = _flatten_stories_for_editor(epics)
        st.caption(
            "Editing in place — changes save to this session and flow into the "
            "JSON / Markdown downloads. Use **Reset to original** to undo."
        )
        edited = st.data_editor(
            rows,
            num_rows="fixed",
            use_container_width=True,
            column_config={
                "epic": st.column_config.TextColumn("Epic", width="small", disabled=True),
                "id": st.column_config.TextColumn("ID", width="small", disabled=True),
                "summary": st.column_config.TextColumn("Summary", width="medium"),
                "description": st.column_config.TextColumn("Description", width="large"),
                "priority": st.column_config.SelectboxColumn(
                    "Priority", options=["Low", "Medium", "High"], width="small",
                ),
                "category": st.column_config.SelectboxColumn(
                    "Category",
                    options=["feature", "bug", "tech-debt", "spike", "chore"],
                    width="small",
                ),
                "acceptance_criteria": st.column_config.TextColumn(
                    "Acceptance criteria (one per line)", width="large",
                ),
                "_epic_idx": None,
                "_story_idx": None,
            },
            key="stories_editor",
        )
        new_epics = _apply_editor_edits(epics, edited or [])
        st.session_state.result["epics"] = new_epics
        return

    # Read-only render — original card layout.
    for ep in epics:
        ep_html = []
        ep_html.append('<div class="epic-card">')
        ep_html.append(
            f'<div class="epic-head"><span class="epic-id">{_esc(ep.get("id"))}</span>'
            f'<span class="epic-title">{_esc(ep.get("title"))}</span></div>'
        )
        if ep.get("description"):
            ep_html.append(f'<div class="epic-desc">{_esc(ep["description"])}</div>')
        for s in ep.get("stories", []) or []:
            pri = s.get("priority") or "Medium"
            tags = s.get("tags") or []
            ac_items = s.get("acceptance_criteria") or []
            tasks = s.get("tasks") or []
            ep_html.append('<div class="story-card">')
            ep_html.append(
                f'<div class="story-head"><span class="story-id">{_esc(s.get("id"))}</span>'
                f'<span class="story-title">{_esc(s.get("title"))}</span>'
                f'<span class="story-pri {_pri_class(pri)}">{_esc(pri)}</span></div>'
            )
            if s.get("user_story"):
                ep_html.append(f'<div class="story-user">{_esc(s["user_story"])}</div>')
            # Evidence: the parser-captured customer quote that motivated the
            # story. Rendered as an inline blockquote so reviewers can trace
            # every story back to a source utterance in the transcript.
            evidence = s.get("evidence") or []
            if evidence:
                ev = evidence[0]
                quote = (ev.get("raw_quote") or "").strip()
                speaker = (ev.get("speaker") or "").strip()
                # Filter LLM placeholder values — "...", "null", etc. — so they
                # never reach the UI regardless of when the run was stored.
                _ph = {"...", "…", "null", "none", "n/a", "tbd", "unknown", "—", "-"}
                if quote.lower() in _ph:
                    quote = ""
                if speaker.lower() in _ph:
                    speaker = ""
                if quote:
                    attribution = f" — {_esc(speaker)}" if speaker else ""
                    # Collapsed by default — click "Evidence" label to expand.
                    # The quote is still there for audit/review; it just doesn't
                    # clutter the card in normal daily use.
                    ep_html.append(
                        f'<details style="margin:6px 0;">'
                        f'<summary style="cursor:pointer;font-size:11px;'
                        f'letter-spacing:0.06em;text-transform:uppercase;'
                        f'color:#64748b;list-style:none;display:flex;'
                        f'align-items:center;gap:4px;">'
                        f'<span style="font-size:9px;">▶</span>'
                        f'Evidence{attribution}'
                        f'</summary>'
                        f'<div style="border-left:3px solid #94a3b8;'
                        f'padding:6px 10px;margin:4px 0 0 0;color:#475569;'
                        f'font-style:italic;background:#f8fafc;border-radius:4px;">'
                        f'"{_esc(quote)}"'
                        f'</div>'
                        f'</details>'
                    )
            if tags:
                ep_html.append('<div class="tags-row">')
                for t in tags:
                    ep_html.append(f'<span class="tag">{_esc(t)}</span>')
                ep_html.append("</div>")
            if ac_items:
                ep_html.append('<ul class="story-ac">')
                for ac in ac_items:
                    ep_html.append(f"<li>{_esc(ac)}</li>")
                ep_html.append("</ul>")
            if tasks:
                ep_html.append('<ol class="task-list">')
                for tk in tasks:
                    ep_html.append(f'<li>{_esc(tk.get("title"))}</li>')
                ep_html.append("</ol>")
            ep_html.append("</div>")
        ep_html.append("</div>")
        st.markdown("".join(ep_html), unsafe_allow_html=True)



def _render_guardrails_tab(result: dict) -> None:
    """Render the post-LLM guardrail findings, grouped by severity.

    Empty state = a green "all clear" pass — the guardrails ran and
    found nothing worth flagging. That itself is a useful signal so we
    surface it explicitly rather than hiding the tab.
    """
    findings = result.get("guardrail_findings") or []
    if not findings:
        st.markdown(
            '<div class="guardrail-pass">'
            '<div class="guardrail-pass-tag">✓ All guardrails pass</div>'
            '<div class="guardrail-pass-title">No issues caught by post-LLM checks.</div>'
            '<div class="guardrail-pass-body">'
            'Story grounding, acceptance-criteria grammar, unique titles, '
            'canonical tags, and priority-rationale length all looked '
            'reasonable on this run.</div></div>',
            unsafe_allow_html=True,
        )
        return

    severity_order = {"error": 0, "warn": 1, "info": 2}
    findings_sorted = sorted(findings, key=lambda f: severity_order.get(f.get("severity"), 99))

    palette = {
        "error": ("var(--rose)", "var(--rose-glow)", "rgba(251,113,133,.4)"),
        "warn":  ("var(--amber)", "var(--amber-glow)", "rgba(251,191,36,.4)"),
        "info":  ("var(--accent)", "var(--accent-glow)", "rgba(34,211,238,.4)"),
    }

    for f in findings_sorted:
        sev = f.get("severity", "info")
        color, bg, border = palette.get(sev, palette["info"])
        story_ref = f.get("story_id")
        story_chip = (
            f'<span style="font-family:\'IBM Plex Mono\',monospace;'
            f'font-size:0.72rem;color:var(--text-faint);'
            f'margin-left:0.6rem;">{_esc(story_ref)}</span>'
            if story_ref else ""
        )
        st.markdown(
            f'<div style="margin-bottom:0.55rem;padding:0.6rem 0.85rem;'
            f'background:{bg};border:1px solid {border};border-radius:8px;">'
            f'<div style="display:flex;align-items:baseline;gap:0.5rem;">'
            f'<span style="font-size:0.65rem;font-weight:700;letter-spacing:0.12em;'
            f'text-transform:uppercase;color:{color};">{sev}</span>'
            f'<span style="font-family:\'IBM Plex Mono\',monospace;font-size:0.7rem;'
            f'color:var(--text-faint);">{_esc(f.get("code", ""))}</span>'
            f'{story_chip}</div>'
            f'<div style="font-size:0.85rem;color:var(--text);margin-top:0.2rem;">'
            f'{_esc(f.get("message", ""))}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


def _render_findings_tab(result: dict, kind: str) -> None:
    items = result.get(kind, []) or []
    if not items:
        kind_label = {"gaps": "gaps", "conflicts": "conflicts", "duplicates": "duplicates"}[kind]
        st.info(f"No {kind_label} detected for this run.")
        return
    css = {"gaps": "finding-gap", "conflicts": "finding-conflict", "duplicates": "finding-dup"}[kind]
    kind_label = {"gaps": "GAP", "conflicts": "CONFLICT", "duplicates": "DUPLICATE"}[kind]
    for item in items:
        parts = [f'<div class="finding-card {css}">']
        parts.append('<div class="finding-head">')
        parts.append(f'<span class="finding-kind">{kind_label}</span>')
        if kind == "gaps":
            parts.append(f'<span class="finding-title">{_esc(item.get("title") or item.get("description") or "")}</span>')
        elif kind == "conflicts":
            parts.append(
                f'<span class="finding-title">'
                f'{_esc(item.get("story_id") or "")} ↔ {_esc(item.get("with") or "constraint")}'
                f' · severity: {_esc(item.get("severity") or "unknown")}</span>'
            )
        else:  # duplicates
            parts.append(
                f'<span class="finding-title">'
                f'{_esc(item.get("story_id") or "")} ↔ existing {_esc(item.get("existing_id") or "?")}'
                f' · {_esc(item.get("confidence") or "")} confidence</span>'
            )
        parts.append("</div>")

        body = item.get("description") or item.get("reason") or ""
        if body:
            parts.append(f'<div class="finding-body">{_esc(body)}</div>')
        if item.get("evidence"):
            parts.append(f'<div class="finding-evidence">↳ {_esc(item["evidence"])}</div>')
        parts.append("</div>")
        st.markdown("".join(parts), unsafe_allow_html=True)


# ----- word-diff for duplicate compare modal --------------------------

def _tokenize_for_diff(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r"\w+|\s+|[^\w\s]", text)


def _word_diff_html(new_text: str, old_text: str) -> tuple[str, str]:
    """Return (new_html, old_html) with word-level highlight markup.

    Added (only-in-new) words: `.dup-diff-add` (green badge).
    Removed (only-in-existing) words: `.dup-diff-del` (amber strikethrough).
    Equal regions are rendered as plain escaped text.
    """
    new_tokens = _tokenize_for_diff(new_text)
    old_tokens = _tokenize_for_diff(old_text)
    matcher = difflib.SequenceMatcher(a=old_tokens, b=new_tokens, autojunk=False)
    new_parts, old_parts = [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_chunk = "".join(old_tokens[i1:i2])
        new_chunk = "".join(new_tokens[j1:j2])
        if tag == "equal":
            new_parts.append(_esc(new_chunk))
            old_parts.append(_esc(old_chunk))
        elif tag == "delete":
            old_parts.append(f'<span class="dup-diff-del">{_esc(old_chunk)}</span>')
        elif tag == "insert":
            new_parts.append(f'<span class="dup-diff-add">{_esc(new_chunk)}</span>')
        elif tag == "replace":
            new_parts.append(f'<span class="dup-diff-add">{_esc(new_chunk)}</span>')
            old_parts.append(f'<span class="dup-diff-del">{_esc(old_chunk)}</span>')
    return "".join(new_parts), "".join(old_parts)


@st.dialog("Duplicate comparison", width="large")
def show_duplicate_compare_dialog(focus_index: int = 0) -> None:
    """Open a modal that walks through every duplicate as side-by-side cards.

    `focus_index` is which duplicate to highlight first; the modal renders
    all of them in order, so it's mostly a scroll-anchor hint right now.
    """
    result = st.session_state.get("result") or {}
    dupes = result.get("duplicates", []) or []
    backlog = st.session_state.get("existing_tickets_cache", []) or []

    # Build lookup maps for both the new stories and the existing tickets.
    stories_by_id: dict[str, dict] = {}
    for ep in result.get("epics", []) or []:
        for s in ep.get("stories", []) or []:
            sid = s.get("id")
            if sid:
                stories_by_id[sid] = s

    backlog_by_id: dict[str, dict] = {}
    for item in backlog:
        if not isinstance(item, dict):
            continue
        for key in ("id", "key", "number"):
            v = item.get(key)
            if v is not None:
                backlog_by_id[str(v)] = item

    if not dupes:
        st.markdown('<div class="dup-side-missing">No duplicates flagged.</div>',
                    unsafe_allow_html=True)
        return

    st.markdown(
        f'<div style="font-size: 0.84rem; color: var(--text-muted); margin-bottom: 1rem;">'
        f'{len(dupes)} duplicate{"s" if len(dupes) != 1 else ""} flagged. '
        f'Review each pair below — added words are highlighted green; removed amber.</div>',
        unsafe_allow_html=True,
    )

    for d in dupes:
        sid = str(d.get("story_id", ""))
        existing_id = str(d.get("existing_id", ""))
        confidence = d.get("confidence", "")
        reason = d.get("reason", "")

        new_story = stories_by_id.get(sid, {})
        existing = backlog_by_id.get(existing_id, {})

        new_title = new_story.get("title", "(unknown story)")
        new_desc = (new_story.get("description") or "").strip()
        old_title = (
            existing.get("title")
            or existing.get("summary")
            or "(not found in backlog)"
        )
        old_desc = (existing.get("description") or existing.get("body") or "").strip()

        if new_desc or old_desc:
            new_desc_html, old_desc_html = _word_diff_html(new_desc, old_desc)
            new_desc_block = f'<div class="dup-side-desc">{new_desc_html}</div>'
            old_desc_block = f'<div class="dup-side-desc">{old_desc_html}</div>'
        else:
            new_desc_block = '<div class="dup-side-missing">No description.</div>'
            old_desc_block = '<div class="dup-side-missing">No description in backlog.</div>'

        new_title_html, old_title_html = _word_diff_html(new_title, old_title)

        st.markdown(
            f"""
            <div class="dup-diff-legend">
                <span class="dup-diff-legend-item"><span class="dup-diff-add">added</span> only in the new story</span>
                <span class="dup-diff-legend-item"><span class="dup-diff-del">removed</span> only in the existing ticket</span>
            </div>
            <div class="dup-pair">
                <div class="dup-side new">
                    <div class="dup-side-label">New · {_esc(sid)}</div>
                    <div class="dup-side-title">{new_title_html}</div>
                    {new_desc_block}
                </div>
                <div class="dup-vs">vs</div>
                <div class="dup-side existing">
                    <div class="dup-side-label">Existing · {_esc(existing_id)}</div>
                    <div class="dup-side-title">{old_title_html}</div>
                    {old_desc_block}
                </div>
            </div>
            <div class="dup-reason">
                <span class="conf-tag">{_esc(confidence)} confidence</span>{_esc(reason)}
            </div>
            """,
            unsafe_allow_html=True,
        )


# -------------------------------------------------------- session state

if "result" not in st.session_state:
    st.session_state.result = None
if "run_dir" not in st.session_state:
    st.session_state.run_dir = None
if "elapsed" not in st.session_state:
    st.session_state.elapsed = None
if "source_label" not in st.session_state:
    st.session_state.source_label = ""
if "stage_states" not in st.session_state:
    st.session_state.stage_states = None
if "model_used" not in st.session_state:
    st.session_state.model_used = ""
if "tokens_total" not in st.session_state:
    st.session_state.tokens_total = 0
if "cost_usd" not in st.session_state:
    st.session_state.cost_usd = 0.0
if "token_usage" not in st.session_state:
    st.session_state.token_usage = {}
if "stories_edit_mode" not in st.session_state:
    st.session_state.stories_edit_mode = False
if "epics_original" not in st.session_state:
    # Pristine copy of the LLM-produced epics; used by Reset-to-original.
    st.session_state.epics_original = None
if "existing_tickets_cache" not in st.session_state:
    # Stored so the duplicate compare dialog can look up backlog rows.
    st.session_state.existing_tickets_cache = []
if "dry_run_result" not in st.session_state:
    st.session_state.dry_run_result = None  # kept for history-load compat


# -------------------------------------------------------- model presets
# Per-stage model selection. The orchestrator accepts `models=dict[str,str]`
# keyed by stage name; the sidebar lets the user pick a preset (Open /
# Hybrid / Elite) or override each stage individually.
#
# Preset definitions are deliberately small and explicit — the spec lists
# these exact mappings. "Hybrid" is the default new-session value.
MODEL_PRESETS: dict[str, dict[str, str]] = {
    "free": {
        "parser":          "gemini-2.5-flash",
        "constraint":      "gemini-2.5-flash",
        "story_writer":    "gemini-2.5-flash",
        "epic_decomposer": "gemini-2.5-flash",
        "gap_detector":    "gemini-2.5-flash",
    },
    "balanced": {
        # Gemini Flash for mechanical extraction stages (fast, cheap);
        # Claude Haiku for the two reasoning-heavy stages.
        # Story Writer needs nuanced judgment for priority + AC quality.
        # Gap Detector needs strong reasoning to detect constraint conflicts.
        "parser":          "gemini-2.5-flash",
        "constraint":      "gemini-2.5-flash",
        "story_writer":    "claude-haiku-4-5",
        "epic_decomposer": "gemini-2.5-flash",
        "gap_detector":    "claude-haiku-4-5",
    },
    "premium": {
        "parser":          "claude-haiku-4-5",
        "constraint":      "claude-haiku-4-5",
        "story_writer":    "claude-haiku-4-5",
        "epic_decomposer": "claude-haiku-4-5",
        "gap_detector":    "claude-haiku-4-5",
    },
}
# Cost-per-run band shown below the preset chips. Rough heuristics from
# the spec — the real number lives in the post-run cost panel.
PRESET_COST_BAND = {
    "free":     "Free tier (Gemini) · ~$0",
    "balanced": "~$0.01 per run",   # now 2× Claude stages (Story Writer + Gap Detector)
    "premium":  "~$0.03 per run",
    "custom":   "custom mix",
}
# Models available in the advanced per-stage selectbox row.
MODEL_OPTIONS = [
    "claude-haiku-4-5",
    "claude-sonnet-4-5",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
]
STAGE_KEYS = ("parser", "constraint", "story_writer", "epic_decomposer", "gap_detector")
STAGE_DISPLAY_NAMES: dict[str, str] = {
    "parser":          "Discovery Engine",
    "constraint":      "Policy Engine Agent",
    "story_writer":    "Story Generation Agent",
    "epic_decomposer": "Delivery Planner Agent",
    "gap_detector":    "Insight Scanner Agent",
}

# -------- Persisted UI state ---------------------------------------
# Streamlit doesn't keep selectbox / preset state across a hard browser
# reload (new session). We mirror a small subset of the state to a JSON
# file so reopening the tab restores the user's last picks.
#
# Under Docker with multiple replicas each pod gets its own file keyed by
# HOSTNAME so concurrent writes never race — pod A's preferences never
# overwrite pod B's.  Within a pod, os.replace() gives an atomic write so
# a Streamlit rerun (main-thread re-execution) can't produce a torn file.
import socket as _socket
_POD_ID = os.environ.get("HOSTNAME", _socket.gethostname()).replace("/", "_")
UI_STATE_FILE = LOGS_DIR / f".ui_state_{_POD_ID}.json"


def _load_ui_state() -> dict:
    if UI_STATE_FILE.exists():
        try:
            return json.loads(UI_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _save_ui_state(state: dict) -> None:
    try:
        UI_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file then atomically replace the target so a
        # concurrent read never sees a half-written file.
        _tmp = UI_STATE_FILE.with_suffix(f".{os.getpid()}.tmp")
        _tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        _tmp.replace(UI_STATE_FILE)
    except OSError:
        pass  # non-critical


_persisted_ui = _load_ui_state()


def _default_index(saved_key: str, options_dict: dict) -> int:
    saved = _persisted_ui.get(saved_key)
    keys = list(options_dict.keys())
    if saved in keys:
        return keys.index(saved)
    return 0


def _default_multi(saved_key: str, options_dict: dict) -> list[str]:
    """Default selection for a multi-select source picker.

    Accepts persisted state that's either a list (new) or a single string
    (older single-select state), filters to currently-valid options, and
    falls back to the first concrete (non-upload) sample."""
    saved = _persisted_ui.get(saved_key)
    keys = list(options_dict.keys())
    if isinstance(saved, str):
        saved = [saved]
    if isinstance(saved, list):
        valid = [s for s in saved if s in keys]
        if valid:
            return valid
    for k, v in options_dict.items():
        if v not in ("__upload__", ""):
            return [k]
    return []


if "models" not in st.session_state:
    # Default = Balanced (or persisted preset). Per-key overrides go into
    # this dict from the advanced expander; preset buttons replace it.
    _saved_preset = _persisted_ui.get("active_preset", "balanced")
    if _saved_preset not in MODEL_PRESETS and _saved_preset != "custom":
        _saved_preset = "balanced"
    # BUG FIX: always load models from the saved preset on first init.
    # Previously a stale persisted preset (e.g. "free") would silently
    # override whatever the user selected, because models are loaded here
    # before the radio renders.
    base_preset = _saved_preset if _saved_preset in MODEL_PRESETS else "balanced"
    st.session_state.models = dict(MODEL_PRESETS[base_preset])
    # If the saved preset was "custom", restore the saved per-stage map.
    # Accept any recognised provider prefix (claude-*, gemini-*) so a saved
    # custom map isn't silently dropped when restoring.
    saved_custom = _persisted_ui.get("models") or {}
    if _saved_preset == "custom" and isinstance(saved_custom, dict):
        _valid_prefixes = ("claude-", "gemini-")
        for k, v in saved_custom.items():
            if k in STAGE_KEYS and (
                v in MODEL_OPTIONS
                or any(str(v).startswith(p) for p in _valid_prefixes)
            ):
                st.session_state.models[k] = v
if "active_preset" not in st.session_state:
    st.session_state.active_preset = _persisted_ui.get("active_preset", "balanced")
    if st.session_state.active_preset not in (*MODEL_PRESETS.keys(), "custom"):
        st.session_state.active_preset = "balanced"


# -------------------------------------------------------- sidebar

SAMPLES_DIR = ROOT / "samples"

TRANSCRIPT_OPTIONS = {
    "Q3 Planning — Meeting notes":
        SAMPLES_DIR / "meeting_notes.txt",
    "Q3 Strategy doc":
        SAMPLES_DIR / "product_strategy.md",
    "NCR notification escalation":
        SAMPLES_DIR / "ncr_escalation.txt",
    "Engineering standup":
        SAMPLES_DIR / "engineering_standup.txt",
    "Client support note (negative)":
        SAMPLES_DIR / "client_support_note.txt",
}
CONSTRAINTS_OPTIONS = {
    "Architecture constraints":
        SAMPLES_DIR / "architecture_constraints.md",
    "Product strategy doc":
        SAMPLES_DIR / "product_strategy.md",
}
BACKLOG_OPTIONS = {
    "JIRA backlog (30 tickets)":
        SAMPLES_DIR / "jira_backlog.json",
    "GitHub issues (13 tickets)":
        SAMPLES_DIR / "github_issues.json",
}

# Bundled sample images for the vision input — selectable directly so a
# whiteboard demo needs no upload. Maps label → image path.
VISION_SAMPLE_OPTIONS = {
    "Whiteboard — sprint planning sketch": SAMPLES_DIR / "whiteboard_sprint_planning.png",
}

def _expander_label(title: str, choices: list, empty_hint: str = "") -> str:
    """Compact expander label that stays on ONE line inside the narrow sidebar.
    Shows a ✓ badge + count when something is selected, empty hint otherwise."""
    if not choices:
        return f"{title}  {empty_hint}"
    count = f"  ·  {len(choices)} selected" if len(choices) > 1 else "  ✓"
    return f"{title}{count}"


with st.sidebar:
    # ── Brand ──────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="acc-brand">'
        '<span class="acc-wordmark">Quantum Technologies</span>'
        '<span class="acc-eyebrow">AI-First Backlog Intelligence</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="rev-bar"></div>'
        '<div class="app-header">'
        '<span class="app-icon">⚙️</span>'
        '<div class="app-title-block">'
        '<div class="app-title">Backlog Synthesizer</div>'
        '<div class="app-tagline">🏭 Quantum Technologies &nbsp;·&nbsp; ⚡ Multi-agent &nbsp;·&nbsp; 🛡️ Five specialists &nbsp;·&nbsp; 📋 Audited</div>'
        '</div>'
        f'<div class="app-client-chip">⚙️ {CLIENT_NAME}</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Show startup warnings if any ───────────────────────────────────────
    for _w in _startup_warnings:
        st.warning(_w, icon="⚠️")

    # ── INPUTS ─────────────────────────────────────────────────────────────
    if True:
        # ── INPUTS ───────────────────────────────────────────────────────────
        _saved_transcript = _default_multi("transcript_choice", TRANSCRIPT_OPTIONS)
        with st.expander(
            _expander_label("📝 Transcript", _saved_transcript, empty_hint="pick a source"),
            expanded=not bool(_saved_transcript),
        ):
            transcript_choice = st.multiselect(
                "Transcript",
                options=list(TRANSCRIPT_OPTIONS.keys()),
                default=_saved_transcript,
                label_visibility="collapsed",
                key="transcript_choice",
                help="Pick one or more bundled transcripts — combined into one source.",
            )
            transcript_upload = st.file_uploader(
                "↑ Upload (txt / md / pdf)", type=["txt", "md", "pdf"],
                accept_multiple_files=True, key="transcript_upload",
                help="Optional — combined with any samples selected above.",
            )
            if True:
                st.caption("**📷 Whiteboard / vision**")
                vision_samples = st.multiselect(
                    "Vision samples",
                    options=list(VISION_SAMPLE_OPTIONS.keys()),
                    default=_default_multi("vision_samples", VISION_SAMPLE_OPTIONS) if _persisted_ui.get("vision_samples") else [],
                    key="vision_samples", label_visibility="collapsed",
                    help="Bundled whiteboard images — fed directly to the Discovery Engine.",
                )
                vision_uploads = st.file_uploader(
                    "↑ Upload whiteboard (PNG / JPG)", type=["png", "jpg", "jpeg", "webp"],
                    accept_multiple_files=True, key="vision_uploads",
                    help="Vision-capable models only.",
                )
            else:
                vision_samples = []
                vision_uploads = []

        _saved_constraints = _default_multi("constraints_choice", CONSTRAINTS_OPTIONS)
        with st.expander(
            _expander_label("📐 Wiki", _saved_constraints, empty_hint="optional"),
            expanded=False,
        ):
            constraints_choice = st.multiselect(
                "Wiki",
                options=list(CONSTRAINTS_OPTIONS.keys()),
                default=_saved_constraints,
                label_visibility="collapsed",
                key="constraints_choice",
                help="Pick one or more wiki pages. Leave empty to skip the Policy Engine Agent.",
            )
            constraints_upload = st.file_uploader(
                "↑ Upload wiki (md / txt)", type=["md", "txt"],
                accept_multiple_files=True, key="constraints_upload",
                help="Combined with any wiki samples selected above.",
            )

        _saved_backlog = _default_multi("backlog_choice", BACKLOG_OPTIONS)
        with st.expander(
            _expander_label("🗂 Backlog", _saved_backlog, empty_hint="optional"),
            expanded=False,
        ):
            backlog_choice = st.multiselect(
                "Backlog",
                options=list(BACKLOG_OPTIONS.keys()),
                default=_saved_backlog,
                label_visibility="collapsed",
                key="backlog_choice",
                help="Ticket exports merged for duplicate detection. Leave empty to skip.",
            )
            backlog_upload = st.file_uploader(
                "↑ Upload backlog (JSON)", type=["json"],
                accept_multiple_files=True, key="backlog_upload",
                help="Merged with any backlog samples selected above.",
            )

        # ── Live Atlassian ────────────────────────────────────────────────────
        use_live_confluence = False
        use_live_jira = False
        live_confluence_page_id = ""
        if True:
            _live_conf_active = bool(st.session_state.get("use_live_confluence"))
            _live_jira_active = bool(st.session_state.get("use_live_jira"))
            _live_label = "☁ Live Atlassian" + (" — active" if (_live_conf_active or _live_jira_active) else "")
            with st.expander(_live_label, expanded=False):
                use_live_confluence = st.toggle(
                    "Pull constraints from live Confluence",
                    value=False,
                    help="Fetches a Confluence page by ID. Overrides the wiki selector above.",
                    key="use_live_confluence",
                )
                live_confluence_page_id = ""
                if use_live_confluence:
                    live_confluence_page_id = st.text_input(
                        "Confluence page ID",
                        value=os.environ.get("CONFLUENCE_PAGE_ID", ""),
                        placeholder="e.g. 65830",
                        key="live_confluence_page_id",
                    )
                use_live_jira = st.toggle(
                    "Pull backlog from live Jira",
                    value=False,
                    help=f"Fetches issues from project `{os.environ.get('JIRA_PROJECT_KEY') or '?'}`. Overrides the backlog selector above.",
                    key="use_live_jira",
                )

        # ── MODELS ────────────────────────────────────────────────────────────
        st.markdown("### Models")
        _label_to_key = {"Open": "free", "Hybrid": "balanced", "Elite": "premium"}
        _key_to_label = {v: k for k, v in _label_to_key.items()}
        _allowed_preset_keys = list(MODEL_PRESETS.keys())
        _preset_labels = [
            lbl for lbl, key in _label_to_key.items()
            if key in _allowed_preset_keys
        ] or ["Open", "Hybrid"]

        _active = st.session_state.active_preset
        if _active not in [_label_to_key[l] for l in _preset_labels] and _active != "custom":
            _active = "balanced"
            st.session_state.active_preset = "balanced"
            st.session_state.models = dict(MODEL_PRESETS["balanced"])

        # Check which providers are actually available right now.
        _has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
        _has_google    = bool(os.environ.get("GOOGLE_API_KEY", "").strip())

        # Each preset requires specific providers — derive its ready status.
        # We check env-var presence (fast); actual API validity is caught at run time.
        def _preset_status(key: str) -> tuple[bool, str]:
            """Return (ready, reason_if_not_ready) for a preset key."""
            if key == "free":
                return (_has_google, "needs GOOGLE_API_KEY")
            if key == "balanced":
                if not _has_google and not _has_anthropic:
                    return (False, "needs GOOGLE_API_KEY + ANTHROPIC_API_KEY")
                if not _has_google:
                    return (False, "needs GOOGLE_API_KEY")
                if not _has_anthropic:
                    return (False, "needs ANTHROPIC_API_KEY")
                return (True, "")
            if key == "premium":
                return (_has_anthropic, "needs ANTHROPIC_API_KEY")
            return (True, "")

        # ── Colored dot status row ────────────────────────────────────────────
        # Green dot = every model in the preset is available right now.
        # Red dot   = at least one model is missing a dependency.
        # Hovering a red dot shows the tooltip explaining what's missing.
        _dot_chips = []
        for _lbl in _preset_labels:
            _pkey = _label_to_key[_lbl]
            _ready, _reason = _preset_status(_pkey)
            _dot_color = "#34d399" if _ready else "#fb7185"   # green / red
            _dot_glow  = "0 0 6px rgba(52,211,153,0.5)" if _ready else "0 0 6px rgba(251,113,133,0.5)"
            _is_active_chip = (_active == _pkey)
            _chip_bg     = "rgba(52,211,153,0.1)"  if _is_active_chip and _ready  else \
                           "rgba(251,113,133,0.1)" if _is_active_chip and not _ready else \
                           "var(--bg-elev-1)"
            _chip_border = _dot_color if _is_active_chip else "var(--border)"
            _tooltip = (
                f"All models in {_lbl} preset are available"
                if _ready else
                f"{_lbl} preset unavailable: {_reason}"
            )
            _dot_chips.append(
                f'<span title="{_esc(_tooltip)}" style="'
                f'display:inline-flex;align-items:center;gap:5px;'
                f'padding:3px 10px;border-radius:20px;font-size:0.78rem;'
                f'color:var(--text);background:{_chip_bg};'
                f'border:1px solid {_chip_border};white-space:nowrap;">'
                f'<span style="width:9px;height:9px;border-radius:50%;'
                f'background:{_dot_color};flex-shrink:0;'
                f'box-shadow:{_dot_glow};display:inline-block;"></span>'
                f'{_esc(_lbl)}'
                f'</span>'
            )
        st.markdown(
            f'<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:4px;">'
            + "".join(_dot_chips)
            + '</div>'
            + '<div style="display:flex;gap:12px;margin-bottom:6px;font-size:0.68rem;color:var(--text-faint);">'
            + '<span style="display:flex;align-items:center;gap:4px;">'
            + '<span style="width:7px;height:7px;border-radius:50%;background:#34d399;display:inline-block;"></span>All models online</span>'
            + '<span style="display:flex;align-items:center;gap:4px;">'
            + '<span style="width:7px;height:7px;border-radius:50%;background:#fb7185;display:inline-block;"></span>Unavailable — hover for details</span>'
            + '</div>',
            unsafe_allow_html=True,
        )

        # ── Selectbox — clean names only, no status text ──────────────────────
        _radio_index = (
            _preset_labels.index(_key_to_label[_active])
            if _active in _key_to_label and _key_to_label[_active] in _preset_labels
            else min(1, len(_preset_labels) - 1)
        )
        _picked_label = st.selectbox(
            "Model preset",
            options=_preset_labels,
            index=_radio_index,
            label_visibility="collapsed",
            key="preset_radio",
            help=(
                "Open: all Gemini Flash · free tier.  "
                "Hybrid: Gemini Flash + Claude Sonnet for Story Generation & Insight Scanner.  "
                "Elite: all Claude Sonnet."
            ),
        )
        _picked_key = _label_to_key.get(_picked_label, "balanced")

        def _apply_preset(key: str) -> None:
            st.session_state.models = dict(MODEL_PRESETS[key])
            st.session_state.active_preset = key
            st.session_state["_preset_radio_last"] = key
            # Also turn off per-stage override when preset changes — user is
            # explicitly picking a preset, so override should reset cleanly.
            st.session_state["_stage_override_enabled"] = False
            # Clear per-stage widget state so the override selects reflect the
            # new preset. Without this, Streamlit keeps the old selectbox value
            # even after the preset changes (stale widget state bug).
            for _s in STAGE_KEYS:
                st.session_state.pop(f"model_pick_{_s}", None)
            _save_ui_state({
                "transcript_choice":   transcript_choice,
                "constraints_choice":  constraints_choice,
                "backlog_choice":      backlog_choice,
                "active_preset":       key,
                "models":              dict(MODEL_PRESETS[key]),
            })
            st.rerun()

        # Track the last preset the user explicitly picked in the selectbox.
        # This lets us distinguish between:
        #   (a) user changed the dropdown → apply the new preset
        #   (b) active_preset became "custom" due to per-stage override,
        #       but the dropdown still shows the old preset → do NOT reset,
        #       or the override would be wiped on every rerun.
        _last_explicit_preset = st.session_state.get("_preset_radio_last", _active)

        if _picked_key != _last_explicit_preset:
            # User explicitly changed the preset dropdown — apply it.
            st.session_state["_preset_radio_last"] = _picked_key
            _apply_preset(_picked_key)
        elif _picked_key != _active and _active != "custom":
            # Drift between displayed preset and active (not a custom override) — sync.
            st.session_state["_preset_radio_last"] = _picked_key
            _apply_preset(_picked_key)

        # If the selected preset is not ready, show a clear actionable error.
        _sel_ready, _sel_reason = _preset_status(_picked_key)
        if not _sel_ready:
            _fix_hint = {
                "free":     "Add `GOOGLE_API_KEY=...` to your `.env` file.",
                "balanced": "Add the missing API key(s) to your `.env` file.",
                "premium":  "Add `ANTHROPIC_API_KEY=...` to your `.env` file.",
            }.get(_picked_key, "Check your `.env` file.")
            st.error(
                f"**{_picked_label} preset not available** — {_sel_reason}. {_fix_hint}"
            )

        _vision_present = bool(vision_samples) or bool(vision_uploads)
        _transcript_ready = bool(transcript_choice) or bool(transcript_upload) or _vision_present

        # ── Rate-limit usage badge ────────────────────────────────────────────
        if MAX_SYNTHESES_PER_HOUR > 0 or MAX_SYNTHESES_PER_DAY > 0:
            _rl_hourly, _rl_daily = get_request_counts(_current_user)
            _rl_parts = []
            if MAX_SYNTHESES_PER_HOUR > 0:
                _rl_h_pct = _rl_hourly / MAX_SYNTHESES_PER_HOUR
                _rl_h_color = "#fb7185" if _rl_hourly >= MAX_SYNTHESES_PER_HOUR else \
                              "#f59e0b" if _rl_h_pct >= 0.8 else "#34d399"
                _rl_parts.append(
                    f'<span style="color:{_rl_h_color};font-weight:600;">'
                    f'{_rl_hourly}/{MAX_SYNTHESES_PER_HOUR}</span>'
                    f'<span style="color:var(--text-faint);"> this hour</span>'
                )
            if MAX_SYNTHESES_PER_DAY > 0:
                _rl_d_pct = _rl_daily / MAX_SYNTHESES_PER_DAY
                _rl_d_color = "#fb7185" if _rl_daily >= MAX_SYNTHESES_PER_DAY else \
                              "#f59e0b" if _rl_d_pct >= 0.8 else "#34d399"
                _rl_parts.append(
                    f'<span style="color:{_rl_d_color};font-weight:600;">'
                    f'{_rl_daily}/{MAX_SYNTHESES_PER_DAY}</span>'
                    f'<span style="color:var(--text-faint);"> today</span>'
                )
            st.markdown(
                '<div style="font-size:0.75rem;margin-bottom:6px;display:flex;gap:10px;'
                'align-items:center;padding:4px 8px;background:var(--bg-elev-1);'
                'border:1px solid var(--border);border-radius:6px;">'
                '<span style="font-size:0.62rem;font-weight:700;letter-spacing:0.12em;'
                'text-transform:uppercase;color:var(--text-faint);">Runs</span>'
                + " &nbsp;·&nbsp; ".join(_rl_parts)
                + "</div>",
                unsafe_allow_html=True,
            )

        # ── SYNTHESIZE ────────────────────────────────────────────────────────
        _rate_blocked = (
            (MAX_SYNTHESES_PER_HOUR > 0 and _rl_hourly >= MAX_SYNTHESES_PER_HOUR)
            or (MAX_SYNTHESES_PER_DAY > 0 and _rl_daily >= MAX_SYNTHESES_PER_DAY)
        ) if (MAX_SYNTHESES_PER_HOUR > 0 or MAX_SYNTHESES_PER_DAY > 0) else False
        run_clicked = st.button(
            "▶  Synthesize", type="primary", use_container_width=True,
            disabled=not _transcript_ready or _rate_blocked,
        )
        if not _transcript_ready:
            st.caption("↑ Pick a transcript source first.")
        elif _rate_blocked:
            st.caption("Rate limit reached — see counts above.")

        # ── JIRA PUSH — gated by jira_write_back feature flag ────────────────
        # Approval dialog is always shown regardless; this flag controls visibility.
        _sb_jira_ready = bool(
            os.environ.get("JIRA_BASE_URL") and os.environ.get("JIRA_EMAIL")
            and os.environ.get("JIRA_API_TOKEN") and os.environ.get("JIRA_PROJECT_KEY")
        )
        _jira_write_allowed = True
        if _sb_jira_ready and _jira_write_allowed and st.session_state.get("result"):
            if st.button(f"⤴  Push to Jira ({os.environ.get('JIRA_PROJECT_KEY')})",
                         use_container_width=True, key="sidebar_jira_btn"):
                st.session_state["_trigger_jira"] = True  # called after definition below
        elif _sb_jira_ready and _jira_write_allowed:
            st.caption("Run a synthesis first, then push to Jira.")

    # ── end sidebar inputs block ──────────────────────────────────────────────

    # ── FOOTER ─────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="acc-footer">'
        '<span class="acc-mark">Quantum Technologies</span> · AI-First Backlog Intelligence<br>'
        f'Demonstration on mock data — fictional client <strong>{CLIENT_NAME}</strong>. '
        'Jira / Confluence run in mock mode by default; live Atlassian is optional.'
        '</div>',
        unsafe_allow_html=True,
    )

# Persist user's selections so a hard browser reload preserves them.
_save_ui_state({
    "transcript_choice":   transcript_choice,
    "constraints_choice":  constraints_choice,
    "backlog_choice":      backlog_choice,
    "active_preset":       st.session_state.get("active_preset", "balanced"),
    "models":              dict(st.session_state.get("models") or {}),
})


# -------------------------------------------------------- main canvas

# ---- Main canvas ----


# ---- Top-nav dialogs ----
@st.dialog("How it works", width="large")
def show_how_it_works_dialog() -> None:
    st.markdown(
        "**Backlog Synthesizer** runs five specialized agents in sequence — each does "
        "one job and writes to a shared, audited memory:\n\n"
        "1. **Discovery Engine** — extracts the distinct topics from the transcript.\n"
        "2. **Policy Engine Agent** — reads the wiki for `must` / `forbidden` rules.\n"
        "3. **Story Generation Agent** — drafts a user story (Given/When/Then AC + priority) per topic.\n"
        "4. **Delivery Planner Agent** — groups stories into epics and breaks each into tasks.\n"
        "5. **Insight Scanner Agent** — local embeddings flag duplicates against your backlog; the "
        "LLM flags conflicts vs. constraints and missing gaps.\n\n"
        "Every step is captured in an **audit trail**, and you can push the result straight "
        "into **Jira** as Epic → Story → Sub-task."
    )
    st.caption("Pick sources on the left (or upload your own / a whiteboard image), then Synthesize.")


@st.dialog("Export", width="large")
def show_export_dialog() -> None:
    res = st.session_state.get("result")
    if not res:
        st.info("Run a synthesis first — then export it here.")
        return
    from output_formatter import _render_markdown as _bm  # local import
    rd = st.session_state.get("run_dir")
    stem = rd.name if rd else datetime.now().strftime("%Y%m%d_%H%M%S")
    md = _bm(res, source_label=st.session_state.get("source_label", ""))
    js = json.dumps({k: v for k, v in res.items() if k != "audit_trail"}, indent=2)
    st.download_button("↓  synthesis.md", md, file_name=f"{stem}_synthesis.md",
                       mime="text/markdown", use_container_width=True)
    st.download_button("↓  synthesis.json", js, file_name=f"{stem}_synthesis.json",
                       mime="application/json", use_container_width=True)
    st.download_button("↓  audit_trail.md", res.get("audit_trail", ""),
                       file_name=f"{stem}_audit_trail.md", mime="text/markdown",
                       use_container_width=True)


@st.dialog("Create in Jira", width="large")
def show_jira_dialog() -> None:
    res = st.session_state.get("result")
    if not res:
        st.info("Run a synthesis first — then publish it to Jira here.")
        return
    _ready = all(os.environ.get(k) for k in
                 ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY"))
    if not _ready:
        st.warning("Set JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN / JIRA_PROJECT_KEY in `.env` to enable.")
        return
    _proj = os.environ.get("JIRA_PROJECT_KEY")

    # ---- Human-in-the-loop approval gate ----
    _epics = res.get("epics") or []
    _n_conflicts = len(res.get("conflicts") or [])
    _n_gaps = len(res.get("gaps") or [])
    _guardrail_errors = sum(1 for f in (res.get("guardrail_findings") or []) if f.get("severity") == "error")

    if _guardrail_errors > 0:
        st.warning(
            f"**{_guardrail_errors} guardrail error(s) detected.** "
            "Review the Guardrails tab before publishing — these stories may have "
            "missing grounding or unresolvable constraint conflicts."
        )

    # ── Per-story selection ───────────────────────────────────────────────────
    st.markdown(
        '<div style="font-size:0.62rem;font-weight:700;letter-spacing:0.14em;'
        'text-transform:uppercase;color:var(--accent);margin-bottom:0.5rem;">'
        'Select items to publish</div>',
        unsafe_allow_html=True,
    )

    _priority_colors = {"High": "var(--danger)", "Medium": "var(--warning)", "Low": "var(--success)"}

    _selected_epics: list[dict] = []
    for _ei, _epic in enumerate(_epics):
        _epic_title = _epic.get("title") or _epic.get("name") or f"Epic {_ei + 1}"
        _stories = _epic.get("stories") or []

        with st.expander(f"📦 {_epic_title}", expanded=True):
            _epic_desc = _epic.get("description") or ""
            if _epic_desc:
                st.caption(_epic_desc[:200] + ("…" if len(_epic_desc) > 200 else ""))

            _sel_stories: list[dict] = []
            for _si, _story in enumerate(_stories):
                _story_title = _story.get("title") or _story.get("name") or f"Story {_si + 1}"
                _priority = _story.get("priority") or "Medium"
                _pcolor = _priority_colors.get(_priority, "#888888")
                _ac = _story.get("acceptance_criteria") or []
                _tasks = _story.get("tasks") or []

                _col_check, _col_detail = st.columns([1, 11])
                with _col_check:
                    _include = st.checkbox(
                        "",
                        value=True,
                        key=f"jira_story_{_ei}_{_si}",
                        label_visibility="collapsed",
                    )
                with _col_detail:
                    st.markdown(
                        f'<div style="padding:0.45rem 0.6rem;border-left:3px solid {_pcolor};'
                        f'background:var(--bg-elev-1);border-radius:0 5px 5px 0;margin-bottom:0.25rem;">'
                        f'<span style="font-size:0.84rem;font-weight:600;">{_esc(_story_title)}</span>'
                        f'&nbsp;&nbsp;<span style="font-size:0.7rem;color:{_pcolor};font-weight:700;">'
                        f'{_esc(_priority)}</span>'
                        + (f'&nbsp;&nbsp;<span style="font-size:0.7rem;color:var(--text-faint);">'
                           f'✅ {len(_ac)} AC &nbsp;·&nbsp; 🔧 {len(_tasks)} tasks</span>'
                           if _ac or _tasks else "")
                        + '</div>',
                        unsafe_allow_html=True,
                    )

                if _include:
                    _sel_stories.append(_story)

            if _sel_stories:
                _selected_epics.append({**_epic, "stories": _sel_stories})

    # Recount based on selection
    _n_epics_sel = len(_selected_epics)
    _n_stories_sel = sum(len(e.get("stories") or []) for e in _selected_epics)
    _n_tasks_sel = sum(
        len(s.get("tasks") or [])
        for e in _selected_epics for s in (e.get("stories") or [])
    )

    # Summary banner
    st.markdown(
        f'<div style="padding:0.7rem 1rem;background:var(--bg-elev-1);border:1px solid var(--border);'
        f'border-left:3px solid var(--accent);border-radius:8px;margin:0.8rem 0;">'
        f'<div style="font-size:0.62rem;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;'
        f'color:var(--accent);margin-bottom:0.4rem;">Ready to publish</div>'
        f'<div style="font-size:0.85rem;display:grid;grid-template-columns:1fr 1fr;gap:0.3rem 1.2rem;">'
        f'<span>📦 <strong>{_n_epics_sel}</strong> epic(s)</span>'
        f'<span>📝 <strong>{_n_stories_sel}</strong> story(ies)</span>'
        f'<span>✅ <strong>{_n_tasks_sel}</strong> sub-task(s)</span>'
        f'<span>⚠ <strong>{_n_conflicts}</strong> conflict(s)</span>'
        f'<span>🔍 <strong>{_n_gaps}</strong> gap(s)</span>'
        f'<span style="color:{"var(--rose)" if _guardrail_errors else "var(--text-muted)"};">'
        f'🛡 <strong>{_guardrail_errors}</strong> guardrail error(s)</span>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    _subs = st.checkbox("Also create sub-tasks", value=True, key="jira_dlg_subtasks")

    if _n_stories_sel == 0:
        st.warning("Select at least one story to enable publishing.")

    st.markdown(
        f'<div style="padding:0.5rem 0.8rem;background:rgba(251,113,133,.08);'
        f'border:1px solid rgba(251,113,133,.3);border-radius:6px;margin:0.5rem 0;font-size:0.82rem;">'
        f'⚠ This will create <strong>{_n_epics_sel} epic(s)</strong>, '
        f'<strong>{_n_stories_sel} story(ies)</strong>, and up to '
        f'<strong>{_n_tasks_sel} sub-task(s)</strong> as <em>real issues</em> in '
        f'<strong>{_esc(_proj)}</strong>. This action cannot be automatically undone.</div>',
        unsafe_allow_html=True,
    )

    # Mandatory confirmation checkbox
    _confirmed = st.checkbox(
        f"I confirm: create {_n_epics_sel} epic(s), {_n_stories_sel} story(ies), "
        f"up to {_n_tasks_sel} sub-task(s) in **{_proj}**",
        value=False,
        key="jira_dlg_confirm",
    )

    if st.button(
        f"⤴  Create in Jira ({_proj})",
        type="primary",
        use_container_width=True,
        key="jira_dlg_go",
        disabled=(not _confirmed or _n_stories_sel == 0),
    ):
        _publish_res = {**res, "epics": _selected_epics}
        with st.spinner(f"Creating issues in {_proj}…"):
            try:
                from tools.jira_tool import JiraTool
                st.session_state["jira_publish_result"] = JiraTool(mode="live").publish_synthesis(
                    _publish_res, create_subtasks=_subs)
            except Exception as e:  # noqa: BLE001
                st.session_state["jira_publish_result"] = {"error": str(e)}

    if not _confirmed:
        st.caption("Tick the confirmation checkbox above to enable the Create button.")

    _pub = st.session_state.get("jira_publish_result")
    if _pub:
        if _pub.get("error"):
            st.error(f"Jira publish failed: {_pub['error']}")
        else:
            _c = _pub["counts"]
            st.success(f"Created {_c['epics']} epic(s), {_c['stories']} story(ies), "
                       f"{_c['subtasks']} sub-task(s) in {_pub['project']}.")
            for _it in _pub["created"]:
                if _it["level"] in ("epic", "story"):
                    _pad = "" if _it["level"] == "epic" else "&nbsp;&nbsp;&nbsp;&nbsp;↳ "
                    st.markdown(f'{_pad}<a href="{_it["url"]}" target="_blank">{_it["key"]}</a> — {_it["summary"]}',
                                unsafe_allow_html=True)

            # ── Two-way sync: read back current Jira status ───────────────────
            st.divider()
            if st.button("🔄  Sync status from Jira", key="jira_sync_btn",
                         use_container_width=True,
                         help="Read back current status, assignee and priority from live Jira"):
                with st.spinner("Fetching current status from Jira…"):
                    try:
                        from tools.jira_tool import JiraTool as _JT2
                        _sync_statuses = _JT2(mode="live").sync_published_stories(_pub)
                        st.session_state["jira_sync_statuses"] = _sync_statuses
                    except Exception as _se:
                        st.error(f"Sync failed: {_se}")

            _sync = st.session_state.get("jira_sync_statuses")
            if _sync:
                st.markdown("**Current Jira status:**")
                _status_colors = {
                    "To Do": "#64748b", "In Progress": "#f59e0b",
                    "Done": "#22c55e", "Closed": "#22c55e",
                    "In Review": "#8b5cf6", "Blocked": "#ef4444",
                }
                for _s in _sync:
                    _sc = _status_colors.get(_s["status"], "#94a3b8")
                    _assignee = _s["assignee"] or "Unassigned"
                    st.markdown(
                        f'<div style="display:flex;align-items:center;justify-content:space-between;'
                        f'padding:6px 10px;background:var(--bg-elev-1);border-radius:6px;'
                        f'margin-bottom:4px;font-size:0.8rem;">'
                        f'<span><a href="{_s["url"]}" target="_blank" style="color:var(--accent);'
                        f'text-decoration:none;font-weight:600;">{_esc(_s["key"])}</a>'
                        f' &nbsp;<span style="color:var(--text-muted);">{_esc(_s["summary"][:50])}</span></span>'
                        f'<span style="display:flex;gap:8px;align-items:center;">'
                        f'<span style="font-size:0.68rem;color:{_sc};font-weight:700;'
                        f'background:{_sc}22;padding:2px 8px;border-radius:10px;">{_esc(_s["status"])}</span>'
                        f'<span style="color:var(--text-faint);font-size:0.72rem;">{_esc(_assignee)}</span>'
                        f'</span></div>',
                        unsafe_allow_html=True,
                    )


if st.session_state.pop("_trigger_jira", False):
    show_jira_dialog()


# ---- Header + adaptive top-right nav ----
_result_exists = bool(st.session_state.get("result"))
_hdr_left, _hdr_right = st.columns(([5, 5] if _result_exists else [6, 3]),
                                   vertical_alignment="center")
with _hdr_left:
    st.markdown(
        '<div class="rev-bar"></div>'
        '<div class="app-header">'
        '<span class="app-icon">⚙️</span>'
        '<div class="app-title-block">'
        '<div class="app-title">Synthesize epics, stories &amp; tasks</div>'
        '<div class="app-tagline">'
        "🏭 OEM manufacturing backlog &nbsp;·&nbsp; ⚡ PartnerPortal &amp; FirmwareVault domain "
        "&nbsp;·&nbsp; 🛡️ IEC 62443 &amp; AS9100 guardrails &nbsp;·&nbsp; ~30-second multi-agent pass"
        "</div></div>"
        f'<div class="app-client-chip">⚙️ {CLIENT_NAME}</div>'
        "</div>",
        unsafe_allow_html=True,
    )
with _hdr_right:
    _navs = [("home", "⌂ Home"), ("history", "⌕ History"), ("help", "❓ Help")]
    if _result_exists:
        _navs += [("export", "↓ Export"), ("jira", "⤴ Jira")]
    _nav_cols = st.columns(len(_navs))
    _nav_clicked: dict[str, bool] = {}
    _primary_nav = {"jira", "export"}
    for _col, (_key, _label) in zip(_nav_cols, _navs):
        with _col:
            _nav_clicked[_key] = st.button(
                _label, key=f"nav_{_key}",
                use_container_width=True,
                type="primary" if _key in _primary_nav else "secondary",
            )

if _nav_clicked.get("home"):
    for _k in ("result", "run_dir", "jira_publish_result"):
        st.session_state[_k] = None
    st.rerun()
if _nav_clicked.get("history"):
    show_run_history_dialog()
if _nav_clicked.get("help"):
    show_how_it_works_dialog()
if _nav_clicked.get("export"):
    show_export_dialog()
if _nav_clicked.get("jira"):
    show_jira_dialog()

_pipeline_placeholder = st.empty()
_progress_placeholder = st.empty()

with _pipeline_placeholder.container():
    # Always use the CURRENT sidebar selection (st.session_state.models) for the
    # pre-run pipeline cards so per-stage overrides are reflected immediately.
    # Only use result["models"] AFTER a run to show what was actually used —
    # but even then, show the current selection if it has changed since the run.
    _last_run_models = (st.session_state.get("result") or {}).get("models") or {}
    _current_models  = dict(st.session_state.get("models") or {})
    _display_models  = _current_models if _current_models else _last_run_models
    _render_pipeline(
        stage_states=st.session_state.get("stage_states"),
        model=st.session_state.get("model_used") or None,
        token_usage=st.session_state.get("token_usage") or None,
        models_per_stage=_display_models,
    )


# -------------------------------------------------------- run handler

def _as_upload_list(uploaded) -> list:
    """Normalise the uploader return (None / single / list) to a clean list."""
    if uploaded is None:
        return []
    if isinstance(uploaded, list):
        return [u for u in uploaded if u is not None]
    return [uploaded]


def _read_one_text(uploaded) -> str:
    name = uploaded.name
    raw_bytes = uploaded.getvalue()

    if len(raw_bytes) > _MAX_UPLOAD_BYTES:
        raise InputError(
            f"**{name}** is {len(raw_bytes) // 1024} KB — "
            f"maximum allowed is {_MAX_UPLOAD_BYTES // 1024} KB. "
            "Set the `MAX_UPLOAD_BYTES` environment variable to increase the limit."
        )

    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        tmp = ROOT / "logs" / f"_upload_{int(time.time() * 1000)}_{name}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(raw_bytes)
        try:
            text = load_text(str(tmp))
        finally:
            tmp.unlink(missing_ok=True)
    else:
        text = raw_bytes.decode("utf-8", errors="replace")

    # Warn on injection patterns detected in uploaded content.
    # InputSanitizer is the single source of truth for all injection rules.
    # We scan here for an early UI warning; the pipeline re-scans and redacts
    # in initialize_node before any LLM stage sees the text.
    from security import InputSanitizer as _InputSanitizer
    _, _upload_findings = _InputSanitizer.scan(text, source=name)
    if _upload_findings:
        st.warning(
            f"⚠️ **Possible prompt injection detected** in **{name}** "
            f"({len(_upload_findings)} pattern(s): "
            f"{', '.join(f.code for f in _upload_findings[:3])}). "
            "The pipeline will redact injections before any LLM stage sees them."
        )

    return text


def _read_uploaded_text(uploaded) -> str:
    """Read one or more uploaded text/pdf files into a single string.

    Multiple files are concatenated with a labelled separator so the Parser
    sees one combined source while still being able to tell the documents
    apart (e.g. several meeting transcripts, or a transcript + a Slack export)."""
    files = _as_upload_list(uploaded)
    if not files:
        return ""
    if len(files) == 1:
        return _read_one_text(files[0])
    parts = [f"===== {f.name} =====\n{_read_one_text(f)}" for f in files]
    return "\n\n".join(parts)


def _read_uploaded_tickets(uploaded) -> list[dict]:
    """Read and MERGE tickets from one or more uploaded JSON backlog files.

    Each file may be a list of tickets or a `{"items": [...]}` wrapper.
    All tickets across files are concatenated into one backlog."""
    merged: list[dict] = []
    for f in _as_upload_list(uploaded):
        raw_bytes = f.getvalue()
        if len(raw_bytes) > _MAX_UPLOAD_BYTES:
            raise InputError(
                f"**{f.name}** is {len(raw_bytes) // 1024} KB — "
                f"maximum allowed is {_MAX_UPLOAD_BYTES // 1024} KB."
            )
        raw = raw_bytes.decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise InputError(f"Backlog JSON parse error in {f.name}: {e}") from e
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            data = data["items"]
        if not isinstance(data, list):
            raise InputError(f"Backlog JSON in {f.name} must be a list of tickets (or an {{\"items\": [...]}} object).")
        merged.extend(data)
    return merged


def _resolve_text(selected, options: dict, uploaded):
    """Combine all selected sample docs + any uploaded files into one text
    source. Returns (combined_text, [source_names]). Multiple sources are
    concatenated with a labelled separator so the Parser can still tell them
    apart; a single source is returned as-is."""
    pairs: list[tuple[str, str]] = []  # (name, text)
    for lbl in (selected or []):
        val = options.get(lbl)
        if val and val != "__upload__":
            pairs.append((Path(str(val)).name, load_text(str(val))))
    for f in _as_upload_list(uploaded):
        pairs.append((f.name, _read_one_text(f)))
    if not pairs:
        return "", []
    if len(pairs) == 1:
        return pairs[0][1], [pairs[0][0]]
    combined = "\n\n".join(f"===== {n} =====\n{t}" for n, t in pairs)
    return combined, [n for n, _ in pairs]


def _resolve_tickets(selected, options: dict, uploaded) -> list[dict]:
    """Merge tickets from all selected sample backlogs + uploaded JSON files."""
    merged: list[dict] = []
    for lbl in (selected or []):
        val = options.get(lbl)
        if val and val != "__upload__":
            merged.extend(load_tickets(str(val)))
    merged.extend(_read_uploaded_tickets(uploaded))
    return merged


# The sidebar Synthesize button and the home-screen ANALYZE button both
# trigger the same pipeline. The latter sets `_pending_run` and reruns
# (because the button isn't bound at script-init time), so we consume
# the flag here and clear it before invoking the pipeline.
_main_canvas_run = bool(st.session_state.pop("_pending_run", False))

if run_clicked or _main_canvas_run:
    # ---- Resolve inputs ----
    # Each picker is multi-select: combine every chosen sample (+ uploads)
    # into one source. Transcripts/wikis are concatenated; backlogs merged.
    try:
        transcript_text, _t_names = _resolve_text(
            transcript_choice, TRANSCRIPT_OPTIONS, transcript_upload)
        if not _t_names:
            source_label = "(uploaded)"
        elif len(_t_names) == 1:
            source_label = _t_names[0]
        else:
            source_label = (
                f"{len(_t_names)} sources: " + ", ".join(_t_names[:3])
                + ("…" if len(_t_names) > 3 else "")
            )

        constraint_text, _ = _resolve_text(
            constraints_choice, CONSTRAINTS_OPTIONS, constraints_upload)

        existing_tickets = _resolve_tickets(
            backlog_choice, BACKLOG_OPTIONS, backlog_upload)
    except InputError as e:
        st.error(f"Could not load inputs: {e}")
        st.stop()

    # ---- Idempotency: block exact duplicate within 60 s ----
    # Hashes the inputs so that a double-click or browser back/forward that
    # replays the same form submission does not kick off a second full run.
    _run_sig = hashlib.sha256(
        f"{transcript_text}|{constraint_text}|"
        f"{sorted((st.session_state.get('models') or {}).items())}".encode()
    ).hexdigest()[:12]
    _last_sig = st.session_state.get("_last_run_sig")
    _last_run_at = float(st.session_state.get("_last_run_at", 0))
    if _run_sig == _last_sig and time.time() - _last_run_at < 60:
        st.warning(
            "This exact input was already synthesized less than 60 seconds ago. "
            "If you want to re-run, please wait a moment or change your inputs."
        )
        st.stop()
    st.session_state["_last_run_sig"] = _run_sig
    st.session_state["_last_run_at"] = time.time()

    # ---- Per-user request rate limit gate ----
    _rate_allowed, _rate_reason = check_rate_limit(
        _current_user, MAX_SYNTHESES_PER_HOUR, MAX_SYNTHESES_PER_DAY
    )
    if not _rate_allowed:
        st.error(f"**Rate limit reached.** {_rate_reason}")
        st.stop()

    # ---- Per-user daily budget gate (atomic reserve) ----
    # try_reserve atomically checks AND pre-charges the estimated cost so two
    # concurrent requests from the same user cannot both pass the gate.
    # settle_reservation corrects for the actual cost after the run.
    _pre_run_estimated_cost, _, _ = _estimate_pre_run_cost(
        transcript_choice=transcript_choice,
        transcript_upload=transcript_upload,
        constraints_choice=constraints_choice,
        constraints_upload=constraints_upload,
        backlog_choice=backlog_choice,
        backlog_upload=backlog_upload,
        models=dict(st.session_state.get("models") or {}),
        TRANSCRIPT_OPTIONS=TRANSCRIPT_OPTIONS,
        CONSTRAINTS_OPTIONS=CONSTRAINTS_OPTIONS,
        BACKLOG_OPTIONS=BACKLOG_OPTIONS,
    )
    _budget_approved = True
    if DAILY_BUDGET_USD > 0:
        _budget_approved, _reserved_spend = try_reserve(
            _current_user, _pre_run_estimated_cost, DAILY_BUDGET_USD
        )
        if not _budget_approved:
            _today_spend = get_today_spend(_current_user)
            st.error(
                f"**Daily budget cap reached.** "
                f"You have spent ${_today_spend:.4f} today against your "
                f"${DAILY_BUDGET_USD:.2f} daily limit. "
                "Ask your admin to raise `DAILY_BUDGET_USD` or try again tomorrow."
            )
            st.stop()
        elif _reserved_spend >= 0.8 * DAILY_BUDGET_USD:
            st.warning(
                f"You have used ${_reserved_spend:.4f} of your "
                f"${DAILY_BUDGET_USD:.2f} daily budget "
                f"({100 * _reserved_spend / DAILY_BUDGET_USD:.0f}%). "
                "Approaching limit."
            )
    else:
        _reserved_spend = 0.0

    # ---- Input size pre-flight check ----
    # Mirrors the guard in initialize_node so the user gets instant feedback
    # rather than waiting for the background thread to start and fail.
    _MAX_INPUT_TOKENS = int(os.environ.get("MAX_INPUT_TOKENS_PER_RUN", "50000"))
    _est_transcript_tokens = len(transcript_text) // 4
    _est_constraint_tokens = len(constraint_text) // 4
    _est_total_tokens = _est_transcript_tokens + _est_constraint_tokens
    if _est_total_tokens > _MAX_INPUT_TOKENS:
        st.error(
            f"**Input too large.** "
            f"Estimated input size ({_est_total_tokens:,} tokens) exceeds the "
            f"`MAX_INPUT_TOKENS_PER_RUN` limit of {_MAX_INPUT_TOKENS:,} tokens "
            f"(transcript ≈ {_est_transcript_tokens:,}, constraints ≈ {_est_constraint_tokens:,}). "
            "Shorten your transcript/wiki or ask your admin to raise `MAX_INPUT_TOKENS_PER_RUN`."
        )
        if DAILY_BUDGET_USD > 0:
            settle_reservation(_current_user, 0.0, _pre_run_estimated_cost)
        st.stop()

    # ---- Process-level concurrency guard ----
    # Allow up to _MAX_CONCURRENT_SYNTHESES runs simultaneously. Beyond that,
    # tell the user to wait rather than queuing silently (which would hide
    # the multi-minute wait time behind a spinner with no ETA).
    if not _SYNTHESIS_SEMAPHORE.acquire(blocking=False):
        st.warning(
            f"All {_MAX_CONCURRENT_SYNTHESES} synthesis slot(s) are currently in use. "
            "Please wait a moment and try again, or ask your admin to increase "
            "`MAX_CONCURRENT_SYNTHESES`."
        )
        st.stop()

    # ---- Live-run branch ----
    st.session_state.dry_run_result = None
    st.session_state.model_used = ""
    st.session_state.token_usage = {}

    record_synthesis_start()
    t0 = time.perf_counter()
    stage_states = ["idle"] * len(_STAGES)
    with _pipeline_placeholder.container():
        _render_pipeline(stage_states=stage_states)
    _progress_placeholder.markdown(
        '<div class="progress-status"><strong>BOOT</strong>'
        'Initializing orchestrator…</div>',
        unsafe_allow_html=True,
    )

    # Cancel support — a threading.Event lets the progress callback signal
    # the run thread to abort cleanly between stages.
    _cancel_event = threading.Event()

    try:
        orch = Orchestrator()
    except Exception as e:
        _progress_placeholder.error(f"Orchestrator init failed: {e}")
        st.stop()

    # Per-stage start timestamps so completed/failed events can report
    # how long the stage actually took. Reset on every pipeline run.
    stage_started_at: dict[int, float] = {}
    # Running log of every agent event. We APPEND to this (rather than
    # overwriting the placeholder per event) so each agent's lines stay
    # visible as the next stage runs.
    progress_log: list[str] = []

    # Data source info is shown inline in each stage that actually fetches data
    # (Constraint Extractor for Confluence, Gap Detector for Jira + GitHub).
    # No pre-pipeline "Data sources" banner — only show it when it's used.
    # Track failovers / failures so we can show an end-of-run summary, a toast,
    # and a persistent badge — nothing changes provider silently.
    _events_seen = {"failover": [], "failed": []}

    def _render_log():
        _progress_placeholder.markdown(
            '<div class="progress-log">' + "".join(progress_log) + "</div>",
            unsafe_allow_html=True,
        )

    def _on_progress(stage_index: int, stage_name: str, event: str, detail: str):
        now = time.perf_counter()
        if event == "started":
            stage_states[stage_index] = "active"
            stage_started_at[stage_index] = now
        elif event == "completed":
            stage_states[stage_index] = "done"
        elif event == "failed":
            stage_states[stage_index] = "failed"
        elif event == "skipped":
            stage_states[stage_index] = "skipped"
        elif event == "failover":
            stage_states[stage_index] = "active"  # still working, just on the other provider

        pretty_name = STAGE_DISPLAY_NAMES.get(stage_name, stage_name.replace("_", " ").title())
        if event == "failover":
            _events_seen["failover"].append(pretty_name)
        elif event == "failed":
            _events_seen["failed"].append(pretty_name)

        # Build an "elapsed" suffix once the stage finishes so reviewers
        # can see which agent dominates wall time.
        elapsed_suffix = ""
        if event in ("completed", "failed") and stage_index in stage_started_at:
            secs = now - stage_started_at[stage_index]
            elapsed_suffix = f" · {secs:.1f}s"

        st.session_state["current_stage"] = stage_index
        icon = {"started": "▸", "completed": "✓", "failed": "✗",
                "skipped": "–", "failover": "⚠"}.get(event, "·")
        evt_label = "FAILOVER" if event == "failover" else _esc(event)
        entry = (
            f'<div class="log-line log-{_esc(event)}">'
            f'<span class="log-icon">{icon}</span>'
            f'<strong>{_esc(pretty_name)}</strong> '
            f'<span class="log-evt">{evt_label}</span>'
            f'{(" · " + _esc(detail)) if detail else ""}{elapsed_suffix}</div>'
        )
        progress_log.append(entry)
        # NOTE: no UI calls here — the main thread polls and renders every
        # 300 ms via the loop below. Calling st.* from a background thread
        # works inconsistently across Streamlit versions; the polling loop
        # is the reliable approach that actually live-streams to the browser.

        # Check for user-initiated cancel between stages. Only interrupt on
        # "completed" or "skipped" events so we never cut a stage mid-call.
        if event in ("completed", "skipped") and _cancel_event.is_set():
            raise _PipelineCancelled("Run cancelled by user.")

    # First-run model download — sentence-transformers downloads ~80MB on
    # first use. Pre-warm the embedding tool inside a spinner so the user
    # sees what's happening instead of an unexplained pause partway through
    # the Gap Detector. Subsequent runs hit the cache and this is a no-op.
    if existing_tickets and not st.session_state.get("_embeddings_warmed"):
        try:
            with st.spinner("Loading embedding model… (~80MB, one-time download)"):
                from tools.embedding_tool import EmbeddingTool  # local import
                EmbeddingTool().encode(["warmup"])
            st.session_state._embeddings_warmed = True
        except Exception as e:  # noqa: BLE001 — don't block the run on warmup failure
            # Not fatal: the InsightScannerAgent will fall back to LLM dedup.
            st.warning(f"Embedding warmup skipped: {e}")

    # When live Atlassian sources are toggled on, blank out whatever the
    # file-based selectors loaded so the orchestrator's live-fetch path
    # owns those inputs. Both toggles surface a sidebar warning + audit
    # event if the live fetch fails, so the user can tell that they're
    # not silently falling back.
    _live_conf_pid = st.session_state.get("live_confluence_page_id", "").strip() \
        if st.session_state.get("use_live_confluence") else ""
    _use_live_jira = bool(st.session_state.get("use_live_jira"))
    if _live_conf_pid:
        constraint_text = ""
    if _use_live_jira:
        existing_tickets = []

    # Build vision attachments from any sidebar image uploads. Errors
    # while reading bytes are surfaced inline; the run still proceeds
    # without the image rather than failing.
    _vision_atts = None
    _vision_files = st.session_state.get("vision_uploads") or []
    _vision_sample_labels = st.session_state.get("vision_samples") or []
    if _vision_files or _vision_sample_labels:
        try:
            from tools.base import VisionAttachment
            _vision_atts = []
            # Bundled sample images selected directly from the dropdown.
            for _lbl in _vision_sample_labels:
                _p = VISION_SAMPLE_OPTIONS.get(_lbl)
                if _p:
                    _vision_atts.append(VisionAttachment.from_path(_p))
            # Plus any user uploads.
            for f in _vision_files:
                _vision_atts.append(
                    VisionAttachment.from_bytes(
                        f.getvalue(),
                        media_type=getattr(f, "type", "image/png"),
                        label=getattr(f, "name", "upload"),
                    )
                )
            if not _vision_atts:
                _vision_atts = None
        except Exception as e:  # noqa: BLE001
            st.warning(f"Skipping vision attachments: {e}")
            _vision_atts = None

    # Capture all session-state values NOW (main thread) before starting
    # the background thread. st.session_state is NOT thread-safe.
    _thread_models = dict(st.session_state.get("models") or {})

    # Thread the pipeline so the Cancel button stays responsive. The run
    # executes in a daemon thread; the main thread polls a result queue.
    # _PipelineCancelled raised in the progress callback propagates out of
    # orch.run() and is caught in the thread, put on the queue as an error.
    _result_q: _queue.Queue = _queue.Queue()

    def _run_pipeline():
        try:
            r = orch.run(
                transcript_text=transcript_text,
                constraint_text=constraint_text,
                existing_tickets=existing_tickets,
                progress_callback=_on_progress,
                models=_thread_models,
                live_confluence_page_id=_live_conf_pid or None,
                live_jira=_use_live_jira,
                vision_attachments=_vision_atts,
                user_email=_current_user,
                run_metadata={
                    "user_id":      _current_user,
                    "role":         _current_role,
                    "preset":       st.session_state.get("active_preset", "unknown"),
                    "source_label": source_label,
                    "auth_disabled": True,
                },
            )
            _result_q.put(("ok", r))
        except _PipelineCancelled:
            _result_q.put(("cancelled", None))
        except Exception as exc:  # noqa: BLE001
            _result_q.put(("error", exc))

    # Cancel button — visible during the run above the progress log.
    # Graceful cancel: sets _cancel_event which the progress callback checks
    # between stages. The run thread raises _PipelineCancelled on the next
    # completed/skipped event so the current stage always finishes cleanly.
    _cancel_col1, _cancel_col2 = st.columns([3, 1])
    with _cancel_col2:
        _cancel_placeholder = st.empty()
        if _cancel_placeholder.button(
            "✕  Cancel run",
            key="cancel_run_btn",
            use_container_width=True,
            type="secondary",
            help="Stops the pipeline between stages. Results up to this point are preserved.",
        ):
            _cancel_event.set()

    _thread = threading.Thread(target=_run_pipeline, daemon=True)
    _thread.start()

    # Live-stream the progress log to the browser.
    # _thread.join() was used before but it blocks the main Streamlit thread,
    # preventing the browser from receiving any WebSocket updates until the
    # entire run finishes. The polling loop below lets the main thread render
    # every 300 ms so each stage appears as it completes.
    _poll_deadline = t0 + _SYNTHESIS_TIMEOUT  # absolute deadline for auto-cancel
    while _thread.is_alive():
        # Graceful shutdown: entrypoint.sh writes this flag when SIGTERM arrives.
        # Setting _cancel_event lets the current LLM stage finish before stopping.
        if _SHUTDOWN_FLAG.exists():
            _cancel_event.set()
        # Auto-cancel if synthesis exceeds the configured wall-clock timeout.
        # This also handles the browser-disconnect case: once the session's
        # WebSocket is gone the main thread keeps running this loop, and the
        # deadline ensures we don't burn API credits indefinitely.
        if not _cancel_event.is_set() and time.perf_counter() > _poll_deadline:
            _cancel_event.set()
        with _pipeline_placeholder.container():
            _render_pipeline(
                stage_states=list(stage_states),  # snapshot to avoid race
                model=st.session_state.get("model_used") or None,
                token_usage=None,
                models_per_stage=_thread_models,
            )
        _render_log()
        time.sleep(0.3)

    _thread.join()  # ensure thread is fully done before reading results
    _cancel_placeholder.empty()  # remove cancel button once run finishes

    _status, _payload = _result_q.get()
    if _status == "cancelled":
        _SYNTHESIS_SEMAPHORE.release()
        record_synthesis_end("cancelled", time.perf_counter() - t0)
        # Refund the full budget reservation — run produced nothing billable.
        settle_reservation(_current_user, 0.0, _pre_run_estimated_cost)
        progress_log.append(
            '<div class="log-line log-failed"><span class="log-icon">✕</span>'
            '<strong>Run cancelled by user</strong></div>'
        )
        _render_log()
        st.warning("Run cancelled — partial results (if any) were not saved.")
        st.stop()
    elif _status == "error":
        _SYNTHESIS_SEMAPHORE.release()
        record_synthesis_end("failure", time.perf_counter() - t0)
        # Refund the full budget reservation — run failed before completing.
        settle_reservation(_current_user, 0.0, _pre_run_estimated_cost)
        _progress_placeholder.error(f"Pipeline failed: {_payload}")
        st.stop()

    result = _payload
    elapsed = time.perf_counter() - t0
    n_done = sum(1 for s in stage_states if s == "done")
    n_failed = sum(1 for s in stage_states if s == "failed")
    n_skipped = sum(1 for s in stage_states if s == "skipped")
    summary_tag = (
        f'<strong>DONE</strong>{n_done}/{len(_STAGES)} agents completed'
        + (f' · {n_failed} failed' if n_failed else '')
        + (f' · {n_skipped} skipped' if n_skipped else '')
        + f' · {elapsed:.1f}s'
    )
    with _pipeline_placeholder.container():
        _render_pipeline(
            stage_states=stage_states,
            model=result.get("model"),
            token_usage=result.get("token_usage"),
            models_per_stage=result.get("models") or st.session_state.models,
        )
    progress_log.append(f'<div class="log-line log-done"><span class="log-icon">✓</span>{summary_tag}</div>')

    # ---- Failover / failure summary (so nothing is missed) ----
    _fo = _events_seen["failover"]
    _fl = _events_seen["failed"]
    st.session_state["failover_count"] = len(_fo)
    st.session_state["failed_count"] = len(_fl)
    if _fo:
        progress_log.append(
            '<div class="log-line log-failover"><span class="log-icon">⚠</span>'
            f'<strong>Provider failover</strong> · {len(_fo)} stage(s) switched provider: '
            f'{_esc(", ".join(_fo))}</div>'
        )
    if _fl:
        progress_log.append(
            '<div class="log-line log-failed"><span class="log-icon">✗</span>'
            f'<strong>Failed</strong> · {len(_fl)} stage(s): {_esc(", ".join(_fl))}</div>'
        )
    _render_log()
    try:
        if _fl:
            st.toast(f"⚠ {len(_fl)} stage(s) failed: {', '.join(_fl)}", icon="⚠️")
        elif _fo:
            st.toast(f"⚠ {len(_fo)} stage(s) failed over to the other provider", icon="⚠️")
    except Exception:  # noqa: BLE001 — toast is best-effort
        pass

    # ---- Persist outputs ----
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Scope outputs to the current user — outputs/<user_id>/<timestamp>/
    _safe_uid = "".join(c if c.isalnum() or c in "-_." else "_" for c in (_current_user or "anonymous"))
    run_dir = OUTPUTS_DIR / _safe_uid / stamp
    # `result` from the orchestrator now includes `token_usage` and `model`.
    # write_outputs reads the synthesis content fields; the extras are
    # carried through to the JSON dump as well — useful downstream.
    synth_payload = {k: v for k, v in result.items() if k != "audit_trail"}
    json_path, md_path = write_outputs(synth_payload, run_dir, source_label=source_label)
    audit_path = run_dir / "audit_trail.md"
    audit_path.write_text(result["audit_trail"], encoding="utf-8")

    # ---- Token tally ----
    token_usage = result.get("token_usage") or {}
    total = token_usage.get("total") or {"input": 0, "output": 0}
    tokens_total = int(total.get("input", 0)) + int(total.get("output", 0))
    model_name = result.get("model") or ""
    cost_usd = _compute_total_cost(token_usage, result.get("models") or {})
    record_synthesis_end("success", elapsed, cost_usd, token_usage, model_name)
    # Settle the budget reservation: charge actual cost, refund unused estimate.
    # This replaces the old record_spend() call and closes the concurrent-user
    # race window where two users both passed the budget gate before either run
    # had recorded its spend.
    settle_reservation(_current_user, cost_usd, _pre_run_estimated_cost)
    increment_request_count(_current_user)

    st.session_state.result = result
    st.session_state.run_dir = run_dir
    st.session_state.elapsed = elapsed
    st.session_state.source_label = source_label
    st.session_state.stage_states = stage_states
    st.session_state.tokens_total = tokens_total
    st.session_state.cost_usd = cost_usd
    st.session_state.token_usage = token_usage
    st.session_state.model_used = model_name
    st.session_state.existing_tickets_cache = existing_tickets
    st.session_state.epics_original = json.loads(json.dumps(result.get("epics") or []))
    st.session_state.stories_edit_mode = False
    st.session_state.dry_run_result = None

    # ---- Append to persisted run history ----
    epics = result.get("epics") or []
    n_stories = sum(len(e.get("stories") or []) for e in epics)
    history_summary = {
        "run_id": f"{stamp}_{uuid.uuid4().hex[:6]}",
        "timestamp": stamp,
        "user_id": _current_user,
        "source_label": source_label,
        "elapsed_seconds": elapsed,
        "epic_count": len(epics),
        "story_count": n_stories,
        "dup_count": len(result.get("duplicates") or []),
        "gap_count": len(result.get("gaps") or []),
        "conflict_count": len(result.get("conflicts") or []),
        "model": model_name,
        "models": result.get("models") or {},
        "token_usage": token_usage,
        "cost_usd": cost_usd,
        "outputs": {
            "synthesis_json": str(json_path),
            "synthesis_md": str(md_path),
            "audit_md": str(audit_path),
        },
    }
    _save_run_to_disk(history_summary)
    _SYNTHESIS_SEMAPHORE.release()


# -------------------------------------------------------- results / empty state

result = st.session_state.result

if result is None:
    # ---- Empty state ----
    # Home-screen explainer ported from UI-smart-backlog-assistant. Unlike
    # the previous "Selected inputs" block, this view is purely
    # instructional — it doesn't echo whichever preset is currently
    # selected in the sidebar, so the home page reads as a clean landing
    # surface rather than a dashboard. The user picks inputs in the
    # sidebar; the CTA on the main canvas mirrors the sidebar Synthesize
    # button.
    st.html("""
        <div class="ap-hero">
            <div class="ap-eyebrow">Backlog Synthesizer &middot; AI Pipeline</div>
            <div class="ap-title">Five agents. One structured backlog.</div>
            <div class="ap-sub">
                Feed in a transcript, a wiki, and an existing ticket backlog.
                Each agent does one job and hands off to the next.
                The result: <strong>epics &rarr; stories &rarr; tasks</strong>,
                every gap flagged, every decision audited.
            </div>

            <div class="ap-flow">

                <div class="ap-card">
                    <div class="ap-num">01</div>
                    <span class="ap-icon">&#128269;</span>
                    <div class="ap-name">Discovery Engine</div>
                    <div class="ap-tag">Reads the transcript and surfaces every distinct topic, actor, and requirement</div>
                    <div class="ap-outputs">
                        <span class="ap-badge">Topics</span>
                        <span class="ap-badge">Quotes</span>
                        <span class="ap-badge">Summary</span>
                    </div>
                </div>

                <div class="ap-arrow"></div>

                <div class="ap-card">
                    <div class="ap-num">02</div>
                    <span class="ap-icon">&#128203;</span>
                    <div class="ap-name">Policy Engine Agent</div>
                    <div class="ap-tag">Extracts must / must-not rules and compliance constraints from the architecture wiki</div>
                    <div class="ap-outputs">
                        <span class="ap-badge">Rules</span>
                        <span class="ap-badge">Constraints</span>
                    </div>
                </div>

                <div class="ap-arrow"></div>

                <div class="ap-card">
                    <div class="ap-num">03</div>
                    <span class="ap-icon">&#9997;</span>
                    <div class="ap-name">Story Generation Agent</div>
                    <div class="ap-tag">Drafts a Given / When / Then user story with acceptance criteria and priority for each topic</div>
                    <div class="ap-outputs">
                        <span class="ap-badge">Stories</span>
                        <span class="ap-badge">AC</span>
                        <span class="ap-badge">Priority</span>
                    </div>
                </div>

                <div class="ap-arrow"></div>

                <div class="ap-card">
                    <div class="ap-num">04</div>
                    <span class="ap-icon">&#128230;</span>
                    <div class="ap-name">Delivery Planner Agent</div>
                    <div class="ap-tag">Groups stories into themed epics and decomposes each into concrete implementation tasks</div>
                    <div class="ap-outputs">
                        <span class="ap-badge">Epics</span>
                        <span class="ap-badge">Tasks</span>
                    </div>
                </div>

                <div class="ap-arrow"></div>

                <div class="ap-card">
                    <div class="ap-num">05</div>
                    <span class="ap-icon">&#128300;</span>
                    <div class="ap-name">Insight Scanner Agent</div>
                    <div class="ap-tag">Embedding-based duplicate detection plus LLM reasoning to flag conflicts and backlog gaps</div>
                    <div class="ap-outputs">
                        <span class="ap-badge">Gaps</span>
                        <span class="ap-badge">Conflicts</span>
                        <span class="ap-badge">Duplicates</span>
                    </div>
                </div>

            </div>

            <div class="ap-io">
                <div class="ap-io-item">
                    <div class="ap-io-dot" style="background:#38bdf8;width:6px;height:6px;border-radius:50%;flex-shrink:0;"></div>
                    Transcript &middot; Wiki &middot; Backlog tickets
                </div>
                <div class="ap-io-item">
                    <div class="ap-io-dot" style="background:#f5c518;width:6px;height:6px;border-radius:50%;flex-shrink:0;"></div>
                    Epics &middot; Stories &middot; Tasks &middot; Gaps &middot; Conflicts &middot; Audit trail
                </div>
            </div>
        </div>
    """)

    # Primary action on the main canvas — large, centered, mirrors the
    # sidebar's Synthesize button. Placed below the explainer card so it's
    # the last thing the eye lands on before clicking.
    st.markdown("<div style='height:0.8rem'/>", unsafe_allow_html=True)
    _, _main_cta_col, _ = st.columns([1, 2, 1])
    with _main_cta_col:
        st.markdown('<div class="main-cta-wrap">', unsafe_allow_html=True)
        main_run_clicked = st.button(
            "⟶  SYNTHESIZE",
            key="main_synthesize_btn",
            use_container_width=True,
            disabled=not _transcript_ready,
        )
        if not _transcript_ready:
            st.caption("Pick a transcript source in the sidebar to enable synthesis.")
        st.markdown('</div>', unsafe_allow_html=True)
    if main_run_clicked:
        st.session_state["_pending_run"] = True
        st.rerun()

else:
    # ---- Run-meta strip ----
    elapsed = st.session_state.elapsed or 0
    tokens = st.session_state.tokens_total or 0
    cost = st.session_state.cost_usd or 0.0
    model = st.session_state.model_used or "—"
    cost_label = f"${cost:.4f}" if cost > 0 else "—"

    st.markdown(
        '<div class="run-meta">'
        f'<span class="run-meta-item"><span class="run-meta-icon">✦</span>'
        f'<span class="run-meta-label">Source</span>{_esc(st.session_state.source_label)}</span>'
        '<span class="run-meta-sep">·</span>'
        f'<span class="run-meta-item"><span class="run-meta-icon">⧗</span>'
        f'<span class="run-meta-label">Elapsed</span>{elapsed:.1f} s</span>'
        '<span class="run-meta-sep">·</span>'
        f'<span class="run-meta-item"><span class="run-meta-icon">⚙</span>'
        f'<span class="run-meta-label">Model</span>{_esc(model)}</span>'
        '<span class="run-meta-sep">·</span>'
        f'<span class="run-meta-item"><span class="run-meta-icon">⊕</span>'
        f'<span class="run-meta-label">Tokens</span>{tokens:,}</span>'
        '<span class="run-meta-sep">·</span>'
        f'<span class="run-meta-item"><span class="run-meta-icon">$</span>'
        f'<span class="run-meta-label">Cost</span>{cost_label}</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    _render_kpis(result)

    # Persistent failover / failure badge so it's visible even after the live
    # log scrolls away (the audit trail has the full detail).
    _fo_n = int(st.session_state.get("failover_count") or 0)
    _fl_n = int(st.session_state.get("failed_count") or 0)
    if _fo_n or _fl_n:
        _bits = []
        if _fl_n:
            _bits.append(f"✗ {_fl_n} stage(s) failed")
        if _fo_n:
            _bits.append(f"⚠ {_fo_n} stage(s) failed over to the other provider")
        st.warning(" · ".join(_bits) + " — see the **Audit trail** tab for details.")

    # ---- Guardrail findings strip ----
    # Non-blocking heuristic checks ran post-LLM. We surface a coloured
    # summary chip; the full list lives in a dedicated tab below.
    findings = result.get("guardrail_findings") or []
    if findings:
        n_err = sum(1 for f in findings if f.get("severity") == "error")
        n_warn = sum(1 for f in findings if f.get("severity") == "warn")
        n_info = sum(1 for f in findings if f.get("severity") == "info")
        if n_err:
            tone, accent = "error", "var(--rose)"
            verdict = f"{n_err} issue{'s' if n_err != 1 else ''} the synthesis should address"
        elif n_warn:
            tone, accent = "warn", "var(--amber)"
            verdict = f"{n_warn} warning{'s' if n_warn != 1 else ''} worth a quick scan"
        else:
            tone, accent = "info", "var(--accent)"
            verdict = f"{n_info} note{'s' if n_info != 1 else ''} for review"
        st.markdown(
            f'<div style="margin:0.4rem 0 0.8rem;padding:0.6rem 0.9rem;'
            f'background:var(--bg-elev-1);border:1px solid var(--border);'
            f'border-left:3px solid {accent};border-radius:8px;'
            f'font-size:0.82rem;color:var(--text-muted);">'
            f'<span style="font-size:0.62rem;font-weight:700;letter-spacing:0.14em;'
            f'text-transform:uppercase;color:{accent};margin-right:0.5rem;">'
            f'Guardrails · {tone}</span>{_esc(verdict)}'
            f' <span style="color:var(--text-faint);">— open the '
            f'<strong>Guardrails</strong> tab below for the full list.</span></div>',
            unsafe_allow_html=True,
        )

    # ---- "What's next" action row — each button is a real action ----
    epics_list = result.get("epics") or []
    n_stories = sum(len(e.get("stories") or []) for e in epics_list)
    dup_count = len(result.get("duplicates") or [])

    actions: list[tuple[str, str, str]] = []  # (key, label, button_type)
    if n_stories > 0:
        actions.append((
            "review",
            f"◇  Review {n_stories} stor{'y' if n_stories == 1 else 'ies'}",
            "secondary",
        ))
    if dup_count > 0:
        actions.append((
            "compare",
            f"⬢  Compare {dup_count} duplicate{'s' if dup_count != 1 else ''}",
            "primary",
        ))
    if n_stories > 0:
        actions.append(("edit", "✎  Edit stories", "secondary"))
    actions.append(("export", "↓  Export JSON / MD", "secondary"))
    # Jira push — most important CTA, shown as primary button when ready
    _jira_cta_ready = bool(
        _can_push_jira()
        and os.environ.get("JIRA_BASE_URL")
        and os.environ.get("JIRA_API_TOKEN")
        and os.environ.get("JIRA_PROJECT_KEY")
    )
    if _jira_cta_ready and n_stories > 0:
        actions.append((
            "push_jira",
            f"⤴  Push to Jira ({os.environ.get('JIRA_PROJECT_KEY')})",
            "primary",
        ))

    st.markdown(
        '<div class="next-strip-label-row">WHAT&rsquo;S NEXT</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="next-action-row">', unsafe_allow_html=True)
    cols = st.columns(len(actions))
    for i, (akey, label, btn_type) in enumerate(actions):
        with cols[i]:
            if st.button(
                label,
                key=f"next_action_{akey}",
                type=btn_type,
                use_container_width=True,
            ):
                if akey == "compare":
                    show_duplicate_compare_dialog()
                elif akey == "edit":
                    st.session_state.stories_edit_mode = True
                    st.toast("Edit mode on — open the Epics tab to edit", icon="✏️")
                elif akey == "review":
                    st.session_state.stories_edit_mode = False
                    st.toast("Stories are in the Epics tab below", icon="📋")
                elif akey == "export":
                    st.toast("Download buttons are inside each tab", icon="⬇️")
                elif akey == "push_jira":
                    show_jira_dialog()
    st.markdown('</div>', unsafe_allow_html=True)

    # ---- Cost / token panel (expander) ----
    # Per-stage models mean per-row models: each agent's row prices its
    # tokens at the rate of *its* stage model. The Total row sums those
    # per-agent costs rather than re-applying a single model rate.
    token_usage = st.session_state.token_usage or {}
    if token_usage:
        with st.expander("Cost & tokens", expanded=False):
            from pricing import is_free_tier_eligible  # local import
            models_per_stage = result.get("models") or {}
            rows = []
            row_total_cost = 0.0
            for agent_name, vals in token_usage.items():
                if agent_name == "total":
                    continue
                ai = int(vals.get("input", 0) or 0)
                ao = int(vals.get("output", 0) or 0)
                row_model = _model_for_agent(agent_name, models_per_stage)
                agent_cost = estimate_cost_usd(row_model, ai, ao) if row_model else None
                if agent_cost is not None:
                    row_total_cost += agent_cost
                tag = " (free tier)" if is_free_tier_eligible(row_model) else ""
                rows.append({
                    "agent": STAGE_DISPLAY_NAMES.get(agent_name, agent_name.replace("_", " ").title()),
                    "model": (row_model + tag) if row_model else "—",
                    "input_tokens": ai,
                    "output_tokens": ao,
                    "cost_usd": f"${agent_cost:.4f}" if agent_cost is not None else "—",
                })
            total = token_usage.get("total") or {"input": 0, "output": 0}
            rows.append({
                "agent": "Total",
                "model": "—",
                "input_tokens": int(total.get("input", 0)),
                "output_tokens": int(total.get("output", 0)),
                "cost_usd": f"${row_total_cost:.4f}",
            })
            st.dataframe(
                rows,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "agent": st.column_config.TextColumn("Agent"),
                    "model": st.column_config.TextColumn("Model"),
                    "input_tokens": st.column_config.NumberColumn("Input tokens", format="%d"),
                    "output_tokens": st.column_config.NumberColumn("Output tokens", format="%d"),
                    "cost_usd": st.column_config.TextColumn("Est. USD"),
                },
            )

            # ---- Visual breakdown ----
            # Per-agent input/output bar chart so reviewers see which agent
            # dominates the bill without parsing the table by eye.
            chart_rows = [r for r in rows if r["agent"] != "Total"]
            if chart_rows:
                chart_data = {
                    "Agent": [r["agent"] for r in chart_rows],
                    "Input tokens": [r["input_tokens"] for r in chart_rows],
                    "Output tokens": [r["output_tokens"] for r in chart_rows],
                }
                try:
                    import pandas as pd  # local — only needed when the panel renders
                    df = pd.DataFrame(chart_data).set_index("Agent")
                    st.bar_chart(df, height=180)
                except ImportError:
                    pass

            # ---- Cost trend across recent runs ----
            # Loads the last ten run summaries from disk and renders a tiny
            # line chart so users can see whether per-run cost is creeping up
            # after a prompt or model change. Cheap (reads ~10 small JSONs);
            # silent fallback if history isn't present yet.
            history = _load_run_history()[:10]
            trend = [
                {"run": h.get("source_label") or h.get("run_dir") or "?",
                 "cost_usd": float(h.get("cost_usd") or 0)}
                for h in reversed(history)
                if (h.get("cost_usd") or 0) > 0
            ]
            if len(trend) >= 2:
                try:
                    import pandas as pd
                    tdf = pd.DataFrame(trend).set_index("run")
                    st.caption("Cost across recent runs (USD)")
                    st.line_chart(tdf, height=140)
                except ImportError:
                    pass

            st.caption(
                "Prices from `src/pricing.py` — paid-tier list rates for Anthropic "
                "Claude (Sonnet 4.5 / Haiku 4.5) and Google Gemini (2.5 Flash / Pro) "
                "as of late 2025. `(free tier)` marks models eligible for AI Studio's "
                "free quota where your actual bill is $0. Labeled *est.* because "
                "cache hits and batch discounts aren't accounted for."
            )

    # ---- Tabs ----
    n_findings = len(result.get("guardrail_findings") or [])
    tab_epics, tab_gaps, tab_conf, tab_dups, tab_guard, tab_audit = st.tabs([
        f"Epics ({n_stories} stories)",
        f"Gaps ({len(result.get('gaps') or [])})",
        f"Conflicts ({len(result.get('conflicts') or [])})",
        f"Duplicates ({dup_count})",
        f"Guardrails ({n_findings})",
        "Audit trail",
    ])

    with tab_epics:
        if result.get("summary"):
            st.markdown(
                f'<div class="summary-card">'
                f'<div class="summary-label">Run summary</div>'
                f'{_esc(result["summary"])}'
                f'</div>',
                unsafe_allow_html=True,
            )
        _render_epics_tab(result)
    with tab_gaps:
        _render_findings_tab(result, "gaps")
    with tab_conf:
        _render_findings_tab(result, "conflicts")
    with tab_dups:
        _render_findings_tab(result, "duplicates")
    with tab_guard:
        _render_guardrails_tab(result)
    with tab_audit:
        # Audit markdown contains <details> blocks for full prompt + response
        # capture; render with raw HTML enabled so the collapsibles work.
        st.markdown(
            result.get("audit_trail", "_No audit trail captured._"),
            unsafe_allow_html=True,
        )

    # ---- Downloads ----
    st.markdown("### Downloads")
    run_dir: Path = st.session_state.run_dir
    cols = st.columns(3)
    # Build live JSON / MD from current (possibly edited) result so the
    # download reflects edits the user made in the data_editor.
    live_json = json.dumps(
        {k: v for k, v in result.items() if k != "audit_trail"},
        indent=2,
    )
    from output_formatter import _render_markdown as _build_md  # local import
    live_md = _build_md(result, source_label=st.session_state.source_label)
    run_stem = run_dir.name if run_dir else datetime.now().strftime("%Y%m%d_%H%M%S")
    with cols[0]:
        st.download_button(
            "↓  synthesis.md",
            live_md,
            file_name=f"{run_stem}_synthesis.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with cols[1]:
        st.download_button(
            "↓  synthesis.json",
            live_json,
            file_name=f"{run_stem}_synthesis.json",
            mime="application/json",
            use_container_width=True,
        )
    with cols[2]:
        audit_md = (run_dir / "audit_trail.md") if run_dir else None
        if audit_md and audit_md.exists():
            st.download_button(
                "↓  audit_trail.md",
                audit_md.read_text(encoding="utf-8"),
                file_name=f"{run_stem}_audit_trail.md",
                mime="text/markdown",
                use_container_width=True,
            )
        else:
            st.download_button(
                "↓  audit_trail.md",
                result.get("audit_trail", ""),
                file_name=f"{run_stem}_audit_trail.md",
                mime="text/markdown",
                use_container_width=True,
            )
    if run_dir is not None:
        try:
            rel = run_dir.relative_to(ROOT)
            st.caption(f"All three artifacts also live on the server under `{rel}/`.")
        except ValueError:
            pass

    # Jira write-back is available via the "⤴ Jira" top-nav button.
    # No duplicate inline section — keeps the Downloads area clean.
