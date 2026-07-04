"""Single-mega-prompt baseline — the honest "1 agent" comparison point.

This is the implementation the multi-agent argument in `docs/AGENT_DESIGN.md`
and TECHNICAL_DOCUMENT §2.2 is measured against: ONE LLM call that takes the
transcript + wiki + backlog and emits the entire synthesis (topics, epics,
stories, duplicates, conflicts, gaps) in a single shot.

It is scored with the *exact same* deterministic metrics and LLM-as-judge as
the five-agent pipeline (`evaluation/metrics.py`, `evaluation/llm_as_judge.py`),
against the *same* 10 golden cases — so the comparison is apples-to-apples.

Usage:
    python evaluation/single_prompt_baseline.py                 # deterministic only
    python evaluation/single_prompt_baseline.py --use-llm-judge # + qualitative
    python evaluation/single_prompt_baseline.py --case case_07  # one case

Results are written to evaluation/results/single_prompt_<UTC>/summary.json,
mirroring the multi-agent runner's shape so the dashboard can diff them.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

load_dotenv(ROOT / ".env")

from input_loader import load_text, load_tickets  # noqa: E402
from tools.claude_tool import ClaudeTool  # noqa: E402
from metrics import all_metrics  # noqa: E402

GOLDEN_DIR = Path(__file__).resolve().parent / "golden_dataset"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


# The mega-prompt. Deliberately a *fair* attempt — it asks for the same
# structured output the five agents collectively produce, with the same rules
# (canonical tags, Given/When/Then ACs, draft-don't-suppress on conflicts).
# The point of the comparison is not to handicap it, but to show what one
# prompt juggling five reasoning tasks actually produces.
MEGA_PROMPT = """You will be given a meeting transcript, an architecture-constraints wiki, and an existing engineering backlog. In a SINGLE response, perform the entire backlog-synthesis task:

1. Identify the distinct topics raised in the transcript.
2. Extract the architectural constraints from the wiki.
3. Draft a well-formed user story for every topic (do NOT suppress a story just because it conflicts with a constraint — draft it and flag the conflict).
4. Group the stories into epics.
5. Detect duplicates against the existing backlog, conflicts against `must`/`forbidden` constraints, and gaps the source implies but nobody planned.

# Transcript
<transcript>
{TRANSCRIPT}
</transcript>

# Architecture constraints wiki
<wiki>
{WIKI}
</wiki>

# Existing backlog (id, title, description)
<backlog>
{BACKLOG}
</backlog>

# Output
Reply with JSON only (no prose, no fences), of exactly this shape:
{{
  "summary": "2-4 sentence overview",
  "topics": [{{"id": "T-01", "theme": "kebab-label", "summary": "...", "raw_quote": "verbatim or close paraphrase", "speaker": "name or null", "sentiment": "concern|request|observation|praise"}}],
  "epics": [{{
    "id": "EP-01", "title": "...", "description": "...",
    "stories": [{{
      "id": "ST-01", "title": "...", "description": "...",
      "user_story": "As a <persona>, I want <capability>, so that <benefit>.",
      "acceptance_criteria": ["Given <context>, when <action>, then <observable outcome>."],
      "priority": "High|Medium|Low",
      "priority_rationale": "concrete, non-empty sentence",
      "tags": ["telemetry", "offline-mode"],
      "source_topic_id": "T-01"
    }}]
  }}],
  "duplicates": [{{"story_id": "ST-01", "existing_id": "AD-123", "confidence": "high|medium|low", "reason": "one sentence"}}],
  "conflicts": [{{"story_id": "ST-01", "with": "C-01", "severity": "high|medium|low", "reason": "one sentence"}}],
  "gaps": [{{"id": "G-01", "title": "...", "description": "...", "evidence": "one grounded sentence"}}]
}}

Rules: 2-5 testable Given/When/Then acceptance criteria per story; canonical tags (mobile-app, tv-app, device-updates, telemetry, subscription, partner-portal, downloads, discovery, remote-playback, enterprise, payments, offline-mode, accessibility, performance, security, compliance); be conservative — do not invent work not grounded in the source. If a topic list would be empty, return empty arrays."""


def _slim_backlog(tickets: list[dict]) -> str:
    rows = []
    for t in tickets:
        tid = t.get("id") or t.get("key") or f"#{t.get('number', '?')}"
        title = t.get("title") or t.get("summary") or ""
        desc = (t.get("description") or t.get("body") or "")[:240]
        rows.append(f"- {tid}: {title} — {desc}")
    return "\n".join(rows)


def run_single_prompt(transcript: str, wiki: str, tickets: list[dict]) -> dict:
    """One LLM call producing the full synthesis dict."""
    tool = ClaudeTool()
    prompt = (
        MEGA_PROMPT
        .replace("{TRANSCRIPT}", transcript)
        .replace("{WIKI}", wiki or "(none provided)")
        .replace("{BACKLOG}", _slim_backlog(tickets) or "(none provided)")
    )
    # Generous single-call budget so the baseline isn't unfairly truncated.
    # (The 5-agent pipeline effectively gets far more — 4000-8000 tokens per
    # stage across five calls — so this keeps the comparison fair.)
    parsed, _usage = tool.call_for_json(prompt, max_tokens=16000)
    # Guarantee the keys metrics.py reads, even if the model omitted some.
    for k in ("topics", "epics", "duplicates", "conflicts", "gaps"):
        parsed.setdefault(k, [])
    parsed.setdefault("summary", "")
    return parsed


def score_case(case_id: str, *, use_llm_judge: bool) -> dict:
    case_input = json.loads((GOLDEN_DIR / f"{case_id}_input.json").read_text())
    expected = json.loads((GOLDEN_DIR / f"{case_id}_expected.json").read_text())

    print(f"\n{'=' * 70}\n Case: {case_id} (single-prompt baseline)\n{'=' * 70}")

    transcript = load_text(str(ROOT / case_input["transcript_path"]))
    wiki = load_text(str(ROOT / case_input["constraints_path"])) if case_input.get("constraints_path") else ""
    tickets = load_tickets(str(ROOT / case_input["backlog_path"])) if case_input.get("backlog_path") else []

    try:
        synthesis = run_single_prompt(transcript, wiki, tickets)
    except Exception as e:  # noqa: BLE001 — a parse/JSON failure is itself a baseline result
        print(f" [single-prompt run failed: {e}] — scoring as empty synthesis")
        synthesis = {"summary": "", "topics": [], "epics": [], "duplicates": [], "conflicts": [], "gaps": []}

    metric_results = all_metrics(synthesis, expected)
    det_avg = sum(m.score for m in metric_results) / max(1, len(metric_results))
    print(" Deterministic metrics:")
    for m in metric_results:
        print(f"   {m.name:42s} {m.score:.2f}")
    print(f" Deterministic average: {det_avg:.2f}")

    judge_dict = None
    judge_avg = None
    if use_llm_judge:
        try:
            from llm_as_judge import judge
            jr = judge(synthesis)
            judge_dict = jr.to_dict()
            judge_avg = jr.average_normalized
            print(f" Judge average (normalised): {judge_avg:.2f}")
        except Exception as e:  # noqa: BLE001
            print(f" [warn] judge skipped: {e}")

    return {
        "case_id": case_id,
        "deterministic_average": det_avg,
        "llm_judge_average": judge_avg,
        "synthesis_summary": {
            "epic_count": len(synthesis.get("epics", [])),
            "story_count": sum(len(e.get("stories", [])) for e in synthesis.get("epics", [])),
            "duplicates": len(synthesis.get("duplicates", [])),
            "conflicts": len(synthesis.get("conflicts", [])),
            "gaps": len(synthesis.get("gaps", [])),
        },
        "llm_judge": judge_dict,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Single-mega-prompt baseline over the golden suite.")
    ap.add_argument("--case", default=None, help="Run one case (e.g. case_07); default: all")
    ap.add_argument("--use-llm-judge", action="store_true")
    ap.add_argument("--no-save-results", action="store_true")
    args = ap.parse_args()

    cases = ([args.case] if args.case
             else sorted(p.stem.replace("_input", "") for p in GOLDEN_DIR.glob("*_input.json")))

    results = [score_case(c, use_llm_judge=args.use_llm_judge) for c in cases]

    det_avg = sum(r["deterministic_average"] for r in results) / max(1, len(results))
    judged = [r["llm_judge_average"] for r in results if r["llm_judge_average"] is not None]
    judge_avg = sum(judged) / len(judged) if judged else None

    print(f"\n{'=' * 70}")
    print(f" SINGLE-PROMPT BASELINE — {len(results)} cases")
    print(f"   deterministic average: {det_avg:.3f}")
    if judge_avg is not None:
        print(f"   LLM-judge average:     {judge_avg:.3f}")
    print("=" * 70)

    if not args.no_save_results:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = RESULTS_DIR / f"single_prompt_{ts}"
        out_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "timestamp_utc": ts,
            "variant": "single_prompt_baseline",
            "use_llm_judge": args.use_llm_judge,
            "case_count": len(results),
            "deterministic_average_across_cases": round(det_avg, 4),
            "llm_judge_average_across_cases": round(judge_avg, 4) if judge_avg is not None else None,
            "cases": results,
        }
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        print(f" Saved → {out_dir}/summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
