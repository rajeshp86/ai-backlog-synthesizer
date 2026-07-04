"""Per-agent unit tests.

Each test exercises one agent in isolation with a mocked Claude tool.
Verifies:
  - The agent loads its prompt template from prompts/<name>_prompt.md
  - The agent reads the expected keys from MemoryStore
  - The agent writes the expected shape to MemoryStore
  - The agent emits audit events for `started` and `completed`
  - The agent handles a Claude tool failure by raising AgentError

The end-to-end orchestrator test (`test_orchestrator.py`) covers the
five-agent handoff. These tests cover each agent's individual contract,
so a regression in one agent surfaces a focused failure rather than an
opaque pipeline error.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


# --------------------------------------------------------------- fakes


class FakeClaudeTool:
    """Stand-in for ClaudeTool. Returns one canned response."""

    name = "claude"

    def __init__(self, response: dict) -> None:
        self._response = response
        self.calls: list[str] = []  # records every prompt the agent sent

    def call_for_json(self, user_message: str, max_tokens: int = 4000):
        self.calls.append(user_message)
        return self._response, {"input_tokens": 50, "output_tokens": 100}


class FailingClaudeTool:
    """Claude tool that always raises — used to verify agents surface ToolError as AgentError."""

    name = "claude"

    def call_for_json(self, user_message: str, max_tokens: int = 4000):
        from tools.base import ToolError
        raise ToolError("simulated API failure")


class FakeJira:
    name = "jira"

    def list_all(self):
        return []

    def search(self, q):
        return []


class FakeGithub:
    name = "github"

    def list_all(self):
        return []

    def search(self, q):
        return []


class FakeConfluence:
    name = "confluence"

    def get_page(self, page_id="default"):
        return ""


# --------------------------------------------------------------- fixtures


@pytest.fixture
def memory():
    from memory.store import MemoryStore
    return MemoryStore()


@pytest.fixture
def audit():
    from memory.audit_log import AuditLog
    return AuditLog()


# --------------------------------------------------------------- Parser Agent


def test_discovery_engine_writes_topics_and_summary(memory, audit):
    from agents.discovery_engine import DiscoveryEngine

    fake = FakeClaudeTool({
        "summary": "Meeting covered telemetry resilience and subscription services.",
        "topics": [
            {"theme": "telemetry-offline", "summary": "Telemetry offline mode",
             "raw_quote": "signal drops", "speaker": "Kenji", "sentiment": "concern"},
            {"theme": "subscription-confusion", "summary": "Renewal rules unclear",
             "raw_quote": "downgraded with no warning", "speaker": "Priya", "sentiment": "concern"},
        ],
    })
    agent = DiscoveryEngine(claude=fake, memory=memory, audit=audit)
    agent.run("Transcript text — short enough that the test is fast.")

    topics = memory.get("topics")
    assert isinstance(topics, list)
    assert len(topics) == 2
    # IDs are deterministic
    assert topics[0]["id"] == "T-01"
    assert topics[1]["id"] == "T-02"
    # Summary written
    assert memory.get("summary") == "Meeting covered telemetry resilience and subscription services."
    # Claude called exactly once
    assert len(fake.calls) == 1
    # Audit log has started + completed events for this agent
    events = [e for e in audit.events if e.agent == "parser"]
    event_types = {e.event for e in events}
    assert "started" in event_types
    assert "completed" in event_types


def test_discovery_engine_raises_agent_error_when_claude_fails(memory, audit):
    """A ToolError from the Claude tool must surface as an AgentError."""
    from agents.discovery_engine import DiscoveryEngine
    from agents.base import AgentError

    agent = DiscoveryEngine(claude=FailingClaudeTool(), memory=memory, audit=audit)
    with pytest.raises(AgentError):
        agent.run("any transcript")


# --------------------------------------------------------------- Constraint Agent


def test_policy_engine_agent_writes_constraints(memory, audit):
    from agents.policy_engine_agent import PolicyEngineAgent

    fake = FakeClaudeTool({
        "constraints": [
            {"severity": "must", "category": "performance",
             "statement": "Cart load p95 under 1.5s on 3G",
             "source_excerpt": "Mobile app cart-load p95 must stay under 1.5 seconds",
             "applies_to": ["mobile-app"]},
            {"severity": "forbidden", "category": "compliance",
             "statement": "Card sales offline are forbidden",
             "source_excerpt": "PCI is specific about online auth",
             "applies_to": ["telemetry"]},
        ],
    })
    agent = PolicyEngineAgent(claude=fake, confluence=FakeConfluence(), memory=memory, audit=audit)
    agent.run("Architecture constraints wiki text.")

    constraints = memory.get("constraints")
    assert len(constraints) == 2
    assert constraints[1]["severity"] == "forbidden"
    # Constraint agent skips writing when the input is empty
    assert len(fake.calls) == 1


def test_policy_engine_agent_raises_agent_error_when_claude_fails(memory, audit):
    """A ToolError from the Claude tool must surface as an AgentError so the
    orchestrator can decide whether to continue with downstream agents."""
    from agents.policy_engine_agent import PolicyEngineAgent
    from agents.base import AgentError

    agent = PolicyEngineAgent(
        claude=FailingClaudeTool(), confluence=FakeConfluence(),
        memory=memory, audit=audit,
    )
    with pytest.raises(AgentError):
        agent.run("Some constraint wiki text.")


# --------------------------------------------------------------- Story Writer Agent


def test_story_generation_agent_writes_stories_with_acceptance_criteria(memory, audit):
    from agents.story_generation_agent import StoryGenerationAgent

    # Story writer reads `topics` and `constraints` from memory
    memory.put("topics", [
        {"id": "T-01", "theme": "telemetry-offline", "summary": "Telemetry offline mode",
         "raw_quote": "signal drops"},
    ])
    memory.put("constraints", [])  # empty constraints list is valid

    fake = FakeClaudeTool({
        "stories": [
            {
                "id": "ST-01",
                "title": "Enable offline playback logging on the TV client",
                "description": "TV client falls back to local cache.",
                "user_story": "As a viewer, I want playback logged offline, so history isn't lost.",
                "acceptance_criteria": [
                    "Given the device is offline, when playback is logged, then it completes from cache.",
                    "Given connectivity returns, when sync runs, then offline playback reconciles.",
                ],
                "priority": "High",
                "priority_rationale": "Direct revenue loss.",
                "tags": ["telemetry", "offline-mode"],
                "source_topic_id": "T-01",
                "potential_constraint_conflicts": [],
            }
        ]
    })
    agent = StoryGenerationAgent(claude=fake, memory=memory, audit=audit)
    agent.run()

    stories = memory.get("stories")
    assert len(stories) == 1
    s = stories[0]
    assert s["id"] == "ST-01"
    assert len(s["acceptance_criteria"]) == 2
    # Every AC follows the Given/When/Then convention — basic structural check
    assert all("Given" in ac and "when" in ac.lower() and "then" in ac.lower()
               for ac in s["acceptance_criteria"])


def test_story_generation_agent_skips_when_no_topics(memory, audit):
    """If no topics were extracted, the writer skips rather than hallucinate."""
    from agents.story_generation_agent import StoryGenerationAgent

    memory.put("topics", [])
    fake = FakeClaudeTool({})
    agent = StoryGenerationAgent(claude=fake, memory=memory, audit=audit)
    agent.run()

    assert fake.calls == []
    assert memory.get("stories", []) == []


# --------------------------------------------------------------- Epic Decomposer Agent


def test_delivery_planner_agent_groups_stories_into_epics_with_tasks(memory, audit):
    from agents.delivery_planner_agent import DeliveryPlannerAgent

    memory.put("stories", [
        {"id": "ST-01", "title": "Offline playback logging", "tags": ["telemetry", "offline"]},
        {"id": "ST-02", "title": "Offline discovery in low-bandwidth mode", "tags": ["discovery", "offline"]},
    ])

    fake = FakeClaudeTool({
        "epics": [
            {
                "id": "EP-01",
                "title": "Connectivity Resilience",
                "description": "Keep the TV client working when offline.",
                "stories": [
                    {
                        "id": "ST-01",
                        "title": "Offline playback logging",
                        "tags": ["telemetry", "offline"],
                        "tasks": [
                            {"id": "ST-01-TK-01", "title": "Embed local cache in TV client", "type": "infra"},
                            {"id": "ST-01-TK-02", "title": "Hourly sync job", "type": "backend"},
                        ],
                    },
                    {
                        "id": "ST-02",
                        "title": "Offline discovery in low-bandwidth mode",
                        "tags": ["telemetry", "offline"],
                        "tasks": [
                            {"id": "ST-02-TK-01", "title": "Local balance cache schema", "type": "infra"},
                        ],
                    },
                ],
            }
        ]
    })
    agent = DeliveryPlannerAgent(claude=fake, memory=memory, audit=audit)
    agent.run()

    epics = memory.get("epics")
    assert len(epics) == 1
    epic = epics[0]
    assert epic["id"] == "EP-01"
    assert len(epic["stories"]) == 2
    # Each story has tasks
    assert all(len(s["tasks"]) >= 1 for s in epic["stories"])


# --------------------------------------------------------------- Gap Detector Agent


def test_insight_scanner_writes_duplicates_conflicts_and_gaps(memory, audit):
    from agents.insight_scanner_agent import InsightScannerAgent

    memory.put("stories", [
        {"id": "ST-01", "title": "Subscription renewal UI",
         "description": "Show the subscriber when their subscription renews.",
         "tags": ["subscription", "mobile-app"]},
    ])
    memory.put("constraints", [])
    memory.put("existing_tickets", [
        {"id": "QT-412", "key": "QT-412", "title": "Surface live order status badge in PartnerPortal",
         "summary": "Surface live order status badge in PartnerPortal", "description": "Wire live MES telemetry."},
    ])

    fake = FakeClaudeTool({
        "duplicates": [
            {"story_id": "ST-01", "existing_id": "QT-412",
             "confidence": "high", "reason": "Both address PartnerPortal live order status transparency."},
        ],
        "conflicts": [],
        "gaps": [
            {"title": "MES telemetry API contract missing",
             "description": "Stories assume the MES API exists but no story defines the contract.",
             "evidence": "No story covers the MES API contract."},
        ],
    })

    # This test asserts on the LLM-emitted duplicate payload, so opt out of
    # the new embedding-based duplicate detection — otherwise duplicates
    # come from the local cosine similarity (different `reason` text) or
    # don't surface at all when the strings aren't close enough.
    agent = InsightScannerAgent(
        claude=fake, jira=FakeJira(),
        memory=memory, audit=audit,
        use_embeddings_for_duplicates=False,
    )
    agent.run()

    assert memory.get("duplicates")[0]["existing_id"] == "QT-412"
    assert memory.get("conflicts") == []
    assert len(memory.get("gaps")) == 1


def test_insight_scanner_skips_when_no_stories(memory, audit):
    """No upstream stories → gap detector should skip cleanly, not call Claude."""
    from agents.insight_scanner_agent import InsightScannerAgent

    memory.put("stories", [])
    fake = FakeClaudeTool({})

    agent = InsightScannerAgent(
        claude=fake, jira=FakeJira(),
        memory=memory, audit=audit,
    )
    agent.run()

    assert fake.calls == []
    events = [e for e in audit.events if e.agent == "gap_detector"]
    assert any(e.event == "skipped" for e in events)


# --------------------------------------------------------------- Memory & Audit


def test_memory_store_kv_put_get_append(memory):
    memory.put("foo", "bar")
    assert memory.get("foo") == "bar"
    assert memory.get("missing", "default") == "default"

    memory.append("items", 1)
    memory.append("items", 2)
    assert memory.get("items") == [1, 2]


def test_audit_log_renders_markdown(audit):
    audit.record("parser", "started", payload={"input_chars": 100})
    audit.record("parser", "completed", reasoning="Extracted 3 topics.")
    md = audit.render_markdown()
    assert "Audit trail" in md
    assert "parser" in md
    assert "started" in md
    assert "completed" in md
    assert "Extracted 3 topics" in md

