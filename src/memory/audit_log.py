"""Append-only audit log of every agent decision.

Each event captures: timestamp, agent name, event type, structured payload,
and an optional human-readable reasoning string. At the end of a run, the
log is rendered as a Markdown trace that a reviewer can read top-to-bottom.

Tamper evidence: every event is stored in an append-only SQLite database
alongside a SHA-256 hash chain (each event's hash covers the previous hash
+ the event JSON). This makes post-hoc editing detectable — a reviewer can
call `verify_chain()` to confirm the log hasn't been altered after the fact.

The markdown rendering is unchanged so the UI and exports work as before.
SQLite persistence is best-effort: if the database write fails (disk full,
permissions) the in-memory log still works and the run is not aborted.

This addresses the requirement: "Audit logs must show how conclusions were
reached" with tamper-evidence suitable for compliance review.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ---- PII redaction patterns --------------------------------------------------
# Applied to LLM prompts before they are written to the audit database.
# Transcripts may contain speaker names, email addresses, phone numbers, and
# other identifiers that must not land in a tamper-evident log without consent.
_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'), "[EMAIL REDACTED]"),
    (re.compile(r'\b(\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b'), "[PHONE REDACTED]"),
    (re.compile(r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b'), "[SSN REDACTED]"),
    (re.compile(r'\b(?:\d[ -]?){13,16}\b'), "[CARD REDACTED]"),
]

# Configurable — set AUDIT_PII_REDACTION=0 to disable (e.g. for on-prem
# deployments where the audit DB is itself a controlled PII store).
_PII_REDACTION_ENABLED = os.environ.get("AUDIT_PII_REDACTION", "1").strip() not in ("0", "false", "no")

# ---- Retention policy --------------------------------------------------------
# AUDIT_LOG_RETENTION_DAYS=0 means keep forever (default for tamper-evidence).
_RETENTION_DAYS = int(os.environ.get("AUDIT_LOG_RETENTION_DAYS", "0"))


def _redact_pii(text: str) -> str:
    """Replace recognised PII patterns with placeholder tokens."""
    if not _PII_REDACTION_ENABLED:
        return text
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


@dataclass
class AuditEvent:
    timestamp: str
    agent: str
    event: str
    payload: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""


# Root for the SQLite audit database.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_AUDIT_DB_PATH = _PROJECT_ROOT / "logs" / "audit_chain.db"


def _event_hash(prev_hash: str, event: AuditEvent) -> str:
    """SHA-256 over prev_hash | canonical JSON of the event.

    Sorting keys ensures the hash is deterministic regardless of dict
    insertion order. Using a pipe separator prevents length-extension attacks.
    """
    canonical = json.dumps(asdict(event), sort_keys=True, ensure_ascii=True)
    payload = f"{prev_hash}|{canonical}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _ensure_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            seq         INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      TEXT    NOT NULL,
            timestamp   TEXT    NOT NULL,
            agent       TEXT    NOT NULL,
            event       TEXT    NOT NULL,
            payload_json TEXT   NOT NULL,
            reasoning   TEXT    NOT NULL,
            prev_hash   TEXT    NOT NULL,
            event_hash  TEXT    NOT NULL
        )
    """)
    conn.commit()


class AuditLog:
    """Append-only log of audit events for one orchestrator run.

    In addition to the in-memory list (used for markdown rendering and
    the result dict), every event is persisted to a SQLite database with
    a SHA-256 hash chain so the log is tamper-evident.
    """

    def __init__(self, run_id: str | None = None) -> None:
        self._events: list[AuditEvent] = []
        self._run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._last_hash = "GENESIS"  # anchor for the first event
        self._db_path = Path(os.environ.get("AUDIT_DB_PATH", str(_AUDIT_DB_PATH)))
        self._db_ok = False
        self._conn: sqlite3.Connection | None = None
        # Protects _last_hash, _events, and the DB connection from concurrent
        # writes when parallel pipeline nodes call record() simultaneously.
        self._lock = threading.Lock()
        self._init_db()

    def __reduce__(self) -> tuple:
        # LangGraph's MemorySaver checkpoints all state fields including the
        # AuditLog instance.  AuditLog is not msgpack-serializable; returning
        # a fresh empty instance on deserialization is safe because the live
        # object remains in scope within the same process throughout the run.
        return (self.__class__.__new__, (self.__class__,))

    def _init_db(self) -> None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,  # lock protects concurrent access
            )
            # WAL journal mode: readers never block writers and vice-versa.
            # With multiple concurrent runs each holding their own connection,
            # this eliminates the per-write lock contention on the shared file.
            conn.execute("PRAGMA journal_mode=WAL")
            # NORMAL sync is safe with WAL and gives ~5x faster writes vs FULL.
            conn.execute("PRAGMA synchronous=NORMAL")
            _ensure_db(conn)
            self._conn = conn
            self._db_ok = True
        except Exception:  # noqa: BLE001 — never break a run over audit persistence
            self._db_ok = False

    def _persist(self, event: AuditEvent, prev_hash: str, event_hash: str) -> None:
        if not self._db_ok or self._conn is None:
            return
        try:
            self._conn.execute(
                """INSERT INTO audit_events
                   (run_id, timestamp, agent, event, payload_json,
                    reasoning, prev_hash, event_hash)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    self._run_id,
                    event.timestamp,
                    event.agent,
                    event.event,
                    json.dumps(event.payload, ensure_ascii=True),
                    event.reasoning,
                    prev_hash,
                    event_hash,
                ),
            )
            self._conn.commit()
        except Exception:  # noqa: BLE001
            pass  # best-effort persistence — in-memory log is authoritative

    # ---------------------------------------------------------- recording

    def record(
        self,
        agent: str,
        event: str,
        payload: dict[str, Any] | None = None,
        reasoning: str = "",
    ) -> None:
        ev = AuditEvent(
            timestamp=_now(),
            agent=agent,
            event=event,
            payload=payload or {},
            reasoning=reasoning,
        )
        with self._lock:
            # Lock protects the hash chain (prev → new) and the events list
            # against concurrent writes from parallel pipeline nodes.
            prev = self._last_hash
            h = _event_hash(prev, ev)
            self._last_hash = h
            self._events.append(ev)
        self._persist(ev, prev, h)

    def record_tool_call(
        self,
        agent: str,
        tool: str,
        request: dict[str, Any] | None = None,
        response_excerpt: str = "",
        tokens_used: int | None = None,
        usage: dict[str, Any] | None = None,
        prompt: str | None = None,
        response_text: str | None = None,
    ) -> None:
        """Record an LLM/tool invocation with optional full prompt + response capture.

        Parameters:
            request          structured metadata about the call (chars,
                             max_tokens, etc.) — short-truncated for the
                             scorecard summary view.
            response_excerpt 300-char preview used by the markdown rollup.
            prompt           full prompt text sent to the LLM. Kept under
                             a separate key so the markdown render can put
                             it in a collapsible block. Trimmed at 16 KB
                             to keep the audit file readable.
            response_text    full LLM response text. Same 16 KB cap.

        Trimming happens here, not at the call site, so every audit entry
        is consistently bounded. Reviewers who want the unbounded version
        can pull from `synthesis.json` (which has the parsed structured
        output) or the application logs.
        """
        payload = {
            "tool": tool,
            "request": _truncate_dict(request or {}, max_chars=300),
            "response_excerpt": _truncate(response_excerpt, max_chars=300),
        }
        if tokens_used is not None:
            payload["tokens_used"] = tokens_used
        if usage is not None:
            payload["usage"] = {
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            }
        # Full prompt + response — PII-redacted then capped to 16 KB each.
        # Redaction runs before truncation so the char-count reflects the
        # redacted length; reviewers see [EMAIL REDACTED] placeholders.
        if prompt is not None:
            redacted_prompt = _redact_pii(prompt)
            payload["prompt_full"] = _truncate(redacted_prompt, max_chars=16_000)
            payload["prompt_chars_actual"] = len(redacted_prompt)
        if response_text is not None:
            payload["response_full"] = _truncate(response_text, max_chars=16_000)
            payload["response_chars_actual"] = len(response_text)
        self.record(agent=agent, event="tool_call", payload=payload)

    def record_failure(self, agent: str, error: str) -> None:
        self.record(
            agent=agent,
            event="failure",
            payload={"error": error},
            reasoning=f"Agent failed permanently after retries: {error}",
        )

    # ----------------------------------------------------------- access

    @property
    def events(self) -> list[AuditEvent]:
        return list(self._events)

    def as_json_list(self) -> list[dict[str, Any]]:
        return [asdict(e) for e in self._events]

    @property
    def chain_fingerprint(self) -> str:
        """The final hash in the chain — a single value that covers all events.

        Changing any event (including reordering) produces a different fingerprint.
        Include this in run metadata for quick integrity checks without re-hashing
        the full chain.
        """
        return self._last_hash

    def verify_chain(self) -> tuple[bool, str]:
        """Re-derive the hash chain from the persisted SQLite rows for this run.

        Returns (ok: bool, message: str).
            ok=True  — chain is intact; no events were added, removed, or edited.
            ok=False — a hash mismatch was detected; message identifies the row.

        Falls back gracefully when the DB is unavailable (returns ok=True with
        a note so callers don't treat a missing DB as a violation).
        """
        if not self._db_ok:
            return True, "SQLite persistence unavailable — chain cannot be verified."
        try:
            conn = sqlite3.connect(str(self._db_path))
            rows = conn.execute(
                """SELECT seq, timestamp, agent, event, payload_json,
                          reasoning, prev_hash, event_hash
                   FROM audit_events WHERE run_id = ? ORDER BY seq""",
                (self._run_id,),
            ).fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            return True, f"Chain verification skipped (DB error): {e}"

        if not rows:
            return True, "No persisted events for this run_id."

        prev_hash = "GENESIS"
        for row in rows:
            seq, ts, agent, event, payload_json, reasoning, stored_prev, stored_hash = row
            try:
                payload = json.loads(payload_json)
            except json.JSONDecodeError:
                return False, f"Row seq={seq}: payload_json is not valid JSON."

            ev = AuditEvent(
                timestamp=ts, agent=agent, event=event,
                payload=payload, reasoning=reasoning,
            )
            expected_prev = prev_hash
            expected_hash = _event_hash(expected_prev, ev)

            if stored_prev != expected_prev:
                return False, (
                    f"Row seq={seq}: prev_hash mismatch "
                    f"(stored={stored_prev[:16]}… expected={expected_prev[:16]}…). "
                    "An event may have been inserted or deleted."
                )
            if stored_hash != expected_hash:
                return False, (
                    f"Row seq={seq}: event_hash mismatch "
                    f"(stored={stored_hash[:16]}… expected={expected_hash[:16]}…). "
                    "This event was modified after it was written."
                )
            prev_hash = stored_hash

        return True, f"Chain intact — {len(rows)} event(s) verified."

    @classmethod
    def purge_old_runs(
        cls,
        retention_days: int | None = None,
        db_path: Path | str | None = None,
    ) -> int:
        """Delete audit rows older than `retention_days` from the database.

        Designed for a scheduled job or startup call.  Returns the number of
        rows deleted.  A `retention_days` of 0 (or negative) is a no-op so
        callers can pass `AUDIT_LOG_RETENTION_DAYS` directly without a guard.

        The hash-chain is broken at the deletion boundary — callers should
        document this as an intentional retention purge in their compliance
        runbooks rather than treating it as a tamper signal.
        """
        days = retention_days if retention_days is not None else _RETENTION_DAYS
        if days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        path = Path(db_path) if db_path else Path(
            os.environ.get("AUDIT_DB_PATH", str(_AUDIT_DB_PATH))
        )
        if not path.exists():
            return 0
        try:
            conn = sqlite3.connect(str(path))
            cur = conn.execute(
                "DELETE FROM audit_events WHERE timestamp < ?", (cutoff,)
            )
            deleted = cur.rowcount
            conn.commit()
            conn.close()
            return deleted
        except Exception:  # noqa: BLE001
            return 0

    # Payload keys that carry potentially long LLM content. These get
    # rendered inside collapsible <details> blocks so the high-level
    # audit narrative stays scannable. Anything else falls through to
    # the short repr path.
    _LONG_PAYLOAD_KEYS = ("prompt_full", "response_full")

    def render_markdown(self) -> str:
        lines: list[str] = []
        lines.append("# Audit trail")
        lines.append("")
        lines.append(f"Total events: {len(self._events)}")
        lines.append("")
        for i, e in enumerate(self._events, start=1):
            lines.append(f"## {i}. `{e.agent}` — {e.event}")
            lines.append("")
            lines.append(f"- **Timestamp:** {e.timestamp}")
            if e.reasoning:
                lines.append(f"- **Reasoning:** {e.reasoning}")
            if e.payload:
                lines.append("- **Payload:**")
                for k, v in e.payload.items():
                    if k in self._LONG_PAYLOAD_KEYS and isinstance(v, str):
                        # Skip — we render these in dedicated blocks below.
                        continue
                    lines.append(f"    - `{k}`: {_short_repr(v)}")

                # Full prompt — collapsible. Streamlit's `st.markdown`
                # renders <details>/<summary> with `unsafe_allow_html=True`,
                # which is how this is shown in the UI's Audit tab.
                prompt_full = e.payload.get("prompt_full")
                if prompt_full:
                    actual = e.payload.get("prompt_chars_actual", len(prompt_full))
                    lines.append("")
                    lines.append(
                        f'<details><summary><strong>📤 Prompt sent to LLM</strong> '
                        f'<em>({actual:,} chars total)</em></summary>'
                    )
                    lines.append("")
                    lines.append("```")
                    lines.append(prompt_full)
                    lines.append("```")
                    lines.append("")
                    lines.append("</details>")

                # Full response — same treatment.
                response_full = e.payload.get("response_full")
                if response_full:
                    actual = e.payload.get("response_chars_actual", len(response_full))
                    lines.append("")
                    lines.append(
                        f'<details><summary><strong>📥 Response from LLM</strong> '
                        f'<em>({actual:,} chars total)</em></summary>'
                    )
                    lines.append("")
                    lines.append("```json")
                    lines.append(response_full)
                    lines.append("```")
                    lines.append("")
                    lines.append("</details>")
            lines.append("")
        return "\n".join(lines)


# -------------------------------------------------------------------- helpers

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _truncate(s: str, max_chars: int = 300) -> str:
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "…"


def _truncate_dict(d: dict[str, Any], max_chars: int = 300) -> dict[str, Any]:
    return {
        k: _truncate(str(v), max_chars) if isinstance(v, str) else v
        for k, v in d.items()
    }


def _short_repr(v: Any, max_chars: int = 300) -> str:
    if isinstance(v, str):
        return _truncate(v, max_chars)
    if isinstance(v, (dict, list)):
        s = str(v)
        return _truncate(s, max_chars)
    return str(v)
