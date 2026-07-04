"""Tests for the post-synthesis guardrails.

The guardrail module is six independent heuristic checks. Each test
builds a minimal synthesis dict that hits one specific check and
verifies exactly that check fires (and that the others stay quiet).
A pair of end-to-end tests covers the "all clear" and "kitchen sink"
combinations.

These tests never call the LLM — guardrails are pure Python over the
result dict.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from guardrails import (  # noqa: E402
    CANONICAL_TAGS,
    GuardrailFinding,
    run_guardrails,
    summarise,
)


# ---------------------------------------------------------------- helpers


def _story(
    *,
    id_="ST-01",
    title="Enable offline firmware deployment when the plant WAN drops",
    description="FirmwareVault falls back to local cache when the plant WAN is offline.",
    user_story="As a platform engineer, I want firmware deployment to continue offline.",
    acceptance_criteria=None,
    priority="High",
    priority_rationale="WAN outages block firmware deployments across the plant floor.",
    tags=None,
    source_topic_id="T-01",
    evidence=None,
):
    """Minimal story dict matching the orchestrator's output shape."""
    return {
        "id": id_,
        "title": title,
        "description": description,
        "user_story": user_story,
        "acceptance_criteria": acceptance_criteria if acceptance_criteria is not None else [
            "Given the plant WAN is offline, when a deployment is triggered, then it completes from local cache.",
            "Given WAN returns, when the next sync runs, then deployment status reconciles with FirmwareVault.",
        ],
        "priority": priority,
        "priority_rationale": priority_rationale,
        "tags": tags if tags is not None else ["firmware-updates", "offline-mode"],
        "source_topic_id": source_topic_id,
        "evidence": evidence if evidence is not None else [{
            "topic_id": "T-01",
            "raw_quote": "firmware deployments stall when the plant WAN drops",
            "speaker": "Kenji",
        }],
    }


def _synthesis(stories=None, topics=None):
    """Wrap a list of stories in the epic structure the guardrails read."""
    return {
        "topics": topics if topics is not None else [
            {"id": "T-01", "theme": "firmware-offline", "raw_quote": "..."},
        ],
        "epics": [{
            "id": "EP-01",
            "title": "Firmware Deployment Resilience",
            "stories": stories or [_story()],
        }],
    }


def _codes(findings: list[GuardrailFinding]) -> list[str]:
    return [f.code for f in findings]


# ---------------------------------------------------------------- baseline


def test_clean_synthesis_produces_no_findings():
    """A well-formed synthesis with one canonical story should pass clean."""
    findings = run_guardrails(_synthesis())
    assert findings == [], f"Expected zero findings, got: {findings}"


def test_summarise_tallies_by_severity():
    """`summarise` returns a dict keyed by severity with int counts."""
    findings = [
        GuardrailFinding("a", "error", "x"),
        GuardrailFinding("b", "warn",  "y"),
        GuardrailFinding("c", "warn",  "z"),
        GuardrailFinding("d", "info",  "w"),
    ]
    tally = summarise(findings)
    assert tally == {"error": 1, "warn": 2, "info": 1}


def test_summarise_empty():
    """Empty findings list returns zeros for every severity."""
    assert summarise([]) == {"error": 0, "warn": 0, "info": 0}


# ---------------------------------------------------------------- per-check


def test_ac_count_too_low_fires_when_under_two():
    story = _story(acceptance_criteria=["Given X, when Y, then Z."])  # only 1 AC
    findings = run_guardrails(_synthesis([story]))
    assert "ac_count_too_low" in _codes(findings)
    # And it shouldn't fire when there are exactly 2 AC.
    story_ok = _story()  # default has 2 AC
    assert "ac_count_too_low" not in _codes(run_guardrails(_synthesis([story_ok])))


def test_ac_count_too_high_fires_when_above_seven():
    eight_acs = [f"Given X{i}, when Y{i}, then Z{i}." for i in range(8)]
    story = _story(acceptance_criteria=eight_acs)
    findings = run_guardrails(_synthesis([story]))
    codes = _codes(findings)
    assert "ac_count_too_high" in codes
    # `ac_count_too_high` is severity=info, not warn
    too_high = [f for f in findings if f.code == "ac_count_too_high"][0]
    assert too_high.severity == "info"


def test_ac_missing_gwt_flags_prose_criteria():
    """AC without the given/when/then keywords gets the warn-level finding."""
    story = _story(acceptance_criteria=[
        "Viewers can use discovery while offline.",             # no GWT
        "Given network returns, when sync runs, then OK.",      # has GWT
    ])
    findings = run_guardrails(_synthesis([story]))
    codes = _codes(findings)
    assert "ac_missing_gwt" in codes
    # The finding should point at AC #1 (the prose one)
    msg = [f.message for f in findings if f.code == "ac_missing_gwt"][0]
    assert "AC #1" in msg


def test_duplicate_title_flags_second_occurrence():
    """Two stories with the same title surface a duplicate_title finding."""
    a = _story(id_="ST-01", title="Enable offline discovery in low-bandwidth mode")
    b = _story(id_="ST-02", title="Enable offline discovery in low-bandwidth mode",
               source_topic_id="T-02",
               evidence=[{"topic_id": "T-02", "raw_quote": "..."}])
    findings = run_guardrails({
        "topics": [
            {"id": "T-01", "theme": "x"},
            {"id": "T-02", "theme": "y"},
        ],
        "epics": [{"id": "EP-01", "stories": [a, b]}],
    })
    codes = _codes(findings)
    assert codes.count("duplicate_title") == 1
    # The finding should be tagged with the second story
    dup = [f for f in findings if f.code == "duplicate_title"][0]
    assert dup.story_id == "ST-02"


def test_duplicate_title_is_case_insensitive_and_trimmed():
    """`Foo` and `  foo  ` collide; whitespace and casing shouldn't hide it."""
    a = _story(id_="ST-01", title="Enable TV App Offline Mode")
    b = _story(id_="ST-02", title="  enable tv app offline mode  ",
               source_topic_id="T-02",
               evidence=[{"topic_id": "T-02", "raw_quote": "..."}])
    findings = run_guardrails({
        "topics": [
            {"id": "T-01", "theme": "x"},
            {"id": "T-02", "theme": "y"},
        ],
        "epics": [{"id": "EP-01", "stories": [a, b]}],
    })
    assert "duplicate_title" in _codes(findings)


def test_non_canonical_tag_is_info_level():
    """Tags outside the canonical set surface as info, not error."""
    story = _story(tags=["telemetry", "made-up-tag", "another-novel-tag"])
    findings = run_guardrails(_synthesis([story]))
    codes = _codes(findings)
    assert "non_canonical_tag" in codes
    nc = [f for f in findings if f.code == "non_canonical_tag"][0]
    assert nc.severity == "info"
    # Both novel tags should appear in the message body
    assert "made-up-tag" in nc.message
    assert "another-novel-tag" in nc.message


def test_canonical_tags_pass_clean():
    """Every tag from the canonical vocabulary should not trigger a finding."""
    story = _story(tags=list(CANONICAL_TAGS)[:3])
    findings = run_guardrails(_synthesis([story]))
    assert "non_canonical_tag" not in _codes(findings)


def test_ungrounded_story_when_source_topic_id_missing():
    """A story with no source_topic_id is the strongest hallucination signal."""
    story = _story(source_topic_id=None)
    findings = run_guardrails(_synthesis([story]))
    codes = _codes(findings)
    assert "ungrounded_story" in codes
    ungrounded = [f for f in findings if f.code == "ungrounded_story"][0]
    assert ungrounded.severity == "error"


def test_dangling_topic_ref_when_source_topic_id_unknown():
    """source_topic_id points at a topic that doesn't exist in the parsed list."""
    story = _story(source_topic_id="T-99")
    findings = run_guardrails(_synthesis([story]))  # topics has T-01 only
    codes = _codes(findings)
    assert "dangling_topic_ref" in codes
    dangling = [f for f in findings if f.code == "dangling_topic_ref"][0]
    # Severity is "warn" (not "error") — the story is still usable, just ungrounded.
    # The story_generation_agent now attempts auto-repair; this guard is a safety net.
    assert dangling.severity == "warn"
    assert "T-99" in dangling.message


def test_missing_evidence_when_block_empty():
    """A story with source_topic_id but no evidence is info-level."""
    story = _story(evidence=[])
    findings = run_guardrails(_synthesis([story]))
    codes = _codes(findings)
    assert "missing_evidence" in codes
    me = [f for f in findings if f.code == "missing_evidence"][0]
    assert me.severity == "info"


def test_weak_priority_rationale_when_under_twenty_chars():
    """High-priority stories with a thin rationale get flagged."""
    story = _story(priority="High", priority_rationale="short")
    findings = run_guardrails(_synthesis([story]))
    codes = _codes(findings)
    assert "weak_priority_rationale" in codes


def test_weak_priority_rationale_does_not_fire_for_medium_or_low():
    """Only high-priority stories are graded on rationale strength."""
    for p in ("Medium", "Low"):
        story = _story(priority=p, priority_rationale="short")
        findings = run_guardrails(_synthesis([story]))
        assert "weak_priority_rationale" not in _codes(findings)


def test_weak_priority_rationale_does_not_fire_when_rationale_is_solid():
    story = _story(priority="High",
                   priority_rationale="Direct customer-facing revenue loss during outages. Compliance flagged this for Q3.")
    findings = run_guardrails(_synthesis([story]))
    assert "weak_priority_rationale" not in _codes(findings)


# ---------------------------------------------------------------- composite


def test_kitchen_sink_synthesis_surfaces_every_check():
    """One story that violates every check at once — sanity-checks that
    findings combine cleanly without one masking another."""
    story = _story(
        acceptance_criteria=["Viewers can use discovery while offline."],  # missing GWT + count low
        priority="High", priority_rationale="x",                              # weak rationale
        tags=["made-up-tag"],                                                  # non-canonical
        source_topic_id=None,                                                  # ungrounded
        evidence=[],                                                           # missing evidence
    )
    findings = run_guardrails(_synthesis([story]))
    codes = _codes(findings)
    expected_some_of = {
        "ac_count_too_low",
        "ac_missing_gwt",
        "weak_priority_rationale",
        "non_canonical_tag",
        "ungrounded_story",
    }
    missing = expected_some_of - set(codes)
    assert not missing, f"Expected findings missing: {missing}; got: {codes}"


def test_guardrails_survive_empty_synthesis():
    """Empty input shouldn't crash — every check tolerates the no-data path."""
    findings = run_guardrails({})
    assert findings == []


def test_guardrails_survive_synthesis_with_no_epics():
    findings = run_guardrails({"epics": [], "topics": []})
    assert findings == []


def test_finding_to_dict_serialises_cleanly():
    """to_dict() is what the orchestrator emits — it must be JSON-safe."""
    import json
    f = GuardrailFinding(code="x", severity="warn", message="y", story_id="ST-01")
    d = f.to_dict()
    assert d == {"code": "x", "severity": "warn", "message": "y", "story_id": "ST-01"}
    json.dumps(d)  # raises if not serialisable
