"""Startup secret validation.

Called once when the app or CLI boots. Raises RuntimeError with a clear
message if any required environment variable is unset, so misconfiguration
is caught at startup rather than mid-run with a cryptic API error.

Optional groups are checked as a set: if ANY var in the group is set,
ALL vars in that group must be set (partial config is worse than none).
"""

from __future__ import annotations

import os


_REQUIRED = [
    ("ANTHROPIC_API_KEY", "Anthropic API key — required for Claude models"),
]

# Set REDIS_REQUIRED=1 in multi-replica deployments so the app refuses to start
# when Redis is unreachable, rather than silently falling back to per-pod budgets.
_REDIS_REQUIRED = os.environ.get("REDIS_REQUIRED", "0").strip() in ("1", "true", "yes")

_OPTIONAL_GROUPS = [
    (
        ["JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"],
        "Jira live integration (all three must be set together)",
    ),
    (
        ["CONFLUENCE_BASE_URL", "CONFLUENCE_EMAIL", "CONFLUENCE_API_TOKEN"],
        "Confluence live integration (all three must be set together)",
    ),
    (
        ["GOOGLE_API_KEY"],
        "Google Gemini models",
    ),
    (
        ["GITHUB_TOKEN"],
        "GitHub MCP live integration",
    ),
]


def check_secret_formats() -> list[str]:
    """Validate the format of configured secrets (non-fatal, warnings only).

    Catches obvious misconfigurations — wrong key pasted into the wrong slot,
    placeholder values left from .env.example, or a cookie secret that is too
    short to be cryptographically safe.  Does NOT make any network calls.
    """
    warnings: list[str] = []

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key and not anthropic_key.startswith("sk-ant-"):
        warnings.append(
            "ANTHROPIC_API_KEY does not start with 'sk-ant-' — "
            "this looks like the wrong key format. "
            "Verify it was copied from console.anthropic.com."
        )

    cookie_secret = os.environ.get("AUTH_COOKIE_SECRET", "")
    if cookie_secret:
        if cookie_secret.lower().startswith("change-me"):
            warnings.append(
                "AUTH_COOKIE_SECRET is still set to the placeholder value from .env.example. "
                "Generate a real secret: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        elif len(cookie_secret) < 32:
            warnings.append(
                f"AUTH_COOKIE_SECRET is only {len(cookie_secret)} characters — "
                "minimum 32 required for cryptographic safety. "
                "Regenerate: python -c \"import secrets; print(secrets.token_hex(32))\""
            )

    pagerduty_key = os.environ.get("PAGERDUTY_ROUTING_KEY", "")
    if pagerduty_key and len(pagerduty_key) < 20:
        warnings.append(
            "PAGERDUTY_ROUTING_KEY looks too short — expected a 32-character routing key. "
            "Verify it in your PagerDuty service settings."
        )

    return warnings


def check_python_version() -> list[str]:
    """Return warnings if Python version is below 3.10 (MCP packages unavailable)."""
    import sys
    if sys.version_info < (3, 10):
        return [
            f"Python {sys.version_info.major}.{sys.version_info.minor} detected. "
            "MCP packages (mcp, mcp-atlassian) require Python 3.10+. "
            "ATLASSIAN_MCP_ENABLED and GITHUB_MCP_ENABLED will fall back to REST/fixture. "
            "Use venv313 (./start.sh) for full MCP support."
        ]
    return []


def check_required_secrets() -> list[str]:
    """Validate secrets. Returns a list of warning strings (non-fatal).

    Raises RuntimeError for any missing *required* secret so the app
    refuses to start rather than failing mid-run with a cryptic error.

    Returns warning strings for partially-configured optional groups so
    callers can surface them in the UI without blocking startup.
    """
    # Hard failures — required for any run.
    missing_required = [
        desc
        for var, desc in _REQUIRED
        if not os.environ.get(var, "").strip()
    ]
    if missing_required:
        raise RuntimeError(
            "Missing required environment variable(s):\n"
            + "\n".join(f"  • {d}" for d in missing_required)
            + "\n\nSet them in your deployment environment (not in .env for production). "
            "See .env.example for local development."
        )

    # Redis strict mode — fail fast when REDIS_REQUIRED=1 and Redis is unreachable.
    if _REDIS_REQUIRED:
        redis_url = os.environ.get("REDIS_URL", "").strip()
        if not redis_url:
            raise RuntimeError(
                "REDIS_REQUIRED=1 but REDIS_URL is not set. "
                "Provide a Redis connection string or remove REDIS_REQUIRED."
            )
        try:
            import redis as _redis_mod
            _r = _redis_mod.from_url(redis_url, socket_connect_timeout=3, socket_timeout=3)
            _r.ping()
        except Exception as _redis_exc:
            raise RuntimeError(
                f"REDIS_REQUIRED=1 but Redis at {redis_url!r} is unreachable: {_redis_exc}. "
                "Fix the Redis connection or remove REDIS_REQUIRED to allow file-based fallback."
            ) from _redis_exc

    # ChromaDB SPOF advisory — warn when using file-backed mode without an HA server.
    _use_chromadb = os.environ.get("USE_CHROMADB", "").lower() in ("1", "true", "yes")
    _chroma_server = os.environ.get("CHROMADB_SERVER_URL", "").strip()
    if _use_chromadb and not _chroma_server:
        warnings_pre = [
            "USE_CHROMADB=1 but CHROMADB_SERVER_URL is not set. "
            "The vector index is backed by a single local directory (.cache/memory/chroma). "
            "A volume failure will lose the index (non-critical: rebuilt on next run). "
            "For HA, deploy a ChromaDB server and set CHROMADB_SERVER_URL=http://chroma-host:8000."
        ]
    else:
        warnings_pre = []

    # Soft warnings — optional but must be complete if partially set.
    warnings: list[str] = list(warnings_pre)
    for vars_in_group, label in _OPTIONAL_GROUPS:
        set_vars = [v for v in vars_in_group if os.environ.get(v, "").strip()]
        if not set_vars:
            continue  # group not configured at all — fine
        missing = [v for v in vars_in_group if not os.environ.get(v, "").strip()]
        if missing:
            warnings.append(
                f"{label}: partially configured — missing {', '.join(missing)}. "
                "Set all vars in the group or none."
            )

    return warnings


def get_configured_integrations() -> dict[str, bool]:
    """Return which optional integrations are fully configured.

    Used by the UI to show/hide live-source toggles and the Jira push button.
    """
    return {
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
        "jira": all(
            os.environ.get(v, "").strip()
            for v in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN")
        ),
        "confluence": all(
            os.environ.get(v, "").strip()
            for v in ("CONFLUENCE_BASE_URL", "CONFLUENCE_EMAIL", "CONFLUENCE_API_TOKEN")
        ),
        "google": bool(os.environ.get("GOOGLE_API_KEY", "").strip()),
        "github": bool(os.environ.get("GITHUB_TOKEN", "").strip()),
        "atlassian_mcp": bool(os.environ.get("ATLASSIAN_MCP_ENABLED", "").strip()),
        "github_mcp": bool(os.environ.get("GITHUB_MCP_ENABLED", "").strip()),
    }
