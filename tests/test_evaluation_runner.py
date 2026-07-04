"""Tests for `evaluation/run_evaluation.py` + `evaluation/dashboard.py`.

The evaluation runner orchestrates: load case fixtures → run the
orchestrator → score with metrics → optionally call LLM-as-judge →
persist results. Tests cover:

  1. `list_cases` discovers every `case_*_input.json` in the golden dir
  2. `run_case` returns the expected score-shape dict
  3. `_save_results` writes the documented directory structure
  4. The LLM-as-judge result is normalised correctly
  5. Dashboard `_load_runs` reads timestamps and orders newest-first
  6. Dashboard regression detection fires when a score drops ≥ 0.10
  7. The dashboard's text + markdown render don't crash on edge cases
     (no runs, one run, identical runs)

The orchestrator and judge are mocked — these tests are deterministic
and run offline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evaluation"))


# --------------------------------------------------------------- list_cases


def test_list_cases_returns_sorted_unique_ids():
    """The bundled golden dataset has cases case_01 … case_10; the helper
    must return them in lexicographic order."""
    import run_evaluation as runner
    cases = runner.list_cases()
    assert len(cases) >= 4   # was 4 at submission; we added 6 more → 10
    assert cases == sorted(cases)
    # Spot-check that the known cases are visible.
    for cid in ("case_01", "case_04"):
        assert cid in cases


# --------------------------------------------------------------- run_case


class _FakeOrchestrator:
    """Stand-in for `Orchestrator` that returns a fixed synthesis dict."""

    def __init__(self, response: dict | None = None):
        self.response = response or {
            "summary": "Test",
            "topics": [],
            "constraints": [],
            "epics": [
                {"id": "EP-01", "title": "E1", "stories": [
                    {"id": "ST-01", "title": "S1",
                     "acceptance_criteria": ["Given X, when Y, then Z.",
                                              "Given A, when B, then C."],
                     "priority": "High",
                     "priority_rationale": "Critical for Q3.",
                     "tags": ["telemetry"]},
                ]},
            ],
            "gaps": [], "conflicts": [], "duplicates": [],
            "audit_trail": "# Audit",
            "token_usage": {"total": {"input": 100, "output": 50}},
            "model": "fake", "models": {},
        }
        self.calls: list[dict] = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_run_case_returns_expected_shape(monkeypatch):
    """A successful case run produces a dict with deterministic scores +
    a synthesis_summary block — even when llm_judge is off."""
    import run_evaluation as runner

    fake_orch = _FakeOrchestrator()
    monkeypatch.setattr(runner, "Orchestrator", lambda: fake_orch)

    result = runner.run_case("case_01", use_llm_judge=False)

    assert result["case_id"] == "case_01"
    assert isinstance(result["deterministic_average"], float)
    assert 0.0 <= result["deterministic_average"] <= 1.0
    assert isinstance(result["deterministic_metrics"], list)
    assert all("name" in m and "score" in m for m in result["deterministic_metrics"])
    assert result["llm_judge"] is None
    assert "synthesis_summary" in result
    assert "epic_count" in result["synthesis_summary"]


def test_run_case_invokes_llm_judge_when_enabled(monkeypatch):
    """With `use_llm_judge=True` and a successful judge call, the
    `llm_judge` field carries the normalised result dict."""
    import run_evaluation as runner

    fake_orch = _FakeOrchestrator()
    monkeypatch.setattr(runner, "Orchestrator", lambda: fake_orch)

    from llm_as_judge import JudgeResult

    fake_judge = JudgeResult(
        scores={"ac_quality": 5, "priority_justification": 4,
                "story_granularity": 4, "tag_accuracy": 5,
                "conflict_reasoning": 3},
        reasons={"ac_quality": "x", "priority_justification": "y",
                 "story_granularity": "z", "tag_accuracy": "w",
                 "conflict_reasoning": "v"},
        overall_comment="Solid.",
    )
    fake_judge.normalized = {k: (s - 1) / 4 for k, s in fake_judge.scores.items()}
    fake_judge.average_normalized = sum(fake_judge.normalized.values()) / 5

    with patch("llm_as_judge.judge", return_value=fake_judge):
        result = runner.run_case("case_01", use_llm_judge=True)

    assert result["llm_judge"] is not None
    assert "scores" in result["llm_judge"]
    assert result["llm_judge"]["scores"]["ac_quality"] == 5


def test_run_case_judge_failure_is_non_fatal(monkeypatch):
    """If the judge call raises (no API key, model error), the run
    continues and `llm_judge` is None. The deterministic score still
    lands."""
    import run_evaluation as runner

    fake_orch = _FakeOrchestrator()
    monkeypatch.setattr(runner, "Orchestrator", lambda: fake_orch)

    with patch("llm_as_judge.judge", side_effect=RuntimeError("no API key")):
        result = runner.run_case("case_01", use_llm_judge=True)

    assert result["case_id"] == "case_01"
    assert result["llm_judge"] is None
    assert isinstance(result["deterministic_average"], float)


def test_run_case_missing_fixture_raises():
    """Asking for a case that doesn't exist should fail loudly, not
    silently return zeros."""
    import run_evaluation as runner
    with pytest.raises(FileNotFoundError):
        runner.run_case("case_does_not_exist")


# --------------------------------------------------------------- _save_results


def test_save_results_writes_directory_structure(tmp_path):
    """The runner persists every case + a summary + a markdown scorecard
    under <results_dir>/<timestamp>/. Verifies the documented layout."""
    import run_evaluation as runner

    fake_results = [
        {
            "case_id": "case_01",
            "deterministic_average": 0.85,
            "deterministic_metrics": [],
            "llm_judge": None,
            "synthesis_summary": {"epic_count": 2, "story_count": 4,
                                  "duplicates": 0, "conflicts": 1, "gaps": 2},
        },
        {
            "case_id": "case_02",
            "deterministic_average": 0.6,
            "deterministic_metrics": [],
            "llm_judge": {"average_normalized": 0.7},
            "synthesis_summary": {"epic_count": 1, "story_count": 2,
                                  "duplicates": 1, "conflicts": 0, "gaps": 1},
        },
    ]

    out_dir = runner._save_results(
        fake_results, use_llm_judge=True, results_dir=tmp_path
    )
    assert out_dir.exists()
    # Per-case files
    assert (out_dir / "case_01.json").exists()
    assert (out_dir / "case_02.json").exists()
    # Aggregate files
    assert (out_dir / "summary.json").exists()
    assert (out_dir / "README.md").exists()

    # Summary contents check
    summary = json.loads((out_dir / "summary.json").read_text())
    assert summary["case_count"] == 2
    assert summary["use_llm_judge"] is True
    # Deterministic average across cases = (0.85 + 0.6) / 2 = 0.725
    assert summary["deterministic_average_across_cases"] == pytest.approx(0.725, abs=1e-3)
    # LLM-judge average across cases — only the case that had a judge entry counts.
    assert summary["llm_judge_average_across_cases"] == pytest.approx(0.7, abs=1e-3)


def test_save_results_with_no_judge_results(tmp_path):
    """When no case had an LLM-judge result, the summary's judge
    average is None (not 0.0 — those are different signals)."""
    import run_evaluation as runner
    out = runner._save_results(
        [{"case_id": "case_01", "deterministic_average": 0.5,
          "deterministic_metrics": [], "llm_judge": None,
          "synthesis_summary": {}}],
        use_llm_judge=False, results_dir=tmp_path,
    )
    summary = json.loads((out / "summary.json").read_text())
    assert summary["llm_judge_average_across_cases"] is None


# --------------------------------------------------------------- dashboard


def _write_run(results_dir: Path, timestamp: str, det_avg: float,
               judge_avg: float | None = None, per_case: list | None = None) -> Path:
    """Helper: write a fake `summary.json` to results_dir/<timestamp>/."""
    run_dir = results_dir / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "timestamp_utc": timestamp,
        "use_llm_judge": judge_avg is not None,
        "case_count": len(per_case) if per_case else 1,
        "deterministic_average_across_cases": det_avg,
        "llm_judge_average_across_cases": judge_avg,
        "cases": per_case or [{
            "case_id": "case_01",
            "deterministic_average": det_avg,
            "llm_judge_average": judge_avg,
            "synthesis_summary": {"epic_count": 1, "story_count": 1,
                                  "duplicates": 0, "conflicts": 0, "gaps": 0},
        }],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary))
    return run_dir


def test_dashboard_load_runs_returns_newest_first(tmp_path):
    """`_load_runs` should sort by directory name descending (timestamps
    are ISO-ish strings so lex sort == chronological sort)."""
    import dashboard

    _write_run(tmp_path, "20260101T000000Z", 0.7)
    _write_run(tmp_path, "20260201T000000Z", 0.8)
    _write_run(tmp_path, "20260301T000000Z", 0.9)

    runs = dashboard._load_runs(tmp_path)
    assert len(runs) == 3
    # Newest first
    assert runs[0]["_run_dir"] == "20260301T000000Z"
    assert runs[2]["_run_dir"] == "20260101T000000Z"


def test_dashboard_load_runs_honours_limit(tmp_path):
    import dashboard

    for ts in ("20260101T000000Z", "20260201T000000Z", "20260301T000000Z"):
        _write_run(tmp_path, ts, 0.5)
    runs = dashboard._load_runs(tmp_path, limit=2)
    assert len(runs) == 2


def test_dashboard_load_runs_empty_dir(tmp_path):
    """Empty results dir should return an empty list, not crash."""
    import dashboard
    runs = dashboard._load_runs(tmp_path)
    assert runs == []


def test_dashboard_text_render_handles_no_runs():
    import dashboard
    out = dashboard.render_text([])
    assert "No evaluation runs found" in out


def test_dashboard_text_render_shows_aggregate_table(tmp_path):
    import dashboard

    _write_run(tmp_path, "20260101T000000Z", 0.6, judge_avg=0.5)
    _write_run(tmp_path, "20260201T000000Z", 0.8, judge_avg=0.7)
    runs = dashboard._load_runs(tmp_path)

    out = dashboard.render_text(runs)
    assert "Aggregate by run" in out
    assert "20260201T000000Z" in out
    assert "20260101T000000Z" in out
    # The improvement should show as an up-arrow on the newest row.
    assert "▲" in out or "+" in out


def test_dashboard_flags_regressions_above_threshold(tmp_path):
    """A per-case score drop ≥ 0.10 should trigger the regression callout."""
    import dashboard

    _write_run(tmp_path, "20260101T000000Z", 0.9, judge_avg=0.7, per_case=[
        {"case_id": "case_01", "deterministic_average": 0.9, "llm_judge_average": 0.7,
         "synthesis_summary": {}},
    ])
    _write_run(tmp_path, "20260201T000000Z", 0.7, judge_avg=0.7, per_case=[
        {"case_id": "case_01", "deterministic_average": 0.7, "llm_judge_average": 0.7,
         "synthesis_summary": {}},
    ])
    runs = dashboard._load_runs(tmp_path)

    out = dashboard.render_text(runs)
    assert "Regression" in out or "regression" in out.lower()
    assert "case_01" in out


def test_dashboard_no_regression_when_within_tolerance(tmp_path):
    """A drop under 0.10 should NOT trigger the regression callout."""
    import dashboard

    _write_run(tmp_path, "20260101T000000Z", 0.85, per_case=[
        {"case_id": "case_01", "deterministic_average": 0.85,
         "llm_judge_average": None, "synthesis_summary": {}},
    ])
    _write_run(tmp_path, "20260201T000000Z", 0.80, per_case=[
        {"case_id": "case_01", "deterministic_average": 0.80,
         "llm_judge_average": None, "synthesis_summary": {}},
    ])
    runs = dashboard._load_runs(tmp_path)
    out = dashboard.render_text(runs)
    assert "No deterministic regressions" in out


def test_dashboard_markdown_render_returns_string(tmp_path):
    """Markdown render should produce a string with the expected table
    header — sanity check, not a full template match."""
    import dashboard

    _write_run(tmp_path, "20260101T000000Z", 0.7)
    runs = dashboard._load_runs(tmp_path)
    md = dashboard.render_markdown(runs)
    assert "# Evaluation regression dashboard" in md
    assert "| Run |" in md
