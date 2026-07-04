#!/usr/bin/env python3
"""Query the Backlog Synthesizer audit chain database.

The SQLite database (logs/audit_chain.db) stores every agent decision with a
SHA-256 hash chain that makes post-hoc edits detectable.  This script lets
compliance reviewers, engineers, and auditors query the database without
needing to open sqlite3 manually.

Usage examples
--------------
  # List all runs (most recent first)
  python scripts/audit_query.py --list-runs

  # Show all events for a specific run
  python scripts/audit_query.py --run 20250610_142301

  # Verify the hash chain is intact (no tampering)
  python scripts/audit_query.py --verify

  # Verify a single run
  python scripts/audit_query.py --verify --run 20250610_142301

  # Export all events since a date to JSON (for external compliance tools)
  python scripts/audit_query.py --export --since 2025-06-01 --output audit_export.json

  # Export to CSV (for Excel / Google Sheets)
  python scripts/audit_query.py --export --format csv --output audit_export.csv

  # Aggregate stats across all runs
  python scripts/audit_query.py --stats

  # Show runs by a specific user
  python scripts/audit_query.py --list-runs --user alice@example.com
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── DB path resolution ────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent.parent
_DEFAULT_DB = Path(os.environ.get(
    "AUDIT_DB_PATH",
    str(_HERE / "logs" / "audit_chain.db"),
))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        print(f"ERROR: database not found at {db_path}", file=sys.stderr)
        print("  Set AUDIT_DB_PATH or pass --db to override the path.", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _fmt_ts(ts: str) -> str:
    """Make a raw timestamp string human-readable."""
    try:
        dt = datetime.strptime(ts, "%Y%m%d_%H%M%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ts


def _recompute_hash(prev_hash: str, row: sqlite3.Row) -> str:
    """Re-derive the event hash for a DB row to check for tampering."""
    event_dict = {
        "timestamp": row["timestamp"],
        "agent":     row["agent"],
        "event":     row["event"],
        "payload":   json.loads(row["payload_json"]),
        "reasoning": row["reasoning"],
    }
    canonical = json.dumps(event_dict, sort_keys=True, ensure_ascii=True)
    payload = f"{prev_hash}|{canonical}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_list_runs(args: argparse.Namespace) -> None:
    conn = _connect(args.db)
    where_clauses: list[str] = []
    params: list[Any] = []

    if args.since:
        where_clauses.append("timestamp >= ?")
        params.append(args.since.replace("-", "") + "_000000")
    if args.user:
        where_clauses.append("run_id LIKE ?")
        params.append(f"%{args.user}%")

    where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    rows = conn.execute(f"""
        SELECT
            run_id,
            MIN(timestamp)  AS started_at,
            MAX(timestamp)  AS finished_at,
            COUNT(*)        AS event_count,
            SUM(CASE WHEN event = 'failure' THEN 1 ELSE 0 END) AS failures,
            GROUP_CONCAT(DISTINCT agent) AS agents
        FROM audit_events
        {where}
        GROUP BY run_id
        ORDER BY started_at DESC
        LIMIT ?
    """, (*params, args.limit)).fetchall()

    if not rows:
        print("No runs found.")
        return

    print(f"\n{'Run ID':<28}  {'Started':<19}  {'Events':>6}  {'Failures':>8}  Agents")
    print("─" * 90)
    for r in rows:
        agents_brief = ", ".join(r["agents"].split(",")[:3]) if r["agents"] else "—"
        if len(r["agents"].split(",")) > 3:
            agents_brief += f" +{len(r['agents'].split(',')) - 3} more"
        print(
            f"{r['run_id']:<28}  {_fmt_ts(r['started_at']):<19}"
            f"  {r['event_count']:>6}  {r['failures']:>8}  {agents_brief}"
        )
    print(f"\n{len(rows)} run(s) shown (limit {args.limit}). Use --limit N to see more.")
    conn.close()


def cmd_show_run(args: argparse.Namespace) -> None:
    conn = _connect(args.db)
    rows = conn.execute(
        "SELECT * FROM audit_events WHERE run_id = ? ORDER BY seq",
        (args.run,),
    ).fetchall()

    if not rows:
        print(f"No events found for run_id: {args.run}")
        sys.exit(1)

    print(f"\n── Run: {args.run}  ({len(rows)} events) ────────────────────────────────")
    for r in rows:
        payload = json.loads(r["payload_json"])
        reasoning = r["reasoning"][:120] + "…" if len(r["reasoning"]) > 120 else r["reasoning"]

        print(f"\n  [{r['seq']:4}] {_fmt_ts(r['timestamp'])}  "
              f"{r['agent']:<30} {r['event']}")
        if reasoning:
            print(f"         Reasoning: {reasoning}")
        if payload:
            payload_str = json.dumps(payload, ensure_ascii=False)
            if len(payload_str) > 200:
                payload_str = payload_str[:197] + "…"
            print(f"         Payload:   {payload_str}")
        if args.hashes:
            print(f"         Hash:      {r['event_hash'][:16]}…")

    conn.close()


def cmd_verify(args: argparse.Namespace) -> None:
    conn = _connect(args.db)
    where = "WHERE run_id = ?" if args.run else ""
    params = [args.run] if args.run else []

    # Group by run_id to verify each run independently
    run_ids = [
        r[0] for r in conn.execute(
            f"SELECT DISTINCT run_id FROM audit_events {where} ORDER BY run_id",
            params,
        )
    ]

    if not run_ids:
        print(f"No run found: {args.run}" if args.run else "No runs in database.")
        sys.exit(1)

    all_ok = True
    for run_id in run_ids:
        rows = conn.execute(
            "SELECT * FROM audit_events WHERE run_id = ? ORDER BY seq",
            (run_id,),
        ).fetchall()
        prev_hash = "GENESIS"
        ok = True
        bad_seqs: list[int] = []
        for r in rows:
            expected = _recompute_hash(prev_hash, r)
            if expected != r["event_hash"]:
                ok = False
                bad_seqs.append(r["seq"])
            prev_hash = r["event_hash"]

        status = "✓ OK" if ok else f"✗ TAMPERED (events: {bad_seqs})"
        chain_fp = rows[-1]["event_hash"][:16] + "…" if rows else "—"
        print(f"  {run_id:<30} {len(rows):>4} events  chain:{chain_fp}  {status}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print(f"All {len(run_ids)} run(s) verified — hash chain intact.")
    else:
        print("WARNING: hash chain violations detected. The audit log may have been tampered with.")
        sys.exit(2)

    conn.close()


def cmd_export(args: argparse.Namespace) -> None:
    conn = _connect(args.db)
    where_clauses: list[str] = []
    params: list[Any] = []

    if args.since:
        where_clauses.append("timestamp >= ?")
        params.append(args.since.replace("-", "") + "_000000")
    if args.run:
        where_clauses.append("run_id = ?")
        params.append(args.run)

    where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    rows = conn.execute(
        f"SELECT * FROM audit_events {where} ORDER BY seq",
        params,
    ).fetchall()

    if not rows:
        print("No events match the filter.")
        sys.exit(1)

    records = [
        {
            "seq":          r["seq"],
            "run_id":       r["run_id"],
            "timestamp":    r["timestamp"],
            "agent":        r["agent"],
            "event":        r["event"],
            "payload":      json.loads(r["payload_json"]),
            "reasoning":    r["reasoning"],
            "prev_hash":    r["prev_hash"],
            "event_hash":   r["event_hash"],
        }
        for r in rows
    ]

    out = sys.stdout if args.output == "-" else open(args.output, "w", encoding="utf-8")
    try:
        if args.format == "json":
            json.dump(records, out, indent=2, ensure_ascii=False)
            out.write("\n")
        else:  # csv
            flat_fields = ["seq", "run_id", "timestamp", "agent", "event",
                           "payload_json", "reasoning", "prev_hash", "event_hash"]
            writer = csv.DictWriter(out, fieldnames=flat_fields)
            writer.writeheader()
            for r in rows:
                writer.writerow(dict(r))
    finally:
        if out is not sys.stdout:
            out.close()

    dest = args.output if args.output != "-" else "stdout"
    print(f"Exported {len(records)} events → {dest} ({args.format.upper()})",
          file=sys.stderr)
    conn.close()


def cmd_stats(args: argparse.Namespace) -> None:
    conn = _connect(args.db)
    total_runs = conn.execute("SELECT COUNT(DISTINCT run_id) FROM audit_events").fetchone()[0]
    total_events = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    first_ts = conn.execute("SELECT MIN(timestamp) FROM audit_events").fetchone()[0]
    last_ts  = conn.execute("SELECT MAX(timestamp) FROM audit_events").fetchone()[0]
    failures = conn.execute(
        "SELECT COUNT(DISTINCT run_id) FROM audit_events WHERE event = 'failure'"
    ).fetchone()[0]

    agent_rows = conn.execute(
        "SELECT agent, COUNT(*) AS n FROM audit_events GROUP BY agent ORDER BY n DESC LIMIT 10"
    ).fetchall()

    print(f"\n── Audit Database Statistics ────────────────────────────────────────")
    print(f"  Database:      {args.db}")
    print(f"  Total runs:    {total_runs}  ({failures} with at least one failure)")
    print(f"  Total events:  {total_events}")
    print(f"  First event:   {_fmt_ts(first_ts) if first_ts else '—'}")
    print(f"  Last event:    {_fmt_ts(last_ts)  if last_ts  else '—'}")
    print(f"\n  Top agents by event count:")
    for a in agent_rows:
        print(f"    {a['agent']:<35} {a['n']:>6} events")
    print()
    conn.close()


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query the Backlog Synthesizer audit chain database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage examples")[1] if "Usage examples" in __doc__ else "",
    )
    parser.add_argument(
        "--db", type=Path, default=_DEFAULT_DB,
        help=f"Path to audit_chain.db (default: {_DEFAULT_DB})",
    )

    sub = parser.add_subparsers(dest="command")

    # list-runs
    p_list = sub.add_parser("list-runs", aliases=["ls"], help="List all runs")
    p_list.add_argument("--since", metavar="YYYY-MM-DD", help="Only runs on or after this date")
    p_list.add_argument("--user",  help="Filter by user ID substring")
    p_list.add_argument("--limit", type=int, default=50, help="Max runs to show (default 50)")

    # show / run
    p_show = sub.add_parser("show", aliases=["run"], help="Show events for a specific run")
    p_show.add_argument("run", help="run_id to display")
    p_show.add_argument("--hashes", action="store_true", help="Show event hash prefixes")

    # verify
    p_verify = sub.add_parser("verify", help="Verify the SHA-256 hash chain")
    p_verify.add_argument("--run", help="Verify only this run_id (default: all runs)")

    # export
    p_export = sub.add_parser("export", help="Export events to JSON or CSV")
    p_export.add_argument("--format", choices=["json", "csv"], default="json")
    p_export.add_argument("--output", default="-", help="Output file path (default: stdout)")
    p_export.add_argument("--since", metavar="YYYY-MM-DD")
    p_export.add_argument("--run", help="Export only this run_id")

    # stats
    sub.add_parser("stats", help="Aggregate statistics across all runs")

    # backwards-compat flat flags (kept for convenience)
    parser.add_argument("--list-runs",  action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--run",        help=argparse.SUPPRESS)
    parser.add_argument("--verify",     action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--export",     action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--format",     choices=["json", "csv"], default="json", help=argparse.SUPPRESS)
    parser.add_argument("--output",     default="-", help=argparse.SUPPRESS)
    parser.add_argument("--since",      metavar="YYYY-MM-DD", help=argparse.SUPPRESS)
    parser.add_argument("--limit",      type=int, default=50, help=argparse.SUPPRESS)
    parser.add_argument("--user",       help=argparse.SUPPRESS)
    parser.add_argument("--stats",      action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--hashes",     action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    # Dispatch subcommands
    if args.command in ("list-runs", "ls"):
        cmd_list_runs(args)
    elif args.command in ("show", "run"):
        cmd_show_run(args)
    elif args.command == "verify":
        cmd_verify(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "stats":
        cmd_stats(args)
    # Backwards-compat flat flags
    elif args.list_runs:
        cmd_list_runs(args)
    elif args.verify:
        cmd_verify(args)
    elif args.export:
        cmd_export(args)
    elif args.stats:
        cmd_stats(args)
    elif args.run:
        cmd_show_run(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
