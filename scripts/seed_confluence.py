"""Seed a Confluence space with the bundled sample wiki content.

Reads:
  - samples/architecture_constraints.md  → "Quantum Technologies — Architecture Constraints"
  - samples/product_strategy.md          → "Quantum Technologies — Product Strategy"

Usage:
    python scripts/seed_confluence.py              # auto-pick the first space
    python scripts/seed_confluence.py --space DEV  # target a specific space key/id
    python scripts/seed_confluence.py --dry-run    # render storage XHTML only

Reads credentials from .env (CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL,
CONFLUENCE_API_TOKEN). If those aren't set, falls back to JIRA_* (same
Atlassian tenant, same token).

The script is idempotent in spirit but not in mechanism: Confluence returns
409 if a page with the same title already exists in the space. Either delete
the prior page from the UI or pick a new title.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT / "src"))

from tools.base import ToolError  # noqa: E402
from tools.confluence_tool import (  # noqa: E402
    ConfluenceTool,
    markdown_to_confluence_storage,
)


# The two sample files this script pushes. Each entry: source path + page title.
SEEDS: list[tuple[Path, str]] = [
    (
        ROOT / "samples" / "architecture_constraints.md",
        "Quantum Technologies — Architecture Constraints",
    ),
    (
        ROOT / "samples" / "product_strategy.md",
        "Quantum Technologies — Product Strategy",
    ),
]


def _resolve_credentials() -> None:
    """Promote JIRA_* into CONFLUENCE_* if the latter aren't set.

    Same Atlassian tenant, same token works for both products. Saves the
    user from having to maintain two copies of the same secret in `.env`.
    """
    pairs = [
        ("CONFLUENCE_BASE_URL", "JIRA_BASE_URL"),
        ("CONFLUENCE_EMAIL",    "JIRA_EMAIL"),
        ("CONFLUENCE_API_TOKEN","JIRA_API_TOKEN"),
    ]
    for conf, jira in pairs:
        if not os.environ.get(conf) and os.environ.get(jira):
            os.environ[conf] = os.environ[jira]
    # Default to live for this script — its whole purpose is to write.
    os.environ.setdefault("CONFLUENCE_MODE", "live")


def _pick_space(tool: ConfluenceTool, requested: str | None) -> dict:
    """Resolve `--space` to a Confluence space dict.

    Accepts a numeric id, a space key, or None (= pick first global space).
    Personal spaces (type=personal) are de-prioritised because they're
    typically the wrong default for demoing to a team.
    """
    spaces = tool.list_spaces(limit=50)
    if not spaces:
        raise SystemExit("No Confluence spaces visible to this account.")

    if requested:
        req = requested.strip()
        for s in spaces:
            if str(s.get("id")) == req or s.get("key") == req:
                return s
        print(f"[warn] Space {requested!r} not found. Available spaces:", file=sys.stderr)
        for s in spaces:
            print(f"  id={s.get('id')}  key={s.get('key')}  name={s.get('name')!r}", file=sys.stderr)
        raise SystemExit(2)

    # Heuristic default: first non-personal space, else first space.
    for s in spaces:
        if s.get("type") != "personal":
            return s
    return spaces[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--space", default=None,
                        help="Target space (numeric id or key). Default: first non-personal space.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Convert markdown and print storage XHTML; don't call the API.")
    args = parser.parse_args()

    _resolve_credentials()
    tool = ConfluenceTool()

    if args.dry_run:
        for src, title in SEEDS:
            md = src.read_text(encoding="utf-8")
            storage = markdown_to_confluence_storage(md)
            print(f"\n========== {title} ==========")
            print(f"  source: {src}")
            print(f"  storage XHTML length: {len(storage)} chars")
            print(storage[:1200])
            print("..." if len(storage) > 1200 else "")
        return 0

    # Verify all source files exist before we make any API calls.
    for src, _ in SEEDS:
        if not src.exists():
            print(f"[error] Missing source: {src}", file=sys.stderr)
            return 1

    try:
        space = _pick_space(tool, args.space)
    except ToolError as e:
        print(f"[error] {e}", file=sys.stderr)
        if "401" in str(e) or "403" in str(e):
            print(
                "\nConfluence rejected the credentials. Possible causes:\n"
                "  - Confluence isn't activated on this tenant\n"
                "  - The API token is scoped to Jira-only\n"
                "  - The account doesn't have Confluence access\n",
                file=sys.stderr,
            )
        return 1

    print(f"Target space: id={space.get('id')}  key={space.get('key')}  "
          f"name={space.get('name')!r}  type={space.get('type')}")

    created = []
    for src, title in SEEDS:
        md = src.read_text(encoding="utf-8")
        storage = markdown_to_confluence_storage(md)
        print(f"\n→ Creating page: {title!r}  ({len(md):,} chars MD → {len(storage):,} XHTML)")
        try:
            page = tool.create_page(
                space_id=str(space["id"]),
                title=title,
                body_storage=storage,
            )
        except ToolError as e:
            print(f"[error] Could not create {title!r}: {e}", file=sys.stderr)
            continue
        page_id = page.get("id")
        webui = (page.get("_links") or {}).get("webui", "")
        base_url = os.environ.get("CONFLUENCE_BASE_URL", "").rstrip("/")
        full_url = f"{base_url}/wiki{webui}" if webui else f"(page id {page_id})"
        print(f"  ✓ Created. id={page_id}\n  URL: {full_url}")
        created.append({"title": title, "id": page_id, "url": full_url})

    print("\n" + "=" * 60)
    print(f" Done — {len(created)}/{len(SEEDS)} pages created")
    for c in created:
        print(f"  · {c['title']}\n      {c['url']}")
    return 0 if created else 1


if __name__ == "__main__":
    sys.exit(main())
