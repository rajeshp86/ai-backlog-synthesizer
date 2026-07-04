"""Security scanning — prompt-injection detection and output safety checks.

Two scanners wired into the LangGraph pipeline:

    InputSanitizer
        Called in ``initialize_node`` BEFORE any LLM stage sees user text.
        Scans transcript + constraint text for prompt-injection patterns.
        Returns (sanitized_text, findings).  Injections are replaced with
        ``[INJECTION REDACTED]`` so the pipeline continues safely even when
        adversarial content is present.

    OutputScanner
        Called in ``finalize_node`` AFTER all agents complete.
        Scans synthesised story/epic text for:
          - PII leakage    (emails, phones, SSNs, card numbers)
          - Toxicity       (threats, hate-speech markers)
          - Demographic bias (stereotypical language in user personas)

Both scanners return ``SecurityFinding`` objects.  ``SecurityFinding`` is
structurally identical to ``GuardrailFinding`` (same ``code``, ``severity``,
``message``, ``story_id`` fields) so the UI's existing Guardrails tab and
audit trail surface security events without any extra wiring.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass


@dataclass
class SecurityFinding:
    """One security event.  Interface mirrors GuardrailFinding intentionally."""
    code: str
    severity: str         # "error" | "warn" | "info"
    message: str
    story_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════ Prompt-Injection Detection ════════

# Each rule: (regex_pattern, re_flags, finding_code, human_label)
_INJECTION_RULES: list[tuple[str, int, str, str]] = [
    # --- Direct instruction-override attempts ---
    (
        r"\b(ignore|disregard|forget|override|bypass)\s+(all\s+)?"
        r"(previous|prior|above|the\s+following|your)\s+"
        r"(instructions?|rules?|guidelines?|constraints?|prompts?|context)\b",
        re.IGNORECASE,
        "injection_instruction_override",
        "Instruction-override attempt",
    ),
    # --- Role-hijacking ---
    (
        r"\b(you\s+are\s+now|you\s+must\s+now|from\s+now\s+on\s+you\s+are|"
        r"act\s+as|pretend\s+(to\s+be|you\s+are)|"
        r"your\s+new\s+(role|identity|persona)\s+is|"
        r"roleplay\s+as|assume\s+the\s+role\s+of)\b",
        re.IGNORECASE,
        "injection_role_hijack",
        "Role-hijacking attempt",
    ),
    # --- System-prompt extraction ---
    (
        r"\b(reveal|print|output|display|leak|expose|show\s+me)\s+(your\s+)?"
        r"(system\s+prompt|internal\s+instructions?|hidden\s+instructions?|"
        r"prompt\s+template|original\s+instructions?)\b",
        re.IGNORECASE,
        "injection_prompt_leak",
        "System-prompt extraction attempt",
    ),
    # --- LLM tokenizer special tokens ---
    (
        r"(<\|endoftext\|>|<\|im_start\|>|<\|im_end\|>|"
        r"\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>|\[SYSTEM\]|"
        r"<s>|</s>|<\|EOT\|>)",
        re.IGNORECASE,
        "injection_special_token",
        "LLM tokenizer special-token injected",
    ),
    # --- Chat-role prefix injection (beginning of a line) ---
    (
        r"(?m)^(SYSTEM|USER|ASSISTANT|HUMAN|AI|CLAUDE|GPT|OPENAI)\s*[:：]\s",
        0,
        "injection_chat_role",
        "Chat-role prefix injection",
    ),
    # --- Jailbreak keywords ---
    (
        r"\b(jailbreak|jail\s*break|DAN\s+mode|developer\s+mode|god\s+mode|"
        r"bypass\s+(content\s+)?(filter|safety|moderation|guardrail)|"
        r"unrestricted\s+mode|no\s+restrictions\s+mode)\b",
        re.IGNORECASE,
        "injection_jailbreak",
        "Jailbreak keyword detected",
    ),
    # --- Data-exfiltration attempts ---
    (
        r"\b(send|POST|exfiltrate|transmit|forward|email)\s+"
        r"(this|the\s+(above|following|results?|data|response|output))\s+"
        r"(to|at)\s+\S+",
        re.IGNORECASE,
        "injection_exfiltration",
        "Data-exfiltration attempt",
    ),
    # --- Verbatim-repeat / prompt-leaking ---
    (
        r"\brepeat\s+(the\s+)?(above|everything|all\s+of\s+this)\s+"
        r"(verbatim|exactly|word[\s-]for[\s-]word)\b",
        re.IGNORECASE,
        "injection_verbatim_repeat",
        "Verbatim-repeat / prompt-leaking attempt",
    ),
]

_COMPILED_INJECTION: list[tuple[re.Pattern, str, str]] = [
    (re.compile(pattern, flags), code, label)
    for pattern, flags, code, label in _INJECTION_RULES
]

_REDACT = "[INJECTION REDACTED]"


class InputSanitizer:
    """Scan and sanitize user-supplied text before it enters the LLM pipeline.

    Usage::

        clean_text, findings = InputSanitizer.scan(raw_text, source="transcript")
        # Pass clean_text to the pipeline; surface findings in the audit trail.
    """

    @staticmethod
    def scan(text: str, source: str = "input") -> tuple[str, list[SecurityFinding]]:
        """Scan *text* for injection patterns.

        Returns:
            sanitized   The text with injections replaced by ``[INJECTION REDACTED]``.
            findings    One ``SecurityFinding`` per matched rule (not per occurrence).
        """
        if not text:
            return text, []

        findings: list[SecurityFinding] = []
        sanitized = text

        for pattern, code, label in _COMPILED_INJECTION:
            matches = list(pattern.finditer(sanitized))
            if not matches:
                continue
            count = len(matches)
            findings.append(SecurityFinding(
                code=code,
                severity="error",
                message=(
                    f"{label} detected in {source} "
                    f"({count} occurrence{'s' if count > 1 else ''}). "
                    "Content redacted before reaching the LLM."
                ),
            ))
            sanitized = pattern.sub(_REDACT, sanitized)

        return sanitized, findings


# ═══════════════════════════════════════════════ Output Safety Scanning ════════

# --- PII patterns ---
_PII_RULES: list[tuple[str, int, str, str]] = [
    (
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
        0,
        "pii_email",
        "Email address",
    ),
    (
        r"\b(\+?1[\s.\-]?)?\(?[2-9]\d{2}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b",
        0,
        "pii_phone",
        "Phone number",
    ),
    (
        r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b",
        0,
        "pii_ssn",
        "Social Security Number pattern",
    ),
    (
        # 13-19 digit run with optional spaces/dashes — catches card numbers.
        # Deliberately not Luhn-checking: a false positive is a safe failure.
        r"\b(?:\d[ \-]?){13,19}\d\b",
        0,
        "pii_card_number",
        "Potential payment card number",
    ),
]

_COMPILED_PII: list[tuple[re.Pattern, str, str]] = [
    (re.compile(p, f), c, lbl) for p, f, c, lbl in _PII_RULES
]

# --- Toxicity — curated high-confidence phrases only.
# Intentionally narrow to avoid false positives in a product-backlog context.
_TOXICITY_RULES: list[tuple[str, str]] = [
    (r"\b(kill|exterminate|slaughter)\s+(all\s+)?(the\s+)?(users?|customers?|people|staff)\b",
     "toxicity_threat"),
    (r"\b(white\s+supremac|nazi|fascist)\s+(agenda|feature|requirement|story|design)\b",
     "toxicity_hate_content"),
    (r"\b(rape|sexually\s+assault|molest)\b",
     "toxicity_explicit"),
]

_COMPILED_TOXICITY: list[tuple[re.Pattern, str]] = [
    (re.compile(p, re.IGNORECASE), c) for p, c in _TOXICITY_RULES
]

# --- Demographic bias — stereotypical language in "As a [user]…" story clauses.
_BIAS_RULES: list[tuple[str, int, str, str]] = [
    (
        r"\bAs\s+a\s+(housewife|homemaker|little\s+old\s+lady|ditzy)\b",
        re.IGNORECASE,
        "bias_gender_stereotype",
        "Gender-stereotyped user persona in story",
    ),
    (
        # "elderly [people/users/customers] cannot/can't/won't/struggle with"
        r"\b(elderly(\s+\w+)?|old\s+people|seniors?(\s+\w+)?)\s+"
        r"(can'?t|cannot|won'?t|are\s+unable\s+to|don'?t\s+understand|struggle\s+with)\b",
        re.IGNORECASE,
        "bias_age_assumption",
        "Negative age-based capability assumption",
    ),
    (
        r"\b(non[\s-]technical|non[\s-]native\s+speakers?|foreign\s+users?)\s+"
        r"(can'?t|cannot|won'?t|should\s+not|must\s+not|are\s+unable)\b",
        re.IGNORECASE,
        "bias_demographic_assumption",
        "Negative demographic capability assumption",
    ),
    (
        r"\b(simple|dumbed[\s-]down|idiot[\s-]proof)\s+(interface|UI|UX|mode|version)\s+"
        r"for\s+(women|elderly|seniors?|non[\s-]technical)\b",
        re.IGNORECASE,
        "bias_condescending_design",
        "Condescending design assumption for a demographic group",
    ),
    (
        # Flags stories that assign systematically low priority to accessibility
        r"\b(accessibility|a11y)\b.{0,80}\bpriority\s*[=:]\s*(low|won.?t\s+fix)\b",
        re.IGNORECASE,
        "bias_accessibility_deprioritised",
        "Accessibility explicitly deprioritised — review for inclusivity compliance",
    ),
]

_COMPILED_BIAS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(p, f), c, lbl) for p, f, c, lbl in _BIAS_RULES
]


def _story_text(story: dict) -> str:
    """Concatenate all scannable text fields from a story dict."""
    return " ".join(filter(None, [
        story.get("title", ""),
        story.get("description", ""),
        story.get("user_story", ""),
        " ".join(story.get("acceptance_criteria") or []),
        story.get("priority_rationale", ""),
    ]))


class OutputScanner:
    """Scan synthesised stories/epics for PII, toxicity, and demographic bias.

    Usage::

        findings = OutputScanner.scan_stories(epics)
        # Merge into guardrail_findings before returning to the caller.
    """

    @classmethod
    def scan_stories(cls, epics: list[dict]) -> list[SecurityFinding]:
        """Scan every story inside *epics*.  Returns all findings."""
        findings: list[SecurityFinding] = []
        for epic in (epics or []):
            for story in (epic.get("stories") or []):
                sid = story.get("id")
                text = _story_text(story)
                if not text:
                    continue
                findings.extend(cls._scan_pii(text, sid))
                findings.extend(cls._scan_toxicity(text, sid))
                findings.extend(cls._scan_bias(text, sid))
        return findings

    @staticmethod
    def _scan_pii(text: str, story_id: str | None) -> list[SecurityFinding]:
        out: list[SecurityFinding] = []
        for pattern, code, label in _COMPILED_PII:
            if pattern.search(text):
                out.append(SecurityFinding(
                    code=code,
                    severity="error",
                    message=(
                        f"{label} pattern found in story output. "
                        "The LLM may have hallucinated or echoed PII from the input. "
                        "Review before publishing to Jira."
                    ),
                    story_id=story_id,
                ))
        return out

    @staticmethod
    def _scan_toxicity(text: str, story_id: str | None) -> list[SecurityFinding]:
        out: list[SecurityFinding] = []
        for pattern, code in _COMPILED_TOXICITY:
            if pattern.search(text):
                out.append(SecurityFinding(
                    code=code,
                    severity="error",
                    message=(
                        "Potentially toxic language detected in story output. "
                        "Review immediately before this story is published."
                    ),
                    story_id=story_id,
                ))
        return out

    @staticmethod
    def _scan_bias(text: str, story_id: str | None) -> list[SecurityFinding]:
        out: list[SecurityFinding] = []
        for pattern, code, label in _COMPILED_BIAS:
            if pattern.search(text):
                out.append(SecurityFinding(
                    code=code,
                    severity="warn",
                    message=(
                        f"{label}. "
                        "Review this story for inclusive language before publishing."
                    ),
                    story_id=story_id,
                ))
        return out
