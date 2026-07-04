"""Run-history persistence and dialog for the Backlog Synthesizer UI."""

from __future__ import annotations
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

# Three levels up: src/ui/ → src/ → project root
ROOT = Path(__file__).resolve().parent.parent.parent

# Respect LOGS_DIR env var so Azure deployments write to the mounted
# Azure Files share (/app/backlog-data/logs) instead of the ephemeral
# container layer.  Falls back to ROOT/logs for local development.
_LOGS_BASE = Path(os.environ.get("LOGS_DIR", str(ROOT / "logs")))
RUNS_DIR = _LOGS_BASE / "runs"

# Per-user hard daily spend cap (USD). Override via env var DAILY_BUDGET_USD.
# Set to 0 to disable the cap entirely.
DAILY_BUDGET_USD: float = float(os.environ.get("DAILY_BUDGET_USD", "10.0"))

# Number of pipeline stages — used to build stage_states lists without
# importing _STAGES from app.py (which would create a circular import).
_N_STAGES = 5


def _esc(value: Any) -> str:
    """Minimal HTML escape so user content doesn't escape its container."""
    if value is None:
        return ""
    s = str(value)
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;").replace("'", "&#x27;")
    )


def _user_runs_dir(user_id: str) -> Path:
    """Per-user run history directory: logs/runs/<safe_user_id>/"""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in (user_id or "anonymous"))
    return RUNS_DIR / safe


def _save_run_to_disk(summary: dict[str, Any]) -> Path:
    """Write summary JSON scoped to the current user: logs/runs/<user_id>/<stamp>_<id>.json"""
    user_id = summary.get("user_id", "anonymous")
    user_dir = _user_runs_dir(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    short_id = uuid.uuid4().hex[:6]
    stamp = summary.get("timestamp") or datetime.now().strftime("%Y%m%d_%H%M%S")
    path = user_dir / f"{stamp}_{short_id}.json"
    try:
        path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    except OSError as e:
        st.warning(f"Could not save run history: {e}")
    return path


def _load_run_history() -> list[dict[str, Any]]:
    """Load run history for the current user."""
    if not RUNS_DIR.exists():
        return []
    entries: list[dict[str, Any]] = []

    current_uid = st.session_state.get("username") or "anonymous"
    search_dirs = [_user_runs_dir(current_uid), RUNS_DIR]  # also legacy flat structure

    for d in search_dirs:
        if not d.exists():
            continue
        for p in d.glob("*.json"):
            try:
                entries.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue

    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return entries


def _user_today_spend(user_id: str) -> float:
    """Sum cost_usd for all runs by *user_id* that started today (local date)."""
    today = datetime.now().strftime("%Y%m%d")
    total = 0.0
    user_dir = _user_runs_dir(user_id)
    if not user_dir.exists():
        return 0.0
    for p in user_dir.glob("*.json"):
        if not p.name.startswith(today):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            total += float(data.get("cost_usd") or 0)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return total


def _load_all_user_runs() -> dict[str, list[dict]]:
    """Load run history for every user under RUNS_DIR.

    Returns a dict mapping user_id (directory name) -> list of run summaries,
    sorted newest-first within each user.  Used for org-wide cost reporting.
    """
    if not RUNS_DIR.exists():
        return {}
    result: dict[str, list[dict]] = {}
    for user_dir in RUNS_DIR.iterdir():
        if not user_dir.is_dir():
            continue
        runs: list[dict] = []
        for p in user_dir.glob("*.json"):
            try:
                runs.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        runs.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        result[user_dir.name] = runs
    return result


@st.dialog("Run history", width="large")
def show_run_history_dialog() -> None:
    """Modal: list past runs from logs/runs/*.json with a "Load" button each.

    Polish over the v1 dialog: free-text search, date-bucket grouping
    (Today / Yesterday / This week / Older), per-row delete, and a small
    aggregate strip showing total runs + total spend across history.
    """
    history = _load_run_history()
    if not history:
        st.markdown(
            '<div style="padding: 1.4rem; text-align: center; color: var(--text-muted);">'
            'No persisted runs yet. After your next synthesis completes, this '
            'list will populate from <code>logs/runs/</code>.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # ---- Aggregate strip (total runs + cumulative cost) ----
    total_cost = 0.0
    total_stories = 0
    for h in history:
        try:
            total_cost += float(h.get("cost_usd") or 0)
        except (TypeError, ValueError):
            pass
        total_stories += int(h.get("story_count") or h.get("n_stories") or 0)

    st.markdown(
        '<div style="display:flex;gap:0.6rem;margin-bottom:0.85rem;">'
        f'<div class="rh-summary-chip"><span>Runs</span>{len(history)}</div>'
        f'<div class="rh-summary-chip"><span>Stories drafted</span>{total_stories}</div>'
        f'<div class="rh-summary-chip"><span>Total est. cost</span>${total_cost:.4f}</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ---- Org-wide cost summary (admin view) ----
    with st.expander("Org cost overview", expanded=False):
        all_runs = _load_all_user_runs()
        if not all_runs:
            st.caption("No runs found across the org yet.")
        else:
            now_month = datetime.now().strftime("%Y%m")
            rows: list[tuple[str, int, float, float]] = []  # (user, run_count, month_cost, total_cost)
            for uid, uruns in sorted(all_runs.items()):
                u_total = sum(float(r.get("cost_usd") or 0) for r in uruns)
                u_month = sum(
                    float(r.get("cost_usd") or 0)
                    for r in uruns
                    if (r.get("timestamp") or "").startswith(now_month)
                )
                rows.append((uid, len(uruns), u_month, u_total))
            rows.sort(key=lambda r: r[3], reverse=True)

            org_month = sum(r[2] for r in rows)
            org_total = sum(r[3] for r in rows)
            st.markdown(
                f"**{len(rows)} users · ${org_month:.4f} this month · ${org_total:.4f} all-time**"
            )
            for uid, run_count, month_cost, all_time_cost in rows:
                st.markdown(
                    f"- `{uid}` — {run_count} runs · "
                    f"${month_cost:.4f} this month · "
                    f"${all_time_cost:.4f} all-time"
                )

    # ---- Search / filter ----
    query = st.text_input(
        "Filter",
        placeholder="Search by source name, model, or timestamp…",
        key="rh_search",
        label_visibility="collapsed",
    ).strip().lower()

    if query:
        filtered = [
            h for h in history
            if query in (h.get("source_label") or "").lower()
            or query in (h.get("model") or "").lower()
            or query in (h.get("timestamp") or "").lower()
        ]
    else:
        filtered = history

    if not filtered:
        st.caption(f"No matches for '{query}'. Clear the filter to see all runs.")
        return

    # ---- Bucket by recency ----
    now = datetime.now()
    buckets: dict[str, list[dict]] = {"Today": [], "Yesterday": [], "This week": [], "Older": []}
    for entry in filtered:
        stamp = entry.get("timestamp", "")
        try:
            dt = datetime.strptime(stamp, "%Y%m%d_%H%M%S")
        except (ValueError, TypeError):
            buckets["Older"].append(entry)
            continue
        delta_days = (now.date() - dt.date()).days
        if delta_days == 0:
            buckets["Today"].append(entry)
        elif delta_days == 1:
            buckets["Yesterday"].append(entry)
        elif delta_days <= 7:
            buckets["This week"].append(entry)
        else:
            buckets["Older"].append(entry)

    current_run_id = (st.session_state.get("run_dir") or "").name \
        if hasattr(st.session_state.get("run_dir") or "", "name") else ""

    for bucket_name, entries in buckets.items():
        if not entries:
            continue
        st.markdown(
            f'<div style="font-size:0.66rem;font-weight:700;letter-spacing:0.16em;'
            f'text-transform:uppercase;color:var(--text-faint);'
            f'margin:1rem 0 0.55rem;">{bucket_name} · {len(entries)}</div>',
            unsafe_allow_html=True,
        )
        for entry in entries:
            _render_history_row(entry, current_run_id)


def _render_history_row(entry: dict, current_run_id: str) -> None:
    """One run card inside the history dialog. Factored out so the buckets
    above can iterate without nesting columns inside columns."""
    stamp = entry.get("timestamp", "—")
    try:
        dt = datetime.strptime(stamp, "%Y%m%d_%H%M%S")
        date_label = dt.strftime("%b %d, %Y · %H:%M:%S")
    except (ValueError, TypeError):
        date_label = stamp

    run_id = entry.get("run_id", stamp)
    is_current = bool(current_run_id) and current_run_id == run_id

    cols = st.columns([5, 1, 1])
    with cols[0]:
        chips = []
        for label, val in (
            ("epics", entry.get("epic_count") or entry.get("n_epics") or 0),
            ("stories", entry.get("story_count") or entry.get("n_stories") or 0),
            ("dups", entry.get("dup_count") or entry.get("n_dups") or 0),
            ("elapsed", f"{float(entry.get('elapsed_seconds', 0) or 0):.1f}s"),
            ("model", entry.get("model") or "—"),
        ):
            chips.append(f'<span class="rh-chip">{_esc(label)}={_esc(val)}</span>')
        cost = entry.get("cost_usd")
        if cost is not None:
            try:
                chips.append(f'<span class="rh-chip rh-chip-accent">${float(cost):.4f}</span>')
            except (TypeError, ValueError):
                pass
        current_badge = (
            '<span class="rh-chip rh-chip-current">⌖ current</span>'
            if is_current else ""
        )
        card_cls = "rh-card rh-card-current" if is_current else "rh-card"
        st.markdown(
            f'<div class="{card_cls}">'
            f'<div class="rh-card-top">'
            f'<div><div class="rh-card-date">{_esc(date_label)}{current_badge}</div>'
            f'<div class="rh-card-source">{_esc(entry.get("source_label", "—"))}</div></div>'
            f'</div>'
            f'<div class="rh-card-meta">{"".join(chips)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with cols[1]:
        if st.button("Load", key=f"history_load_{run_id}", use_container_width=True,
                     disabled=is_current,
                     help="Already loaded" if is_current else "Re-open this run"):
            _load_history_into_state(entry)
            st.rerun()
    with cols[2]:
        if st.button("✕", key=f"history_delete_{run_id}", use_container_width=True,
                     help="Delete this run's metadata file (output files are kept)."):
            _delete_history_entry(entry)
            st.rerun()


def _delete_history_entry(entry: dict) -> None:
    """Remove a single run's metadata JSON from logs/runs/.

    We delete only the metadata file — the corresponding `outputs/<stamp>/`
    directory is kept so the synthesis artefacts aren't lost on a stray
    click. If the user wants a clean wipe, that's a shell rm.
    """
    run_id = entry.get("run_id") or entry.get("timestamp", "")
    if not run_id:
        return
    # Search all user subdirectories for the run file
    deleted = 0
    if not RUNS_DIR.exists():
        st.toast(f"No metadata file found for run {run_id}", icon="⚠️")
        return
    search_dirs = [RUNS_DIR] + [d for d in RUNS_DIR.iterdir() if d.is_dir()]
    for d in search_dirs:
        for p in d.glob(f"{run_id}*.json"):
            try:
                p.unlink()
                deleted += 1
            except OSError:
                pass
    if deleted:
        st.toast(f"Deleted run metadata · {deleted} file(s)", icon="🗑️")
    else:
        st.toast(f"No metadata file found for run {run_id}", icon="⚠️")


def _load_history_into_state(entry: dict[str, Any]) -> None:
    """Restore a saved run's outputs into session_state for re-display."""
    outputs = entry.get("outputs", {}) or {}
    synth_path = outputs.get("synthesis_json")
    if synth_path:
        p = Path(synth_path)
        # Absolute paths from a different machine won't exist here; try to find
        # the file relative to ROOT/outputs as a fallback before giving up.
        if not p.exists():
            relative_candidate = ROOT / "outputs" / p.name
            if not relative_candidate.exists():
                # Walk outputs/ for any file with the same name.
                matches = list((ROOT / "outputs").rglob(p.name)) if (ROOT / "outputs").exists() else []
                if matches:
                    p = matches[0]
                else:
                    st.warning(
                        f"Run output file not found: `{synth_path}`. "
                        "This run was created on a different machine. "
                        "Only the run summary metadata is available."
                    )
                    return
            else:
                p = relative_candidate
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                st.error(f"Could not load run outputs: {e}")
                return
            # The historical synthesis.json doesn't carry audit_trail —
            # try to read the sibling file.
            audit_md = p.parent / "audit_trail.md"
            if audit_md.exists():
                data["audit_trail"] = audit_md.read_text(encoding="utf-8")
            data.setdefault("token_usage", entry.get("token_usage") or {})
            data.setdefault("model", entry.get("model") or "")
            st.session_state.result = data
            st.session_state.run_dir = p.parent
            st.session_state.elapsed = entry.get("elapsed_seconds") or 0
            st.session_state.source_label = entry.get("source_label") or ""
            st.session_state.stage_states = ["done"] * _N_STAGES
            st.session_state.tokens_total = (
                (entry.get("token_usage") or {}).get("total", {}).get("input", 0)
                + (entry.get("token_usage") or {}).get("total", {}).get("output", 0)
            )
            st.session_state.cost_usd = entry.get("cost_usd") or 0
            st.session_state.model_used = entry.get("model") or ""
            st.session_state.epics_original = json.loads(json.dumps(data.get("epics") or []))
            # Reset transient UI state so a loaded historical run renders
            # cleanly: drop any stale dry-run preview and edit-mode flag.
            st.session_state.dry_run_result = None
            st.session_state.stories_edit_mode = False
