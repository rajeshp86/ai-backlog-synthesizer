"""Claude API client — backed by langchain-anthropic.

Internally uses ``langchain_anthropic.ChatAnthropic`` while preserving the
exact ``call()`` / ``call_for_json()`` interface that all five agents rely on.
This means the agents themselves require no changes.

Key behaviours preserved from the original implementation:
  - Prompt caching: the system prompt is sent with ``cache_control`` when it
    is long enough (≥ 1024 tokens ≈ 4096 chars) and the model supports it.
  - Vision support: multimodal content blocks (images before text) are
    forwarded as ``HumanMessage`` with a list of typed content blocks.
  - Retry: ``max_retries`` is wired directly into ``ChatAnthropic`` — the
    SDK retries on ``RateLimitError`` and connection errors automatically.
  - JSON extraction: the same defensive ``_extract_json_block`` logic,
    shared by GeminiTool.
  - Token usage: extracted from ``AIMessage.response_metadata`` and returned
    as ``{"input_tokens": N, "output_tokens": N}`` to the audit trail.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from logger_setup import get_logger
from tools.base import Tool, ToolError, VisionAttachment

try:
    from circuit_breaker import CLAUDE_CB as _CLAUDE_CB
    _HAS_CB = True
except ImportError:  # pragma: no cover
    _HAS_CB = False

logger = get_logger(__name__)

DEFAULT_MODEL   = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
MAX_RETRIES     = int(os.environ.get("AGENT_MAX_RETRIES", "3"))
# Per-call HTTP timeout in seconds. Prevents a single hung API call from
# occupying a synthesis slot for the full SYNTHESIS_TIMEOUT_SECONDS window.
LLM_CALL_TIMEOUT = int(os.environ.get("LLM_CALL_TIMEOUT_SECONDS", "120"))
PROMPTS_DIR   = Path(__file__).parent.parent.parent / "prompts"


try:
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import HumanMessage, SystemMessage
except ImportError:  # pragma: no cover
    ChatAnthropic = None  # type: ignore[assignment,misc]
    HumanMessage = SystemMessage = None  # type: ignore[assignment,misc]


class ClaudeTool(Tool):
    """Claude API client using langchain-anthropic with retry + JSON parsing."""

    name = "claude"

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        if ChatAnthropic is None:
            raise ToolError(
                "The `langchain-anthropic` package isn't installed. "
                "Run: pip install -r requirements.txt"
            )
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ToolError(
                "ANTHROPIC_API_KEY isn't set. See .env.example for setup instructions."
            )
        self.model = model
        self.system_prompt = (PROMPTS_DIR / "system_prompt.md").read_text(encoding="utf-8")

        # ChatAnthropic handles rate-limit / connection retries internally.
        self._llm = ChatAnthropic(
            model=model,
            api_key=api_key,
            max_retries=MAX_RETRIES,
            temperature=0,
            timeout=LLM_CALL_TIMEOUT,  # hard per-call HTTP timeout (seconds)
        )

    # ---------------------------------------------- public interface

    def call(
        self,
        user_message: str,
        max_tokens: int = 4000,
        *,
        images: list[VisionAttachment] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Make a single Claude API call. Returns (text, usage_dict)."""
        return self._call_internal(user_message, max_tokens, images=images)

    def call_for_json(
        self,
        user_message: str,
        max_tokens: int = 4000,
        *,
        images: list[VisionAttachment] | None = None,
    ) -> tuple[dict, dict[str, Any]]:
        """Call Claude and parse the response as JSON. Returns (parsed_dict, usage)."""
        text, usage = self.call(user_message, max_tokens=max_tokens, images=images)
        parsed = self._extract_json_block(text)
        return parsed, usage

    # ---------------------------------------------- internal

    def _call_internal(
        self,
        user_message: str,
        max_tokens: int,
        *,
        images: list[VisionAttachment] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        # ---- System message (with optional prompt caching) ----
        # Anthropic caches system blocks when cache_control is set and the block
        # is ≥ 1024 tokens (≈ 4096 chars).  We pass the cache_control dict as
        # part of the content list, which langchain-anthropic forwards verbatim.
        _cacheable = self.model.startswith("claude") and len(self.system_prompt) >= 4096
        if _cacheable:
            system_msg = SystemMessage(
                content=[{
                    "type":          "text",
                    "text":          self.system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }]
            )
        else:
            system_msg = SystemMessage(content=self.system_prompt)

        # ---- User message (multimodal when images are present) ----
        if images:
            # Image blocks come BEFORE the text block — Anthropic's recommendation.
            content: list[dict[str, Any]] = [
                {
                    "type":   "image",
                    "source": {
                        "type":       "base64",
                        "media_type": img.media_type,
                        "data":       img.data_b64,
                    },
                }
                for img in images
            ]
            content.append({"type": "text", "text": user_message})
            human_msg = HumanMessage(content=content)
        else:
            human_msg = HumanMessage(content=user_message)

        # ---- Telemetry span (no-op if opentelemetry isn't enabled) ----
        try:
            from telemetry import child_span as _cs
        except ImportError:
            import contextlib
            def _cs(*_a, **_kw):  # type: ignore[misc]
                return contextlib.nullcontext()

        with _cs(
            "llm.call",
            **{
                "llm.provider":    "anthropic",
                "llm.model":       self.model,
                "llm.max_tokens":  max_tokens,
                "llm.has_images":  bool(images),
            },
        ) as _span:
            try:
                # .bind() creates a new model instance with max_tokens set;
                # this is the standard LangChain pattern for per-call overrides.
                response = self._llm.bind(max_tokens=max_tokens).invoke(
                    [system_msg, human_msg]
                )
            except Exception as exc:
                msg = str(exc).lower()
                transient = any(t in msg for t in (
                    "rate", "429", "overloaded", "connection",
                    "timeout", "unavailable",
                ))
                if transient and _HAS_CB:
                    _CLAUDE_CB.record_failure()
                if transient:
                    raise ToolError(f"Anthropic transient error: {exc}") from exc
                raise ToolError(f"Anthropic API error: {exc}") from exc

            # ---- Extract text ----
            raw = response.content
            if isinstance(raw, str):
                text = raw
            else:
                # Content blocks list — join text segments
                text = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in (raw or [])
                )

            # ---- Extract usage from response metadata ----
            meta  = getattr(response, "response_metadata", {}) or {}
            udata = meta.get("usage", {}) or {}
            usage: dict[str, Any] = {
                "input_tokens":  udata.get("input_tokens"),
                "output_tokens": udata.get("output_tokens"),
            }

            try:
                _span.set_attribute("llm.tokens_in",     usage["input_tokens"]  or 0)
                _span.set_attribute("llm.tokens_out",    usage["output_tokens"] or 0)
                _span.set_attribute("llm.response_chars", len(text))
            except Exception:  # noqa: BLE001
                pass

            if _HAS_CB:
                _CLAUDE_CB.record_success()
            return text, usage

    # ---------------------------------------------- JSON extraction
    # Shared by GeminiTool via import.

    @staticmethod
    def _extract_json_block(text: str) -> dict:
        """Pull a JSON object out of model output. Handles fences and prose."""
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence_match:
            candidates = [fence_match.group(1)]
        else:
            candidates = [text[m.start():] for m in re.finditer(r"\{", text)]

        if not candidates:
            raise ToolError(f"No JSON object found in model output:\n{text[:300]}")

        last_err: Exception = ValueError("no candidates")
        for raw in candidates:
            depth = 0
            end   = -1
            for i, ch in enumerate(raw):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            candidate = raw[:end] if end > 0 else raw
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as exc:
                last_err = exc
                continue

        raise ToolError(
            f"Model produced invalid JSON: {last_err}\nGot:\n{candidates[0][:500]}"
        )
