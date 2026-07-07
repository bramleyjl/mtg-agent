"""
Reconcile manual edits to a deck's Notion page body into MongoDB's `working_notes`
field on the `decks` collection.

This is the second of two write paths for per-deck working notes. The primary
path is tools.decks.update_deck_working_notes(), which the agent calls directly —
it writes the same content to Notion and MongoDB in one operation, so those two
never drift on agent-driven updates. This script exists only to catch the other
path: John hand-editing a deck's Notion page body himself, bypassing that function.

Staleness here isn't a fixed time window like the other refresh_*.py scripts —
each deck page's Notion `last_edited_time` is compared against its own
`working_notes_synced_at` in MongoDB (the timestamp of the last known sync,
whichever path set it). Only pages edited more recently get re-pulled.

Run:               python -m mtg_agent.scripts.refresh_deck_working_notes
Stale check only:  python -m mtg_agent.scripts.refresh_deck_working_notes --if-stale
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone

from mtg_agent.clients.notion_mcp import fetch_page, fetch_page_body
from mtg_agent.config import Config, load_config
from mtg_agent.db.mongodb import get_db, init_db


def _parse_notion_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def refresh(force: bool = False, config: Config | None = None) -> None:
    config = config or load_config()
    if not config.notion_mcp_url:
        print("NOTION_MCP_URL not set — skipping.", flush=True)
        return

    db = get_db()
    decks = list(db["decks"].find(
        {"notion_id": {"$ne": None}},
        {"_id": 0, "slug": 1, "notion_id": 1, "working_notes_synced_at": 1},
    ))

    updated = 0
    errors: list[str] = []
    for deck in decks:
        slug, notion_id = deck["slug"], deck["notion_id"]
        try:
            page = await fetch_page(config.notion_mcp_url, notion_id)
            if not page:
                errors.append(f"{slug}: failed to fetch page")
                continue

            last_edited = _parse_notion_datetime(page["last_edited_time"])
            synced_at = deck.get("working_notes_synced_at")
            if synced_at and synced_at.tzinfo is None:
                synced_at = synced_at.replace(tzinfo=timezone.utc)

            if not force and synced_at and last_edited <= synced_at:
                continue

            body = await fetch_page_body(config.notion_mcp_url, notion_id)
            db["decks"].update_one(
                {"slug": slug},
                {"$set": {"working_notes": body, "working_notes_synced_at": last_edited}},
            )
            updated += 1
            print(f"  {slug}: working_notes updated (Notion edited {last_edited.isoformat()})", flush=True)
        except Exception as e:
            errors.append(f"{slug}: {e}")

    print(f"Done. {updated} deck(s) updated out of {len(decks)} checked.", flush=True)
    if errors:
        print(f"Errors: {errors}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--if-stale",
        action="store_true",
        help="Only refresh decks whose Notion page was edited since the last known working_notes sync.",
    )
    args = parser.parse_args()

    config = load_config()
    init_db(config.mongodb_uri, config.mongodb_db)

    try:
        asyncio.run(refresh(force=not args.if_stale, config=config))
    except Exception as e:
        print(f"Error refreshing deck working notes: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
