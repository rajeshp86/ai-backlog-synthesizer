"""Deterministic metrics for evaluating a synthesis run against expectations.

Each metric returns a float in [0, 1] (1 = perfect) plus a list of
human-readable observations. The runner aggregates these and reports.

Metrics implemented:
  - story_count_in_range
  - acceptance_criteria_well_formed
  - required_topics_present
  - forbidden_topics_absent
  - expected_duplicates_found
  - expected_constraint_conflicts_found  (recall — did we catch real ones?)
  - conflict_detection_precision         (precision — were the flags trustworthy?)
  - conflict_detection_f1                (F1 — harmonic mean of recall + precision)

A separate LLM-as-judge evaluator (see `llm_as_judge.py`, skeleton only)
handles qualitative aspects like "are the acceptance criteria genuinely
testable" that don't reduce to a keyword check.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MetricResult:
    name: str
    score: float  # 0.0–1.0
    observations: list[str]


def all_metrics(synthesis: dict, expected: dict) -> list[MetricResult]:
    """Run every deterministic metric and return their results."""
    return [
        story_count_in_range(synthesis, expected),
        acceptance_criteria_well_formed(synthesis, expected),
        required_topics_present(synthesis, expected),
        forbidden_topics_absent(synthesis, expected),
        expected_duplicates_found(synthesis, expected),
        expected_constraint_conflicts_found(synthesis, expected),
        conflict_detection_precision(synthesis, expected),
        conflict_detection_f1(synthesis, expected),
    ]


# ----------------------------------------------------- individual metrics

def story_count_in_range(synthesis: dict, expected: dict) -> MetricResult:
    """Total story count should be within an inclusive range."""
    epics = synthesis.get("epics", [])
    total_stories = sum(len(e.get("stories", [])) for e in epics)

    min_n = expected.get("expected_minimum_story_count", 1)
    max_n = expected.get("expected_maximum_story_count", 20)

    if min_n <= total_stories <= max_n:
        return MetricResult(
            "story_count_in_range",
            1.0,
            [f"OK: {total_stories} stories in [{min_n}, {max_n}]"],
        )
    return MetricResult(
        "story_count_in_range",
        0.0,
        [f"FAIL: {total_stories} stories outside [{min_n}, {max_n}]"],
    )


def acceptance_criteria_well_formed(synthesis: dict, expected: dict) -> MetricResult:
    """Every story should have AC count within [min, max]."""
    min_ac = expected.get("expected_story_acceptance_criteria_min", 2)
    max_ac = expected.get("expected_story_acceptance_criteria_max", 7)

    epics = synthesis.get("epics", [])
    stories = [s for e in epics for s in e.get("stories", [])]
    if not stories:
        return MetricResult("acceptance_criteria_well_formed", 0.0, ["No stories to check"])

    well_formed = 0
    observations = []
    for s in stories:
        ac = s.get("acceptance_criteria", [])
        if min_ac <= len(ac) <= max_ac:
            well_formed += 1
        else:
            observations.append(
                f"Story `{s.get('id', '?')}` has {len(ac)} AC, expected [{min_ac}, {max_ac}]"
            )
    score = well_formed / len(stories)
    observations.insert(0, f"{well_formed}/{len(stories)} stories have AC count in range")
    return MetricResult("acceptance_criteria_well_formed", score, observations)


def required_topics_present(synthesis: dict, expected: dict) -> MetricResult:
    """Every required-topic keyword set should match at least one parsed topic."""
    required = expected.get("required_topics", [])
    if not required:
        return MetricResult("required_topics_present", 1.0, ["No required topics specified"])

    topics_text = _all_topics_text(synthesis)
    matched = 0
    observations = []
    for req in required:
        keywords = [k.lower() for k in req.get("theme_keywords", [])]
        # Require ALL keywords from the set to appear somewhere in topics text
        if all(k in topics_text for k in keywords):
            matched += 1
        else:
            observations.append(f"Missing topic for keywords: {keywords}")
    score = matched / len(required)
    observations.insert(0, f"{matched}/{len(required)} required topics found")
    return MetricResult("required_topics_present", score, observations)


def forbidden_topics_absent(synthesis: dict, expected: dict) -> MetricResult:
    """No forbidden-topic keyword set should appear in any topic / story title."""
    forbidden = expected.get("forbidden_topics", [])
    if not forbidden:
        return MetricResult("forbidden_topics_absent", 1.0, ["No forbidden topics specified"])

    haystack = _all_topics_text(synthesis) + " " + _all_story_titles(synthesis).lower()
    violations = 0
    observations = []
    for f in forbidden:
        keywords = [k.lower() for k in f.get("theme_keywords", [])]
        if any(k in haystack for k in keywords):
            violations += 1
            observations.append(f"Forbidden topic appeared: {keywords}")
    score = 1.0 if violations == 0 else max(0.0, 1.0 - violations / len(forbidden))
    observations.insert(0, f"{violations} forbidden topic violations of {len(forbidden)} checked")
    return MetricResult("forbidden_topics_absent", score, observations)


def expected_duplicates_found(synthesis: dict, expected: dict) -> MetricResult:
    """Each expected duplicate should appear in synthesis.duplicates with sufficient confidence."""
    expected_dupes = expected.get("expected_duplicates", [])
    if not expected_dupes:
        return MetricResult("expected_duplicates_found", 1.0, ["No expected duplicates"])

    found_dupes = synthesis.get("duplicates", [])
    matched = 0
    observations = []
    confidence_rank = {"low": 0, "medium": 1, "high": 2}

    for exp in expected_dupes:
        expected_id = exp.get("existing_id")
        min_conf = confidence_rank.get(exp.get("min_confidence", "low"), 0)
        keywords = [k.lower() for k in exp.get("story_theme", [])]

        candidate_matches = [
            d for d in found_dupes
            if d.get("existing_id") == expected_id
            and confidence_rank.get(d.get("confidence", "low"), 0) >= min_conf
        ]
        # If the existing_id matched, also verify the story has relevant keywords
        if candidate_matches and _story_has_keywords(synthesis, candidate_matches[0].get("story_id", ""), keywords):
            matched += 1
        else:
            observations.append(
                f"Expected duplicate ({keywords} ↔ {expected_id}) not found at confidence ≥ {exp.get('min_confidence', 'low')}"
            )
    score = matched / len(expected_dupes)
    observations.insert(0, f"{matched}/{len(expected_dupes)} expected duplicates found")
    return MetricResult("expected_duplicates_found", score, observations)


def expected_constraint_conflicts_found(synthesis: dict, expected: dict) -> MetricResult:
    """For each expected-conflict pattern, at least one matching conflict should appear."""
    expected_conflicts = expected.get("expected_constraint_conflicts", [])
    if not expected_conflicts:
        return MetricResult("expected_constraint_conflicts_found", 1.0, ["No expected conflicts"])

    found_conflicts = synthesis.get("conflicts", [])
    matched = 0
    observations = []

    for exp in expected_conflicts:
        keywords = [k.lower() for k in exp.get("story_keywords", [])]
        # Check if any conflict's referenced story title contains all the keywords
        any_match = any(
            _story_has_keywords(synthesis, c.get("story_id", ""), keywords)
            for c in found_conflicts
        )
        if any_match:
            matched += 1
        else:
            observations.append(f"Expected conflict for story keywords {keywords} not flagged")
    score = matched / len(expected_conflicts)
    observations.insert(0, f"{matched}/{len(expected_conflicts)} expected conflicts flagged")
    return MetricResult("expected_constraint_conflicts_found", score, observations)


def conflict_detection_precision(synthesis: dict, expected: dict) -> MetricResult:
    """Of every conflict the AI flagged, how many were actually expected?

    Answers the "crying wolf" question: a low precision means the AI is
    raising false alarms that waste the team's time.

    Score = correctly_flagged / total_flagged_by_ai
    If the AI flagged nothing, score = 1.0 (no false alarms, but recall
    may be 0 — see conflict_detection_f1 for the combined view).
    """
    expected_conflicts = expected.get("expected_constraint_conflicts", [])
    found_conflicts = synthesis.get("conflicts", [])

    if not found_conflicts:
        return MetricResult(
            "conflict_detection_precision",
            1.0,
            ["AI flagged 0 conflicts — no false alarms (but recall may be 0)"],
        )

    correctly_flagged = 0
    false_alarms = []

    for fc in found_conflicts:
        story_id = fc.get("story_id", "")
        # A flagged conflict is "correct" if it matches at least one expected pattern
        is_expected = any(
            _story_has_keywords(
                synthesis, story_id, [k.lower() for k in exp.get("story_keywords", [])]
            )
            for exp in expected_conflicts
        )
        if is_expected:
            correctly_flagged += 1
        else:
            false_alarms.append(f"Unexpected conflict flagged for story `{story_id}`")

    score = correctly_flagged / len(found_conflicts)
    observations = [
        f"{correctly_flagged}/{len(found_conflicts)} flagged conflicts matched expected patterns"
    ] + false_alarms
    return MetricResult("conflict_detection_precision", score, observations)


def conflict_detection_f1(synthesis: dict, expected: dict) -> MetricResult:
    """Harmonic mean of conflict recall and precision.

    F1 = 2 * (precision * recall) / (precision + recall)

    Catches both failure modes:
      - Recall = 0 → missed real conflicts (dangerous)
      - Precision = 0 → pure noise, no real conflicts found (wasteful)
    Score = 0 if either is 0; score = 1 only when both are perfect.
    """
    expected_conflicts = expected.get("expected_constraint_conflicts", [])
    found_conflicts = synthesis.get("conflicts", [])

    if not expected_conflicts and not found_conflicts:
        return MetricResult("conflict_detection_f1", 1.0, ["No conflicts expected or flagged"])

    # Recall: expected conflicts that were caught
    if expected_conflicts:
        recall_matched = sum(
            1
            for exp in expected_conflicts
            if any(
                _story_has_keywords(
                    synthesis,
                    fc.get("story_id", ""),
                    [k.lower() for k in exp.get("story_keywords", [])],
                )
                for fc in found_conflicts
            )
        )
        recall = recall_matched / len(expected_conflicts)
    else:
        recall = 1.0
        recall_matched = 0

    # Precision: flagged conflicts that were actually expected
    if found_conflicts:
        precision_matched = sum(
            1
            for fc in found_conflicts
            if any(
                _story_has_keywords(
                    synthesis,
                    fc.get("story_id", ""),
                    [k.lower() for k in exp.get("story_keywords", [])],
                )
                for exp in expected_conflicts
            )
        )
        precision = precision_matched / len(found_conflicts)
    else:
        precision = 1.0
        precision_matched = 0

    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    observations = [
        f"F1 {f1:.2f}  (recall {recall:.2f} = {recall_matched}/{len(expected_conflicts) or 0}"
        f",  precision {precision:.2f} = {precision_matched}/{len(found_conflicts) or 0})"
    ]
    return MetricResult("conflict_detection_f1", f1, observations)


# ----------------------------------------------------- helpers

def _all_topics_text(synthesis: dict) -> str:
    topics = synthesis.get("topics", [])
    return " ".join(
        f"{t.get('theme', '')} {t.get('summary', '')} {t.get('raw_quote', '')}".lower()
        for t in topics
    )


def _all_story_titles(synthesis: dict) -> str:
    epics = synthesis.get("epics", [])
    return " ".join(
        s.get("title", "")
        for e in epics
        for s in e.get("stories", [])
    )


def _story_has_keywords(synthesis: dict, story_id: str, keywords: list[str]) -> bool:
    """True if the story with the given id has every keyword in its title/description."""
    epics = synthesis.get("epics", [])
    for e in epics:
        for s in e.get("stories", []):
            if s.get("id") != story_id:
                continue
            haystack = (s.get("title", "") + " " + s.get("description", "")).lower()
            return all(k in haystack for k in keywords)
    return False
