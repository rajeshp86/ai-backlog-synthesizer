"""Google Gemini API client — backed by langchain-google-genai.

Internally uses ``langchain_google_genai.ChatGoogleGenerativeAI`` while
preserving the same ``call()`` / ``call_for_json()`` interface as ClaudeTool,
so agents can swap providers without knowing which one is in use.

Behaviour preserved from the original:
  - Reads ``GOOGLE_API_KEY`` (also accepts ``GEMINI_API_KEY`` alias).
  - Returns usage as ``{"input_tokens": N, "output_tokens": N}``.
  - JSON extraction reuses ``ClaudeTool._extract_json_block`` — defensive
    parsing works identically for all providers.
  - Transient errors (quota / rate-limit / 5xx / network) are classified
    and surfaced as ``ToolError`` so the orchestrator handles them uniformly.
"""

from __future__ import annotations

import os
from typing import Any

from logger_setup import get_logger
from tools.base import Tool, ToolError
from tools.claude_tool import ClaudeTool, PROMPTS_DIR  # reuse JSON extractor + prompts dir

logger = get_logger(__name__)

DEFAULT_MODEL    = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_RETRIES      = int(os.environ.get("AGENT_MAX_RETRIES", "3"))
LLM_CALL_TIMEOUT = int(os.environ.get("LLM_CALL_TIMEOUT_SECONDS", "120"))

_TRANSIENT_KEYWORDS = (
    "quota", "rate", "429", "resource_exhausted",
    "deadline", "unavailable", "503", "502", "500",
    "timeout", "connection",
)


try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage, SystemMessage
except ImportError:  # pragma: no cover
    ChatGoogleGenerativeAI = None  # type: ignore[assignment,misc]
    HumanMessage = SystemMessage = None  # type: ignore[assignment,misc]


class GeminiTool(Tool):
    """Gemini API client using langchain-google-genai with retry + JSON parsing.

    Public surface matches ``ClaudeTool`` so agents use either via the same
    ``tool.call(...)`` / ``tool.call_for_json(...)`` API.
    """

    name = "gemini"

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        if ChatGoogleGenerativeAI is None:
            raise ToolError(
                "The `langchain-google-genai` package isn't installed. "
                "Run: pip install -r requirements.txt"
            )
        api_key = (
            os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
        )
        if not api_key:
            raise ToolError(
                "GOOGLE_API_KEY isn't set. Get a free key at "
                "https://aistudio.google.com/ and add it to .env. "
                "See .env.example for the exact line."
            )
        self.model = model
        self.system_prompt = (PROMPTS_DIR / "system_prompt.md").read_text(encoding="utf-8")

        try:
            self._llm = ChatGoogleGenerativeAI(
                model=model,
                google_api_key=api_key,
                temperature=0,
                max_retries=MAX_RETRIES,
                request_timeout=LLM_CALL_TIMEOUT,  # hard per-call HTTP timeout (seconds)
            )
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Could not initialise Gemini client: {exc}") from exc

    # ---------------------------------------------- public interface

    def call(self, user_message: str, max_tokens: int = 4000) -> tuple[str, dict[str, Any]]:
        """Make a single Gemini API call. Returns (text, usage_dict)."""
        return self._call_internal(user_message, max_tokens)

    def call_for_json(self, user_message: str, max_tokens: int = 4000) -> tuple[dict, dict[str, Any]]:
        """Call Gemini and parse the response as JSON. Returns (parsed_dict, usage)."""
        text, usage = self.call(user_message, max_tokens=max_tokens)
        parsed = ClaudeTool._extract_json_block(text)
        return parsed, usage

    # ---------------------------------------------- internal

    def _call_internal(
        self, user_message: str, max_tokens: int
    ) -> tuple[str, dict[str, Any]]:
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=user_message),
        ]

        try:
            from telemetry import child_span as _cs
        except ImportError:
            import contextlib
            def _cs(*_a, **_kw):  # type: ignore[misc]
                return contextlib.nullcontext()

        with _cs("llm.call", **{
            "llm.provider":   "google",
            "llm.model":      self.model,
            "llm.max_tokens": max_tokens,
        }) as _span:
            try:
                # max_output_tokens is the Gemini parameter name
                response = self._llm.bind(max_output_tokens=max_tokens).invoke(messages)
            except Exception as exc:
                msg = str(exc).lower()
                if any(kw in msg for kw in _TRANSIENT_KEYWORDS):
                    raise ToolError(f"Gemini transient error: {exc}") from exc
                raise ToolError(f"Gemini API error: {exc}") from exc

            # ---- Extract text ----
            raw = response.content
            text = raw if isinstance(raw, str) else str(raw or "")

            # ---- Extract usage ----
            # langchain-google-genai stores token counts under usage_metadata
            meta  = getattr(response, "response_metadata", {}) or {}
            udata = meta.get("usage_metadata", {}) or {}
            usage: dict[str, Any] = {
                "input_tokens":  udata.get("prompt_token_count"),
                "output_tokens": udata.get("candidates_token_count"),
            }

            try:
                _span.set_attribute("llm.tokens_in",  usage["input_tokens"]  or 0)
                _span.set_attribute("llm.tokens_out", usage["output_tokens"] or 0)
            except Exception:  # noqa: BLE001
                pass

            return text, usage
