"""Seed the live Jira project with the bundled `samples/jira_backlog.json`.

After this runs, the live Jira project will hold the same demo-tuned
tickets that the bundled meeting_notes.txt is designed to overlap with.
That means picking "Live Jira" in the UI will produce the same
duplicates/conflicts/gaps you'd see picking the bundled JSON.

Usage:
    python scripts/seed_jira.py                  # use JIRA_PROJECT_KEY from .env
    python scripts/seed_jira.py --project NS     # target a specific project
    python scripts/seed_jira.py --dry-run        # preview without writing
    python scripts/seed_jira.py --limit 10       # cap at N tickets

Idempotency: each created issue gets the label `backlog-synth-seed-v1`.
Re-running asks Jira for the existing labelled issues first; anything
already present is skipped. To force a re-create, delete the labelled
issues from Jira and re-run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT / "src"))

DEFAULT_FIXTURE = ROOT / "samples" / "jira_backlog.json"
SEED_LABEL = "backlog-synth-seed-v1"


def _require_env() -> tuple[str, str, str, str]:
    base = (os.environ.get("JIRA_BASE_URL") or "").rstrip("/")
    email = os.environ.get("JIRA_EMAIL") or ""
    token = os.environ.get("JIRA_API_TOKEN") or ""
    project = os.environ.get("JIRA_PROJECT_KEY") or ""
    missing = [k for k, v in (
        ("JIRA_BASE_URL", base),
        ("JIRA_EMAIL", email),
        ("JIRA_API_TOKEN", token),
        ("JIRA_PROJECT_KEY", project),
    ) if not v]
    if missing:
        raise SystemExit(f"Missing env: {', '.join(missing)}. Configure .env.")
    return base, email, token, project


def _adf_paragraph(text: str) -> dict:
    """Convert a plain string to a minimal ADF (Atlassian Document Format)
    paragraph block. Jira Cloud's v3 issue API requires ADF for the
    description field. Newlines become separate paragraphs."""
    paragraphs: list[dict] = []
    for chunk in (text or "").split("\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        paragraphs.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": chunk}],
        })
    if not paragraphs:
        # Empty description still needs valid ADF
        paragraphs = [{"type": "paragraph", "content": []}]
    return {"version": 1, "type": "doc", "content": paragraphs}


def _existing_seeded_keys(session, base: str, project: str) -> set[str]:
    """Return the Jira keys of issues already labelled by a prior seed run.

    Lets the script run idempotently — we skip issues that already exist
    instead of creating duplicates each run.
    """
    jql = f'project = "{project}" AND labels = "{SEED_LABEL}"'
    url = f"{base}/rest/api/3/search/jql"
    resp = session.get(
        url,
        params={"jql": jql, "fields": "summary", "maxResults": 100},
        timeout=20,
    )
    if resp.status_code >= 400:
        # Auth might disallow search — proceed assuming nothing exists.
        return set()
    summaries = {i.get("fields", {}).get("summary", "")
                 for i in resp.json().get("issues", [])}
    return summaries


def _post_issue(session, base: str, project: str, ticket: dict) -> dict:
    payload = {
        "fields": {
            "project": {"key": project},
            "summary": ticket.get("summary") or ticket.get("title") or "(no title)",
            "description": _adf_paragraph(ticket.get("description", "")),
            "issuetype": {"name": "Task"},
            "labels": list(set((ticket.get("labels") or []) + [SEED_LABEL])),
        }
    }
    url = f"{base}/rest/api/3/issue"
    resp = session.post(url, json=payload, timeout=30)
    if resp.status_code >= 400:
        # Some Jira projects forbid setting labels on create or require
        # specific issue types. Retry without labels + as Task.
        payload["fields"].pop("labels", None)
        resp = session.post(url, json=payload, timeout=30)
        if resp.status_code >= 400:
            raise SystemExit(
                f"Jira create issue failed {resp.status_code}: {resp.text[:300]}"
            )
    return resp.json()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=None,
                        help="Override JIRA_PROJECT_KEY for the target project.")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE),
                        help="Path to the source JSON file (default: samples/jira_backlog.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be created; don't call the API.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap how many tickets to create.")
    args = parser.parse_args()

    base, email, token, default_project = _require_env()
    project = args.project or default_project

    try:
        import requests
    except ImportError:
        raise SystemExit("'requests' package required. pip install requests.")

    session = requests.Session()
    session.auth = (email, token)
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

    fixture = Path(args.fixture)
    if not fixture.exists():
        raise SystemExit(f"Source file not found: {fixture}")
    tickets = json.loads(fixture.read_text(encoding="utf-8"))
    if isinstance(tickets, dict):
        tickets = tickets.get("items", [])
    if args.limit:
        tickets = tickets[: args.limit]

    if args.dry_run:
        print(f"[dry-run] Would create {len(tickets)} ticket(s) in project {project!r}")
        for t in tickets[:5]:
            print(f"  · {t.get('summary') or t.get('title')!r}")
        if len(tickets) > 5:
            print(f"  ... and {len(tickets) - 5} more")
        return 0

    print(f"Target project: {project}")
    print(f"Source: {fixture}  ({len(tickets)} ticket(s))")

    print("\n→ Checking for existing seeded issues...")
    existing_summaries = _existing_seeded_keys(session, base, project)
    print(f"  Found {len(existing_summaries)} previously-seeded issue(s); will skip those.")

    created = 0
    skipped = 0
    for i, t in enumerate(tickets, start=1):
        summary = t.get("summary") or t.get("title") or f"Untitled #{i}"
        if summary in existing_summaries:
            print(f"  [{i}/{len(tickets)}] SKIP (already seeded): {summary[:60]}")
            skipped += 1
            continue
        try:
            res = _post_issue(session, base, project, t)
            key = res.get("key")
            print(f"  [{i}/{len(tickets)}] ✓ {key}  {summary[:60]}")
            created += 1
        except SystemExit as e:
            # Hard error — surface, but continue with the rest so a single
            # bad ticket doesn't abort the whole seed.
            print(f"  [{i}/{len(tickets)}] ✗ {e}")
            continue

    print(f"\nDone. Created {created}, skipped {skipped}, total {len(tickets)}.")
    return 0 if created or skipped else 1


if __name__ == "__main__":
    sys.exit(main())
