"""Regression dashboard for evaluation runs.

Reads every `summary.json` under `evaluation/results/`, sorts by run
timestamp, and renders a trend report in the console plus an optional
markdown file. Catches regressions between prompt changes by comparing
the most recent two runs on every per-case score.

Usage:
    python evaluation/dashboard.py                # text report to stdout
    python evaluation/dashboard.py --md out.md    # also write markdown
    python evaluation/dashboard.py --last 5       # only consider last 5 runs

Designed to be cheap and dependency-free so it can run in CI as a
post-evaluation step.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _load_runs(results_dir: Path, limit: int | None = None) -> list[dict]:
    """Load every summary.json under `results_dir`, newest first."""
    if not results_dir.exists():
        return []
    runs: list[dict] = []
    for run_dir in sorted(results_dir.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        summary = run_dir / "summary.json"
        if not summary.exists():
            continue
        try:
            data = json.loads(summary.read_text(encoding="utf-8"))
            data["_run_dir"] = run_dir.name
            runs.append(data)
        except json.JSONDecodeError:
            continue
        if limit is not None and len(runs) >= limit:
            break
    return runs


def _format_score(x: float | None) -> str:
    return f"{x:.2f}" if isinstance(x, (int, float)) else "—"


def _delta_marker(curr: float | None, prev: float | None) -> str:
    """Up/down arrow with delta magnitude — empty when no prev value to compare."""
    if not isinstance(curr, (int, float)) or not isinstance(prev, (int, float)):
        return ""
    d = curr - prev
    if abs(d) < 0.005:
        return "  ="
    sign = "▲" if d > 0 else "▼"
    return f"  {sign}{abs(d):.2f}"


def render_text(runs: list[dict]) -> str:
    """Format the run history as a plain-text scorecard."""
    if not runs:
        return "No evaluation runs found in evaluation/results/."

    lines: list[str] = []
    lines.append("=" * 78)
    lines.append(" Evaluation regression dashboard")
    lines.append("=" * 78)
    lines.append(f" Runs analysed: {len(runs)}")
    lines.append("")

    # Aggregate trend across runs (newest first)
    lines.append(" Aggregate by run (newest first):")
    lines.append("")
    lines.append(f"   {'run':<24s}  det.avg  judge.avg  cases")
    lines.append(f"   {'-' * 24}  -------  ---------  -----")
    prev_det = prev_judge = None
    for r in runs:
        det = r.get("deterministic_average_across_cases")
        judge = r.get("llm_judge_average_across_cases")
        n = r.get("case_count", 0)
        det_str = _format_score(det) + _delta_marker(det, prev_det)
        judge_str = _format_score(judge) + _delta_marker(judge, prev_judge)
        lines.append(
            f"   {r['_run_dir']:<24s}  {det_str:<13s}  {judge_str:<15s}  {n}"
        )
        prev_det, prev_judge = det, judge

    # Per-case comparison between the two newest runs
    if len(runs) >= 2:
        latest, previous = runs[0], runs[1]
        lines.append("")
        lines.append(" Per-case comparison (latest vs. previous):")
        lines.append("")
        lines.append(f"   {'case':<14s}  curr_det  prev_det   curr_judge  prev_judge")
        lines.append(f"   {'-' * 14}  --------  --------   ----------  ----------")
        prev_by_case = {c["case_id"]: c for c in previous.get("cases", [])}
        for c in latest.get("cases", []):
            cid = c["case_id"]
            pc = prev_by_case.get(cid, {})
            curr_d = c.get("deterministic_average")
            prev_d = pc.get("deterministic_average")
            curr_j = c.get("llm_judge_average")
            prev_j = pc.get("llm_judge_average")
            lines.append(
                f"   {cid:<14s}  {_format_score(curr_d):<8s}  "
                f"{_format_score(prev_d):<8s}   "
                f"{_format_score(curr_j):<10s}  {_format_score(prev_j):<10s}"
                f"{_delta_marker(curr_d, prev_d)}"
            )

        # Regression callouts: any case whose score dropped >= 0.10
        regressions = [
            (c["case_id"], c.get("deterministic_average"),
             prev_by_case.get(c["case_id"], {}).get("deterministic_average"))
            for c in latest.get("cases", [])
        ]
        flagged = [
            (cid, curr, prev) for cid, curr, prev in regressions
            if isinstance(curr, (int, float)) and isinstance(prev, (int, float))
            and (prev - curr) >= 0.10
        ]
        if flagged:
            lines.append("")
            lines.append(" ⚠️  Regressions (deterministic dropped ≥ 0.10):")
            for cid, curr, prev in flagged:
                lines.append(f"     · {cid}: {prev:.2f} → {curr:.2f} (Δ {curr - prev:+.2f})")
        else:
            lines.append("")
            lines.append(" ✓  No deterministic regressions vs. previous run.")

    lines.append("")
    return "\n".join(lines)


def render_markdown(runs: list[dict]) -> str:
    """Markdown variant of the text dashboard — suitable for committing."""
    if not runs:
        return "# Evaluation dashboard\n\n_No runs found._\n"

    md: list[str] = []
    md.append("# Evaluation regression dashboard")
    md.append("")
    md.append(f"Runs analysed: **{len(runs)}** (newest first)\n")

    md.append("## Run history")
    md.append("")
    md.append("| Run | Deterministic avg | LLM-judge avg | Cases |")
    md.append("| --- | --- | --- | --- |")
    for r in runs:
        det = r.get("deterministic_average_across_cases")
        judge = r.get("llm_judge_average_across_cases")
        md.append(
            f"| {r['_run_dir']} | {_format_score(det)} | {_format_score(judge)} "
            f"| {r.get('case_count', 0)} |"
        )

    if len(runs) >= 2:
        latest, previous = runs[0], runs[1]
        prev_by_case = {c["case_id"]: c for c in previous.get("cases", [])}
        md.append("")
        md.append("## Per-case comparison (latest vs. previous)")
        md.append("")
        md.append("| Case | curr det | prev det | curr judge | prev judge | Δ det |")
        md.append("| --- | --- | --- | --- | --- | --- |")
        for c in latest.get("cases", []):
            cid = c["case_id"]
            pc = prev_by_case.get(cid, {})
            curr_d = c.get("deterministic_average")
            prev_d = pc.get("deterministic_average")
            curr_j = c.get("llm_judge_average")
            prev_j = pc.get("llm_judge_average")
            delta = ""
            if isinstance(curr_d, (int, float)) and isinstance(prev_d, (int, float)):
                d = curr_d - prev_d
                delta = f"{d:+.2f}"
            md.append(
                f"| {cid} | {_format_score(curr_d)} | {_format_score(prev_d)} "
                f"| {_format_score(curr_j)} | {_format_score(prev_j)} | {delta} |"
            )

    md.append("")
    return "\n".join(md)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluation regression dashboard.")
    parser.add_argument("--last", type=int, default=None,
                        help="Limit the dashboard to the N most recent runs.")
    parser.add_argument("--md", default=None,
                        help="Also write a markdown report to this path.")
    parser.add_argument("--results-dir", default=str(RESULTS_DIR),
                        help="Override the results directory.")
    parser.add_argument("--fail-on-regression", action="store_true",
                        help="Exit 1 if any case drops >= threshold vs. previous run (CI gate).")
    parser.add_argument("--regression-threshold", type=float, default=0.10,
                        help="Score drop threshold that triggers failure (default: 0.10).")
    args = parser.parse_args()

    runs = _load_runs(Path(args.results_dir), limit=args.last)
    report = render_text(runs)
    print(report)

    if args.md:
        Path(args.md).write_text(render_markdown(runs), encoding="utf-8")
        print(f"\n Markdown report written to: {args.md}")

    # ---- CI gate: exit non-zero on regression ----
    if args.fail_on_regression and len(runs) >= 2:
        curr_run, prev_run = runs[0], runs[1]
        curr_cases = {c["case_id"]: c for c in curr_run.get("cases", [])}
        prev_cases = {c["case_id"]: c for c in prev_run.get("cases", [])}
        regressions = []
        for cid, curr_c in curr_cases.items():
            prev_c = prev_cases.get(cid)
            if not prev_c:
                continue
            curr_score = curr_c.get("score_deterministic")
            prev_score = prev_c.get("score_deterministic")
            if curr_score is None or prev_score is None:
                continue
            drop = prev_score - curr_score
            if drop >= args.regression_threshold:
                regressions.append((cid, prev_score, curr_score, drop))

        if regressions:
            print(f"\n❌ CI GATE FAILED — {len(regressions)} regression(s) "
                  f"≥ {args.regression_threshold:.2f} vs. previous run:")
            for cid, prev_s, curr_s, drop in regressions:
                print(f"   {cid}: {prev_s:.3f} → {curr_s:.3f}  (drop {drop:.3f})")
            print("Fix prompt regressions before merging.\n")
            return 1

        print(f"\n✅ CI gate passed — no regressions ≥ {args.regression_threshold:.2f}.\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
