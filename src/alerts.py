"""Security and operational alerting.

Provides ``post_security_alert`` — called after any ``SecurityFinding`` with
severity "error" is produced by the pipeline.  Supports three destinations,
selected by environment variable:

  Slack   — ``SECURITY_WEBHOOK_URL`` pointing at an Incoming Webhook URL.
  Teams   — same var; auto-detected by the URL path containing "webhook.office.com".
  Generic — any URL; receives the canonical JSON payload described below.
  PagerDuty — set ``PAGERDUTY_ROUTING_KEY``; uses the Events API v2.

All destinations are fire-and-forget (2-second timeout, logged on failure).
If no destination is configured the function logs at WARNING and returns.

Canonical payload (Slack / generic POST)
-----------------------------------------
{
  "run_id":     "<uuid>",
  "user":       "<email or anonymous>",
  "findings":   [{"code": "...", "severity": "...", "message": "...", "story_id": null}],
  "timestamp":  "2026-06-10T12:34:56Z"
}
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from logger_setup import get_logger

logger = get_logger(__name__)

_WEBHOOK_URL       = os.environ.get("SECURITY_WEBHOOK_URL", "").strip()
_PAGERDUTY_KEY     = os.environ.get("PAGERDUTY_ROUTING_KEY", "").strip()
_MIN_SEVERITY      = os.environ.get("SECURITY_ALERT_MIN_SEVERITY", "error").strip().lower()
_ALERT_TIMEOUT     = 2.0   # seconds — fire-and-forget; never blocks the pipeline

_SEVERITY_RANK = {"info": 0, "warn": 1, "error": 2}


def _should_alert(severity: str) -> bool:
    return _SEVERITY_RANK.get(severity.lower(), 0) >= _SEVERITY_RANK.get(_MIN_SEVERITY, 2)


def post_security_alert(
    findings: list[dict],
    *,
    run_id: str = "",
    user: str = "anonymous",
) -> None:
    """Fire an alert for any findings that meet the minimum severity threshold.

    Safe to call with an empty list — returns immediately.
    """
    alertable = [f for f in findings if _should_alert(f.get("severity", "info"))]
    if not alertable:
        return

    logger.warning(
        "Security alert: %d finding(s) (run=%s user=%s): %s",
        len(alertable),
        run_id or "—",
        user,
        [f.get("code") for f in alertable],
    )

    if not _WEBHOOK_URL and not _PAGERDUTY_KEY:
        logger.info(
            "No SECURITY_WEBHOOK_URL or PAGERDUTY_ROUTING_KEY configured — "
            "alert logged only. Set one to enable push notifications."
        )
        return

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "run_id":    run_id,
        "user":      user,
        "findings":  alertable,
        "timestamp": timestamp,
    }

    if _WEBHOOK_URL:
        _post_webhook(payload)
    if _PAGERDUTY_KEY:
        _post_pagerduty(payload)


def _post_webhook(payload: dict) -> None:
    """POST to Slack Incoming Webhook, MS Teams webhook, or a generic URL."""
    try:
        import urllib.request
        url = _WEBHOOK_URL
        if "webhook.office.com" in url:
            # MS Teams adaptive-card format
            body = _teams_card(payload)
        else:
            # Slack / generic
            body = _slack_message(payload)

        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_ALERT_TIMEOUT) as resp:  # noqa: S310
            status = resp.getcode()
            if status not in (200, 204):
                logger.warning("Security webhook returned HTTP %d", status)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Security webhook delivery failed: %s", exc)


def _post_pagerduty(payload: dict) -> None:
    """POST to PagerDuty Events API v2."""
    try:
        import urllib.request
        findings = payload["findings"]
        summary = f"[Backlog Synthesizer] {len(findings)} security finding(s): " + ", ".join(
            f.get("code", "?") for f in findings[:3]
        ) + ("…" if len(findings) > 3 else "")

        body = {
            "routing_key":  _PAGERDUTY_KEY,
            "event_action": "trigger",
            "payload": {
                "summary":   summary,
                "source":    "backlog-synthesizer",
                "severity":  "critical",
                "timestamp": payload["timestamp"],
                "custom_details": payload,
            },
        }
        req = urllib.request.Request(
            "https://events.pagerduty.com/v2/enqueue",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_ALERT_TIMEOUT) as resp:  # noqa: S310
            status = resp.getcode()
            if status != 202:
                logger.warning("PagerDuty Events API returned HTTP %d", status)
    except Exception as exc:  # noqa: BLE001
        logger.warning("PagerDuty delivery failed: %s", exc)


def _slack_message(payload: dict) -> dict:
    findings = payload["findings"]
    lines = [
        f"*:rotating_light: Backlog Synthesizer — {len(findings)} security finding(s)*",
        f"Run: `{payload['run_id'] or '—'}`   User: `{payload['user']}`",
        "",
    ]
    for f in findings:
        icon = ":red_circle:" if f.get("severity") == "error" else ":warning:"
        lines.append(f"{icon} `{f.get('code', '?')}` — {f.get('message', '')}")
    return {"text": "\n".join(lines)}


def _teams_card(payload: dict) -> dict:
    findings = payload["findings"]
    facts = [
        {"name": "Run ID", "value": payload["run_id"] or "—"},
        {"name": "User",   "value": payload["user"]},
        {"name": "Findings", "value": str(len(findings))},
    ]
    for f in findings:
        facts.append({"name": f.get("code", "?"), "value": f.get("message", "")[:200]})
    return {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "themeColor": "FF0000",
        "summary": f"Security alert — {len(findings)} finding(s)",
        "sections": [{"activityTitle": "Backlog Synthesizer Security Alert", "facts": facts}],
    }
