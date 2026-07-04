"""Base class for all agents.

An agent has:
  - A name (used in the audit log)
  - Access to `MemoryStore` for reading from / writing to shared memory
  - Access to `AuditLog` for recording its decisions
  - Access to tools (passed in by the orchestrator)

Subclasses implement `run()` which does the agent's work. Retry logic for
tool calls lives in the individual tools (e.g., `ClaudeTool`), not here —
that way each tool can have appropriate retry behavior.
"""

from __future__ import annotations

from pathlib import Path

from memory.store import MemoryStore
from memory.audit_log import AuditLog


PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


class AgentError(Exception):
    """Raised when an agent cannot produce usable output."""


class Agent:
    """Base agent. Subclasses set `name` and implement `run()`."""

    name: str = "agent"

    def __init__(self, memory: MemoryStore, audit: AuditLog) -> None:
        self.memory = memory
        self.audit = audit

    # ---------------------------------------------- helpers

    @staticmethod
    def load_prompt(filename: str) -> str:
        """Load a prompt template from the prompts/ directory."""
        path = PROMPTS_DIR / filename
        if not path.exists():
            raise AgentError(f"Prompt file missing: {path}")
        return path.read_text(encoding="utf-8")

    def emit(self, event: str, payload: dict | None = None, reasoning: str = "") -> None:
        """Shorthand to record an audit event tagged with this agent's name."""
        self.audit.record(self.name, event, payload=payload, reasoning=reasoning)

    # ---------------------------------------------- abstract

    def run(self, *args, **kwargs) -> None:
        raise NotImplementedError
