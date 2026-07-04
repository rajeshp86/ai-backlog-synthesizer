"""Evaluation runner — loads golden cases, runs the synthesizer, scores results.

Usage:
    python evaluation/run_evaluation.py [--case case_01] [--use-llm-judge]
                                        [--save-results] [--results-dir DIR]

Reads:
  - evaluation/golden_dataset/case_*_input.json   (input pointers)
  - evaluation/golden_dataset/case_*_expected.json (assertions to score against)

For each case:
  1. Runs the multi-agent orchestrator on the case inputs
  2. Scores the result with deterministic metrics (metrics.py)
  3. Optionally scores qualitative dimensions with an LLM-as-judge (llm_as_judge.py)
  4. Prints a per-case scorecard and an aggregate

When `--save-results` is set (default true), the per-case scorecards
and an aggregate summary are written to
`evaluation/results/<timestamp>/` so the run is reviewable later.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT / "src"))

from input_loader import load_text, load_tickets  # noqa: E402
from pipeline import Orchestrator  # noqa: E402

# Local imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from metrics import all_metrics  # noqa: E402


GOLDEN_DIR = Path(__file__).resolve().parent / "golden_dataset"
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"


def list_cases() -> list[str]:
    return sorted(p.stem.replace("_input", "") for p in GOLDEN_DIR.glob("*_input.json"))


def run_case(case_id: str, *, use_llm_judge: bool = False,
             orchestrator: Orchestrator | None = None) -> dict:
    """Run one golden case end-to-end and score it.

    `orchestrator` is injectable so tests can pass an Orchestrator wired
    to a FakeClaudeTool; production callers leave it None and get a real
    one.
    """
    input_path = GOLDEN_DIR / f"{case_id}_input.json"
    expected_path = GOLDEN_DIR / f"{case_id}_expected.json"

    if not input_path.exists() or not expected_path.exists():
        raise FileNotFoundError(f"Missing fixtures for {case_id}")

    case_input = json.loads(input_path.read_text())
    expected = json.loads(expected_path.read_text())

    print(f"\n{'=' * 70}")
    print(f" Case: {case_id}")
    print(f" Description: {case_input.get('description', '')}")
    print("=" * 70)

    # Load inputs
    transcript_text = load_text(str(ROOT / case_input["transcript_path"]))
    constraint_text = ""
    if case_input.get("constraints_path"):
        constraint_text = load_text(str(ROOT / case_input["constraints_path"]))
    existing_tickets: list[dict] = []
    if case_input.get("backlog_path"):
        existing_tickets = load_tickets(str(ROOT / case_input["backlog_path"]))

    # Run the synthesizer
    orch = orchestrator or Orchestrator()
    synthesis = orch.run(
        transcript_text=transcript_text,
        constraint_text=constraint_text,
        existing_tickets=existing_tickets,
    )

    # Score with deterministic metrics
    metric_results = all_metrics(synthesis, expected)

    print("\n Deterministic metrics:")
    total_score = 0.0
    for m in metric_results:
        bar = "█" * int(m.score * 20) + "░" * (20 - int(m.score * 20))
        print(f"   {m.name:42s} {bar} {m.score:.2f}")
        for obs in m.observations:
            print(f"     · {obs}")
        total_score += m.score
    avg_score = total_score / max(1, len(metric_results))
    print(f"\n Deterministic average: {avg_score:.2f}")

    # Optional LLM-as-judge
    judge_result_dict: dict | None = None
    if use_llm_judge:
        try:
            from llm_as_judge import judge
            judge_result = judge(synthesis)
            judge_result_dict = judge_result.to_dict()
            print("\n LLM-as-judge scores (1-5, normalised 0-1):")
            for dim in judge_result.scores:
                score = judge_result.scores[dim]
                norm = judge_result.normalized.get(dim, 0.0)
                reason = judge_result.reasons.get(dim, "")
                print(f"   {dim:30s} {score}/5  ({norm:.2f})  — {reason}")
            print(f"\n Judge average (normalised): {judge_result.average_normalized:.2f}")
            print(f" Overall: {judge_result.overall_comment}")
        except Exception as e:  # noqa: BLE001 — judge failures shouldn't kill the run
            print(f"\n [warn] LLM-as-judge skipped: {e}")

    return {
        "case_id": case_id,
        "description": case_input.get("description", ""),
        "deterministic_average": avg_score,
        "deterministic_metrics": [
            {"name": m.name, "score": m.score, "observations": m.observations}
            for m in metric_results
        ],
        "llm_judge": judge_result_dict,
        "synthesis_summary": {
            "epic_count": len(synthesis.get("epics", [])),
            "story_count": sum(len(e.get("stories", [])) for e in synthesis.get("epics", [])),
            "duplicates": len(synthesis.get("duplicates", [])),
            "conflicts": len(synthesis.get("conflicts", [])),
            "gaps": len(synthesis.get("gaps", [])),
        },
    }


def _save_results(results: list[dict], *, use_llm_judge: bool, results_dir: Path) -> Path:
    """Persist a run's per-case results + aggregate summary to disk.

    Layout:
        <results_dir>/<UTC timestamp>/
            summary.json          aggregate + per-case scores
            case_<id>.json        full per-case detail (one per case)
            README.md             human-readable scorecard

    Returns the directory written to.
    """
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_dir = results_dir / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    # Per-case detail files
    for r in results:
        (out_dir / f"{r['case_id']}.json").write_text(json.dumps(r, indent=2))

    # Aggregate summary
    if results:
        det_avg = sum(r["deterministic_average"] for r in results) / len(results)
        judge_results = [r for r in results if r.get("llm_judge")]
        judge_avg = (
            sum(r["llm_judge"]["average_normalized"] for r in judge_results)
            / len(judge_results)
        ) if judge_results else None
    else:
        det_avg = 0.0
        judge_avg = None

    summary = {
        "timestamp_utc": timestamp,
        "use_llm_judge": use_llm_judge,
        "case_count": len(results),
        "deterministic_average_across_cases": round(det_avg, 4),
        "llm_judge_average_across_cases": (round(judge_avg, 4) if judge_avg is not None else None),
        "cases": [
            {
                "case_id": r["case_id"],
                "deterministic_average": round(r["deterministic_average"], 4),
                "llm_judge_average": (
                    round(r["llm_judge"]["average_normalized"], 4)
                    if r.get("llm_judge") else None
                ),
                "synthesis_summary": r.get("synthesis_summary", {}),
            }
            for r in results
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    # Human-readable scorecard
    lines = [
        f"# Evaluation run — {timestamp}",
        "",
        f"- Cases evaluated: **{len(results)}**",
        f"- LLM-as-judge enabled: **{use_llm_judge}**",
        f"- Deterministic average across cases: **{det_avg:.2f}**",
    ]
    if judge_avg is not None:
        lines.append(f"- LLM-as-judge average across cases (normalised): **{judge_avg:.2f}**")
    lines += ["", "## Per-case scores", "", "| Case | Deterministic | LLM judge | Epics | Stories | Dupes | Conflicts | Gaps |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in results:
        s = r.get("synthesis_summary", {})
        judge_cell = (
            f"{r['llm_judge']['average_normalized']:.2f}" if r.get("llm_judge") else "—"
        )
        lines.append(
            f"| {r['case_id']} | {r['deterministic_average']:.2f} | {judge_cell} | "
            f"{s.get('epic_count', 0)} | {s.get('story_count', 0)} | "
            f"{s.get('duplicates', 0)} | {s.get('conflicts', 0)} | {s.get('gaps', 0)} |"
        )
    (out_dir / "README.md").write_text("\n".join(lines) + "\n")

    return out_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default=None, help="Run a specific case (default: all)")
    parser.add_argument("--use-llm-judge", action="store_true",
                        help="Also run LLM-as-judge for qualitative scoring")
    parser.add_argument("--save-results", dest="save_results", action="store_true",
                        default=True, help="Save results to evaluation/results/ (default)")
    parser.add_argument("--no-save-results", dest="save_results", action="store_false",
                        help="Skip writing result files")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR),
                        help="Directory under which to save results")
    args = parser.parse_args()

    cases = [args.case] if args.case else list_cases()
    if not cases:
        print("No cases found in evaluation/golden_dataset/", file=sys.stderr)
        return 1

    results = []
    for case_id in cases:
        try:
            results.append(run_case(case_id, use_llm_judge=args.use_llm_judge))
        except Exception as e:  # noqa: BLE001
            print(f"\n[error] Case {case_id} failed: {e}", file=sys.stderr)

    if len(results) > 1:
        print("\n" + "=" * 70)
        print(" Aggregate")
        print("=" * 70)
        for r in results:
            judge_cell = (
                f"  judge {r['llm_judge']['average_normalized']:.2f}"
                if r.get("llm_judge") else ""
            )
            print(f"   {r['case_id']:20s} {r['deterministic_average']:.2f}{judge_cell}")

    if args.save_results and results:
        out_dir = _save_results(results, use_llm_judge=args.use_llm_judge,
                                results_dir=Path(args.results_dir))
        print(f"\n Results saved to: {out_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
