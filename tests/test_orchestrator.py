"""End-to-end smoke test for the orchestrator with a mocked Claude tool.

Verifies that:
  - All five agents fire in the right order
  - Memory handoff between agents works
  - The final result dict has the expected shape
  - The audit log records every agent's events
"""

from __future__ import annotations

import sys
from pathlib import Path


# Make src/ importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


class FakeClaudeTool:
    """Stand-in for ClaudeTool. Returns canned responses per agent."""

    name = "claude"

    def __init__(self, responses_by_prefix: dict[str, dict]):
        self._responses = responses_by_prefix
        self.calls = []

    def call_for_json(self, user_message: str, max_tokens: int = 4000) -> tuple[dict, dict]:
        # Match on a substring of the prompt to pick the canned response
        for prefix, response in self._responses.items():
            if prefix in user_message:
                self.calls.append((prefix, len(user_message)))
                return response, {"input_tokens": 100, "output_tokens": 200}
        raise RuntimeError(f"No canned response matched prompt starting: {user_message[:80]}...")


class FakeJira:
    name = "jira"
    def list_all(self): return []
    def search(self, q): return []


class FakeConfluence:
    name = "confluence"
    def get_page(self, page_id="default"): return ""


class FakeGithub:
    name = "github"
    def list_all(self): return []
    def search(self, q): return []


def test_orchestrator_end_to_end_with_mocks():
    """Run the orchestrator with mocked tools; verify the synthesis assembles correctly."""
    from pipeline import Orchestrator

    fake_claude = FakeClaudeTool({
        # Parser
        "extract the distinct topics": {
            "summary": "Two themes discussed.",
            "topics": [
                {"theme": "firmware-offline", "summary": "Firmware deployment stalls when the plant WAN drops",
                 "raw_quote": "firmware deployments stall when the plant WAN drops", "speaker": "Kenji",
                 "sentiment": "concern"},
                {"theme": "order-status-confusion", "summary": "PartnerPortal order status shows stale data",
                 "raw_quote": "clients see On Track for orders that are actually delayed", "speaker": "Sarah",
                 "sentiment": "concern"},
            ],
        },
        # Constraint extractor
        "extract the architectural constraints": {
            "constraints": [
                {"severity": "must", "category": "offline", "statement": "FirmwareVault must support offline deployment mode",
                 "source_excerpt": "firmware deployment must continue during WAN outage", "applies_to": ["firmware-updates"]},
                {"severity": "forbidden", "category": "compliance", "statement": "Direct calls to payment processors are forbidden",
                 "source_excerpt": "payments must go through InvoiceGateway: direct calls FORBIDDEN", "applies_to": ["payments"]},
            ],
        },
        # Story writer
        "draft well-formed user stories": {
            "stories": [
                {
                    "id": "ST-01",
                    "title": "Enable offline firmware deployment when the plant WAN drops",
                    "description": "FirmwareVault falls back to local cache when offline.",
                    "user_story": "As a platform engineer, I want firmware deployment to continue offline, so that plant WAN outages don't block module updates.",
                    "acceptance_criteria": [
                        "Given the plant WAN is offline, when a firmware deployment is triggered, then it completes from local cache.",
                        "Given WAN connectivity returns, when next sync runs, then deployment status reconciles with FirmwareVault.",
                    ],
                    "priority": "High",
                    "priority_rationale": "WAN outages block firmware deployments across the plant floor.",
                    "tags": ["firmware-updates", "offline-mode"],
                    "source_topic_id": "T-01",
                    "potential_constraint_conflicts": [],
                },
                {
                    "id": "ST-02",
                    "title": "Show live production order status badge in PartnerPortal",
                    "description": "Wire live MES telemetry into the order-status service.",
                    "user_story": "As an OEM client, I want a live order status badge, so that I see accurate production state without calling support.",
                    "acceptance_criteria": [
                        "Given I'm on the order detail screen, when I view order status, then I see live MES data not older than 5 minutes.",
                    ],
                    "priority": "Medium",
                    "priority_rationale": "Stale order status drives unnecessary support contacts.",
                    "tags": ["partner-portal", "mes"],
                    "source_topic_id": "T-02",
                    "potential_constraint_conflicts": [],
                },
            ],
        },
        # Epic decomposer
        "group them into epics": {
            "epics": [
                {
                    "id": "EP-01",
                    "title": "Firmware Deployment Resilience",
                    "description": "Keep firmware deployments working during plant WAN outages.",
                    "stories": [
                        {
                            "id": "ST-01",
                            "title": "Enable offline firmware deployment when the plant WAN drops",
                            "description": "FirmwareVault falls back to local cache when offline.",
                            "user_story": "As a platform engineer...",
                            "acceptance_criteria": ["Given the plant WAN is offline..."],
                            "priority": "High",
                            "tags": ["firmware-updates", "offline-mode"],
                            "tasks": [
                                {"id": "ST-01-TK-01", "title": "Embed local firmware cache in deployment agent", "type": "infra"},
                                {"id": "ST-01-TK-02", "title": "Implement WAN-reconnect sync", "type": "backend"},
                                {"id": "ST-01-TK-03", "title": "QA — offline deployment soak test", "type": "qa"},
                            ],
                        },
                    ],
                },
                {
                    "id": "EP-02",
                    "title": "PartnerPortal Order Visibility",
                    "description": "Surface live MES production order status to OEM clients.",
                    "stories": [
                        {
                            "id": "ST-02",
                            "title": "Show live production order status badge in PartnerPortal",
                            "description": "Wire live MES telemetry into the order-status service.",
                            "user_story": "As an OEM client...",
                            "acceptance_criteria": ["Given I'm on the order detail screen..."],
                            "priority": "Medium",
                            "tags": ["partner-portal", "mes"],
                            "tasks": [
                                {"id": "ST-02-TK-01", "title": "Design live order status badge component", "type": "frontend"},
                                {"id": "ST-02-TK-02", "title": "Wire MES telemetry API for order data", "type": "backend"},
                                {"id": "ST-02-TK-03", "title": "Add freshness SLA tests", "type": "qa"},
                            ],
                        },
                    ],
                },
            ],
        },
        # Gap detector
        "Duplicate detection is handled separately": {
            "duplicates": [
                {
                    "story_id": "ST-02",
                    "existing_id": "QT-412",
                    "confidence": "high",
                    "reason": "Both address PartnerPortal live order status.",
                },
            ],
            "conflicts": [],
            "gaps": [
                {
                    "title": "WAN-loss detection trigger for firmware deployment",
                    "description": "Stories assume offline mode kicks in, but no story defines when/how the agent detects WAN loss.",
                    "evidence": "Deployment flow assumes FirmwareVault agent already knows it's offline.",
                },
            ],
        },
    })

    orchestrator = Orchestrator(
        claude=fake_claude,
        jira=FakeJira(),
        confluence=FakeConfluence(),
    )

    # Disable embedding-based duplicate detection — this test asserts on
    # the LLM-emitted duplicate payload, so the duplicate must come from
    # the mocked LLM rather than local cosine similarity.
    result = orchestrator.run(
        transcript_text="(transcript content, doesn't matter — Claude is mocked)",
        constraint_text="(constraint content)",
        existing_tickets=[
            {"id": "AD-389", "title": "Subscription trial expiry notification", "description": "Improve notification."},
        ],
        use_embeddings_for_duplicates=False,
    )

    # Topics extracted
    assert len(result["topics"]) == 2
    assert result["topics"][0]["id"] == "T-01"
    assert result["topics"][1]["id"] == "T-02"

    # Constraints extracted
    assert len(result["constraints"]) == 2

    # Epics with nested stories and tasks
    epics = result["epics"]
    assert len(epics) == 2
    assert epics[0]["id"] == "EP-01"
    assert len(epics[0]["stories"]) == 1
    assert len(epics[0]["stories"][0]["tasks"]) == 3

    # Gap detector outputs
    assert len(result["duplicates"]) == 1
    assert result["duplicates"][0]["existing_id"] == "QT-412"
    assert len(result["gaps"]) == 1

    # Audit trail rendered as markdown
    assert "Audit trail" in result["audit_trail"]
    assert "parser" in result["audit_trail"]
    assert "constraint_extractor" in result["audit_trail"]
    assert "story_writer" in result["audit_trail"]
    assert "epic_decomposer" in result["audit_trail"]
    assert "gap_detector" in result["audit_trail"]

    # Confirm each agent called Claude exactly once
    assert len(fake_claude.calls) == 5


def test_orchestrator_skips_agents_when_input_missing():
    """If the transcript is empty, the parser is skipped — and downstream agents too."""
    from pipeline import Orchestrator

    fake_claude = FakeClaudeTool({})  # Should never be called

    orchestrator = Orchestrator(
        claude=fake_claude,
        jira=FakeJira(),
        confluence=FakeConfluence(),
    )

    result = orchestrator.run(
        transcript_text="",
        constraint_text="",
        existing_tickets=[],
    )

    assert result["topics"] == []
    assert result["constraints"] == []
    assert result["epics"] == []
    assert result["duplicates"] == []
    assert fake_claude.calls == []


def test_output_formatter_renders_epic_hierarchy(tmp_path):
    """The output formatter should render epic → story → task hierarchy correctly."""
    from output_formatter import write_outputs

    result = {
        "summary": "Two epics from the meeting.",
        "epics": [
            {
                "id": "EP-01",
                "title": "Connectivity Resilience",
                "description": "TV client must survive connectivity drops.",
                "stories": [
                    {
                        "id": "ST-01",
                        "title": "Offline playback logging",
                        "description": "Local playback store on the TV client.",
                        "user_story": "As a viewer, I want playback logged offline.",
                        "acceptance_criteria": ["Given X, when Y, then Z."],
                        "priority": "High",
                        "tags": ["telemetry", "offline-mode"],
                        "tasks": [
                            {"id": "TK-01", "title": "Embed local playback store in TV client", "type": "infra"},
                        ],
                    }
                ],
            }
        ],
        "gaps": [],
        "conflicts": [],
        "duplicates": [],
    }
    json_path, md_path = write_outputs(result, tmp_path)
    md = md_path.read_text()
    assert "# Backlog Synthesis" in md
    assert "Epic 1: Connectivity Resilience" in md
    assert "1.1 Offline playback logging" in md
    assert "Embed local playback store in TV client" in md
    assert "`telemetry`" in md
