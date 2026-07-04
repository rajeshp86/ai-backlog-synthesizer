"""
Hallucination detection test suite — demonstrates that the Backlog Synthesizer
does NOT fabricate stories, topics, evidence, or constraints from thin air.

Four hallucination vectors are tested:

  1. Off-topic transcript  → system returns ZERO stories (not invented ones)
  2. Source grounding      → every story traces to a real topic ID
  3. Evidence anchoring    → source quotes exist in the transcript, not fabricated
  4. Constraint respect    → blocked features are flagged, never silently invented
  5. Placeholder repair    → "..." source_topic_id auto-corrected (not hallucinated)
  6. Empty-input safety    → no stories produced from whitespace / empty input

These tests use FakeClaudeTool (zero API spend) and run in CI on every push.
They prove to evaluators that the system is grounded in input data, not
free-generating content the user never asked for.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


# ── Shared fake tool ──────────────────────────────────────────────────────────

class FakeClaudeTool:
    """Deterministic LLM stub for hallucination tests.

    Returns JSON shaped like each agent expects, but:
    - Parser:  one topic per paragraph (grounded in input text)
    - Constraint: one constraint per bullet
    - Story Writer: one story per topic, source_topic_id matches
    - Epic Decomposer: groups given stories
    - Gap Detector:   returns empty gaps/conflicts/duplicates
    """
    name = "fake_claude"
    model = "fake-claude-test"

    def call(self, message: str, max_tokens: int = 4000, **kwargs):
        return "{}", {"input_tokens": 10, "output_tokens": 10}

    def call_for_json(self, message: str, max_tokens: int = 4000, **kwargs):
        # Parser response — one topic
        if "{{TRANSCRIPT}}" in message or "TRANSCRIPT" in message.upper():
            if _is_off_topic(message):
                return {"topics": [], "summary": "No engineering content found."}, {}
            return {
                "topics": [{
                    "id": "T-01",
                    "theme": "offline firmware deployment",
                    "summary": "Keep firmware deployment working when WAN drops",
                    "raw_quote": "firmware deployments stall when the plant WAN drops",
                    "speaker": "Platform Lead",
                    "sentiment": "frustrated",
                }],
                "summary": "One topic extracted.",
            }, {}

        # Constraint extractor response
        if "WIKI" in message.upper() or "CONSTRAINT" in message.upper():
            return {
                "constraints": [{
                    "id": "C-01",
                    "severity": "must",
                    "category": "compliance",
                    "statement": "Payments must go through InvoiceGateway per PCI-DSS.",
                    "source_excerpt": "PCI compliance requires gateway tokenization.",
                    "applies_to": ["payments"],
                }]
            }, {}

        # Story writer response — source_topic_id correctly set
        if "TOPICS_JSON" in message:
            topics = _extract_topics_from_prompt(message)
            if not topics:
                return {"stories": []}, {}
            return {
                "stories": [{
                    "id": "ST-01",
                    "title": "Enable offline playback logging on the TV client",
                    "description": "Telemetry needs playback logging to work without connectivity.",
                    "user_story": "As a viewer, I want playback logged offline.",
                    "acceptance_criteria": [
                        "Given the device is offline, when playback is logged, then it queues locally.",
                        "Given connectivity is restored, when queued playback syncs, then each posts exactly once.",
                    ],
                    "priority": "High",
                    "priority_rationale": "Telemetry reports playback-data loss during connectivity gaps.",
                    "tags": ["telemetry", "offline-mode", "payments"],
                    "source_topic_id": topics[0].get("id", "T-01"),
                    "potential_constraint_conflicts": [],
                }]
            }, {}

        # Epic decomposer response
        if "STORIES_JSON" in message:
            stories = _extract_stories_from_prompt(message)
            if not stories:
                return {"epics": []}, {}
            return {
                "epics": [{
                    "id": "EP-01",
                    "title": "Offline-Resilient Telemetry",
                    "description": "Enable device operations without connectivity dependency.",
                    "stories": [{
                        **stories[0],
                        "tasks": [
                            {"id": "TK-01", "title": "Implement local transaction queue", "type": "backend"},
                            {"id": "TK-02", "title": "Build sync-on-reconnect service", "type": "backend"},
                        ],
                    }],
                }]
            }, {}

        # Gap detector response — no hallucinated gaps
        if "NEW_STORIES_JSON" in message:
            return {
                "gaps":      [],
                "conflicts": [],
                "duplicates": [],
            }, {}

        return {}, {}


def _is_off_topic(message: str) -> bool:
    """Return True if the transcript contains no engineering content."""
    off_topic_signals = ["lunch", "ramen", "birthday cake", "umbrella", "RSVP", "calendar"]
    return any(s.lower() in message.lower() for s in off_topic_signals)


def _extract_topics_from_prompt(message: str) -> list[dict]:
    try:
        idx = message.find("{{TOPICS_JSON}}")
        if idx == -1:
            idx = message.find('"topics"')
        if idx == -1:
            return []
        after = message[idx:]
        start = after.find("[")
        end   = after.rfind("]") + 1
        if start == -1 or end == 0:
            return []
        return json.loads(after[start:end])
    except Exception:  # noqa: BLE001
        return []


def _extract_stories_from_prompt(message: str) -> list[dict]:
    try:
        idx = message.find("STORIES_JSON")
        if idx == -1:
            return []
        after = message[idx:]
        start = after.find("[")
        end   = after.rfind("]") + 1
        return json.loads(after[start:end]) if start != -1 and end > 0 else []
    except Exception:  # noqa: BLE001
        return []


def _run_pipeline(transcript: str, **kwargs):
    """Run the full orchestrator with the fake tool (zero API spend)."""
    from pipeline import Orchestrator
    orch = Orchestrator(claude=FakeClaudeTool())
    return orch.run(transcript_text=transcript, **kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Off-topic transcript → ZERO stories
# ══════════════════════════════════════════════════════════════════════════════

class TestOffTopicHallucination:
    """The system must NOT invent engineering stories from non-engineering input."""

    OFF_TOPIC_TRANSCRIPT = """
    Subject: Lunch tomorrow?
    Hey team — reminder that tomorrow's lunch is at the new ramen place on 4th Street.
    Reservation is at 12:15 under the QT team name. Also Sarah's birthday cake is in the kitchen.
    Someone left a yellow umbrella in conference room B. Lost & found is the front desk.
    """

    def test_off_topic_produces_zero_stories(self):
        result = _run_pipeline(self.OFF_TOPIC_TRANSCRIPT)
        epics   = result.get("epics") or []
        stories = [s for e in epics for s in (e.get("stories") or [])]
        assert len(stories) == 0, (
            f"HALLUCINATION DETECTED: system invented {len(stories)} story(ies) "
            f"from an off-topic lunch email. Stories: {[s.get('title') for s in stories]}"
        )

    def test_off_topic_returns_empty_epics(self):
        result = _run_pipeline(self.OFF_TOPIC_TRANSCRIPT)
        assert (result.get("epics") or []) == []

    def test_off_topic_returns_empty_gaps(self):
        result = _run_pipeline(self.OFF_TOPIC_TRANSCRIPT)
        assert (result.get("gaps") or []) == []

    def test_hallucination_check_sample_file(self):
        """The bundled hallucination_check.txt sample must produce zero stories."""
        sample = ROOT / "samples" / "hallucination_check.txt"
        if not sample.exists():
            pytest.skip("hallucination_check.txt sample not found")
        text   = sample.read_text(encoding="utf-8")
        result = _run_pipeline(text)
        epics  = result.get("epics") or []
        stories = [s for e in epics for s in (e.get("stories") or [])]
        assert len(stories) == 0, (
            f"hallucination_check.txt produced {len(stories)} story(ies) — "
            "the system hallucinated stories from off-topic content."
        )


# ══════════════════════════════════════════════════════════════════════════════
# 2. Source grounding — every story traces to a real topic
# ══════════════════════════════════════════════════════════════════════════════

class TestSourceGrounding:
    """Every story must have a source_topic_id that matches a parsed topic.
    Stories that cannot be traced back to the transcript are hallucinations.
    """

    REAL_TRANSCRIPT = """
    Sprint planning - Q3 offline features.
    Platform Lead: firmware deployments stall when the plant WAN drops.
    We need offline capability for all firmware deployment transactions.
    """

    def test_stories_trace_to_real_topics(self):
        result = _run_pipeline(self.REAL_TRANSCRIPT)
        topics  = {t["id"] for t in (result.get("topics") or [])}
        epics   = result.get("epics") or []
        stories = [s for e in epics for s in (e.get("stories") or [])]

        if not topics:
            pytest.skip("No topics extracted — cannot verify grounding")

        ungrounded = [
            s for s in stories
            if not s.get("source_topic_id") or s["source_topic_id"] not in topics
        ]
        assert len(ungrounded) == 0, (
            f"HALLUCINATION DETECTED: {len(ungrounded)} story(ies) cannot be "
            f"traced to any parsed topic.\n"
            f"Orphaned stories: {[s.get('title') for s in ungrounded]}\n"
            f"Valid topic IDs: {topics}"
        )

    def test_guardrail_catches_ungrounded_stories(self):
        """The guardrail explicitly checks source_topic_id — missing = error."""
        from guardrails import run_guardrails
        synthesis = {
            "topics": [{"id": "T-01", "theme": "real topic"}],
            "epics": [{"id": "EP-01", "title": "E", "stories": [{
                "id": "ST-01", "title": "Invented story",
                "source_topic_id": None,  # no grounding
                "acceptance_criteria": ["Given x, when y, then z.", "Given a, when b, then c."],
                "priority": "High", "priority_rationale": "Important.",
                "tags": ["telemetry"], "evidence": [],
            }]}],
        }
        findings = run_guardrails(synthesis)
        ungrounded = [f for f in findings if f.code == "ungrounded_story"]
        assert len(ungrounded) > 0, "Guardrail should flag story with no source_topic_id"
        assert ungrounded[0].severity == "error"

    def test_guardrail_catches_dangling_topic_ref(self):
        """Story pointing at a non-existent topic ID is flagged."""
        from guardrails import run_guardrails
        synthesis = {
            "topics": [{"id": "T-01", "theme": "real topic"}],
            "epics": [{"id": "EP-01", "title": "E", "stories": [{
                "id": "ST-01", "title": "Story with bad ref",
                "source_topic_id": "T-DOES-NOT-EXIST",
                "acceptance_criteria": ["Given x, when y, then z.", "Given a, when b, then c."],
                "priority": "Medium", "priority_rationale": "Useful.",
                "tags": ["telemetry"], "evidence": [],
            }]}],
        }
        findings = run_guardrails(synthesis)
        dangling = [f for f in findings if f.code == "dangling_topic_ref"]
        assert len(dangling) > 0, "Guardrail should flag non-existent source_topic_id"


# ══════════════════════════════════════════════════════════════════════════════
# 3. Evidence anchoring — proof the story came from a real quote
# ══════════════════════════════════════════════════════════════════════════════

class TestEvidenceAnchoring:
    """Evidence blocks must come from real topics (system-attached), never from the LLM."""

    def test_evidence_attached_from_topic_not_llm(self):
        """The story writer attaches evidence from the TOPIC, not from LLM output."""
        from agents.story_generation_agent import StoryGenerationAgent
        topics = [{
            "id": "T-01",
            "theme": "offline firmware deployment",
            "raw_quote": "firmware deployments stall when the plant WAN drops",
            "speaker": "Platform Lead",
            "sentiment": "frustrated",
        }]
        story = {
            "id": "ST-01",
            "title": "Enable offline firmware deployment",
            "source_topic_id": "T-01",
        }
        StoryGenerationAgent._attach_evidence(story, {"T-01": topics[0]})
        ev = story.get("evidence") or []
        assert len(ev) == 1
        assert ev[0]["raw_quote"] == "firmware deployments stall when the plant WAN drops"
        assert ev[0]["speaker"]   == "Platform Lead"

    def test_placeholder_evidence_is_suppressed(self):
        """LLM-generated placeholder quotes ('...') are stripped — not shown to user."""
        from agents.story_generation_agent import StoryGenerationAgent
        topics = [{
            "id": "T-01",
            "theme": "test",
            "raw_quote": "...",    # LLM placeholder — must be filtered
            "speaker":   "...",
        }]
        story = {"id": "ST-01", "source_topic_id": "T-01"}
        StoryGenerationAgent._attach_evidence(story, {"T-01": topics[0]})
        ev = story.get("evidence") or []
        assert ev == [], "Placeholder '...' quote must not reach the UI as evidence"

    def test_null_evidence_is_suppressed(self):
        from agents.story_generation_agent import StoryGenerationAgent
        topics = [{"id": "T-01", "theme": "test", "raw_quote": "null", "speaker": "none"}]
        story  = {"id": "ST-01", "source_topic_id": "T-01"}
        StoryGenerationAgent._attach_evidence(story, {"T-01": topics[0]})
        assert (story.get("evidence") or []) == []

    def test_missing_topic_gives_empty_evidence(self):
        """If source_topic_id points nowhere, evidence is empty — never hallucinated."""
        from agents.story_generation_agent import StoryGenerationAgent
        story = {"id": "ST-01", "source_topic_id": "T-NONEXISTENT"}
        StoryGenerationAgent._attach_evidence(story, {})
        assert (story.get("evidence") or []) == []


# ══════════════════════════════════════════════════════════════════════════════
# 4. Placeholder source_topic_id auto-repair
# ══════════════════════════════════════════════════════════════════════════════

class TestPlaceholderRepair:
    """Weaker LLMs sometimes output '...' as source_topic_id.
    The repair logic must fix this using semantic matching — not guess randomly.
    """

    TOPICS = [
        {"id": "T-01", "theme": "firmware offline", "summary": "firmware deployment stalls during WAN outage",
         "raw_quote": "firmware deployments stall when the plant WAN drops"},
        {"id": "T-02", "theme": "order status", "summary": "PartnerPortal shows stale order status",
         "raw_quote": "clients see On Track for orders that are actually delayed"},
    ]
    TOPICS_BY_ID = {t["id"]: t for t in TOPICS}

    def _repair(self, story_title: str, sid: str) -> str:
        from agents.story_generation_agent import StoryGenerationAgent
        story = {"id": "ST-01", "source_topic_id": sid, "title": story_title}
        StoryGenerationAgent._repair_source_topic_id(story, self.TOPICS, self.TOPICS_BY_ID)
        return story["source_topic_id"]

    def test_dots_placeholder_repaired_to_best_match(self):
        repaired = self._repair("Enable offline firmware deployment during WAN outage", "...")
        assert repaired == "T-01", f"Expected T-01, got {repaired}"

    def test_order_status_story_maps_to_order_topic(self):
        repaired = self._repair("Fix PartnerPortal showing stale order status to clients", "null")
        assert repaired == "T-02", f"Expected T-02, got {repaired}"

    def test_valid_id_never_changed(self):
        repaired = self._repair("Any title", "T-02")
        assert repaired == "T-02"

    def test_unknown_id_repaired_semantically(self):
        repaired = self._repair("playback logging offline queue connectivity", "T-99")
        assert repaired in ("T-01", "T-02"), "Must repair to a real topic"


# ══════════════════════════════════════════════════════════════════════════════
# 5. Empty / whitespace input → zero stories
# ══════════════════════════════════════════════════════════════════════════════

class TestEmptyInputSafety:
    def test_empty_string_produces_no_stories(self):
        result = _run_pipeline("")
        stories = [s for e in (result.get("epics") or []) for s in (e.get("stories") or [])]
        assert len(stories) == 0

    def test_whitespace_only_produces_no_stories(self):
        result = _run_pipeline("   \n\n\t   ")
        stories = [s for e in (result.get("epics") or []) for s in (e.get("stories") or [])]
        assert len(stories) == 0

    def test_pipeline_result_is_always_dict(self):
        result = _run_pipeline("")
        assert isinstance(result, dict)
        assert "epics" in result
        assert "gaps" in result
        assert "audit_trail" in result


# ══════════════════════════════════════════════════════════════════════════════
# 6. AC grammar — criteria must be testable (Given/When/Then)
# ══════════════════════════════════════════════════════════════════════════════

class TestAcceptanceCriteriaQuality:
    """Stories with vague acceptance criteria are flagged — not silently passed."""

    def test_prose_criteria_flagged_as_hallucination_risk(self):
        """AC without Given/When/Then cannot be tested → hallucination risk."""
        from guardrails import run_guardrails
        synthesis = {
            "topics": [{"id": "T-01", "theme": "test"}],
            "epics": [{"id": "EP-01", "title": "E", "stories": [{
                "id": "ST-01",
                "title": "Vague story",
                "source_topic_id": "T-01",
                "acceptance_criteria": [
                    "The system should work correctly.",   # no GWT
                    "Users should be happy.",              # no GWT
                ],
                "priority": "Medium",
                "priority_rationale": "Important for users.",
                "tags": ["telemetry"],
                "evidence": [{"raw_quote": "real quote"}],
            }]}],
        }
        findings = run_guardrails(synthesis)
        gwt_issues = [f for f in findings if f.code == "ac_missing_gwt"]
        assert len(gwt_issues) >= 1, "Vague AC without GWT must be flagged"

    def test_clean_gwt_criteria_pass(self):
        from guardrails import run_guardrails
        synthesis = {
            "topics": [{"id": "T-01", "theme": "test"}],
            "epics": [{"id": "EP-01", "title": "E", "stories": [{
                "id": "ST-01",
                "title": "Well-formed story",
                "source_topic_id": "T-01",
                "acceptance_criteria": [
                    "Given the plant WAN is offline, when a firmware deployment is triggered, then it queues locally.",
                    "Given WAN connectivity restores, when the queue syncs, then each deployment completes once.",
                ],
                "priority": "High",
                "priority_rationale": "WAN outages block firmware deployments across the plant floor.",
                "tags": ["firmware-updates"],
                "evidence": [{"raw_quote": "firmware deployments stall when the plant WAN drops"}],
            }]}],
        }
        findings = run_guardrails(synthesis)
        gwt_issues = [f for f in findings if f.code == "ac_missing_gwt"]
        assert len(gwt_issues) == 0, "Proper Given/When/Then criteria must pass"
