"""
Download the official WotC Commander Format Panel announcements about the
Commander Brackets system and upsert into MongoDB. These are the full-text
articles behind the terse bracket descriptions on the format page
(see refresh_commander_brackets.py). Parsing/discovery logic lives in
mtg_agent.clients.wotc_news, shared with refresh_commander_banr_announcements.py.

Run:               python -m mtg_agent.scripts.refresh_commander_bracket_announcements
Stale check only:  python -m mtg_agent.scripts.refresh_commander_bracket_announcements --if-stale
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone

from pymongo import ReplaceOne

from mtg_agent.clients.wotc_news import chunk_announcement, discover_announcement_urls, fetch_announcement
from mtg_agent.config import load_config
from mtg_agent.db.mongodb import get_db, init_db, replace_content_chunks

SEARCH_URL = "https://magic.wizards.com/en/news/announcements?search=Commander%20Bracket"

STALE_AFTER_DAYS = 56  # ~8 weeks
META_COLLECTION = "commander_bracket_announcements_meta"
COLLECTION = "commander_bracket_announcements"
CHUNK_CATEGORY = "commander_bracket_announcements"


def _last_updated() -> datetime | None:
    meta = get_db()[META_COLLECTION].find_one({"_id": "last_updated"})
    return meta["timestamp"] if meta else None


def _is_stale() -> bool:
    last = _last_updated()
    if last is None:
        return True
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return last < now - timedelta(days=STALE_AFTER_DAYS)


def refresh(force: bool = False) -> None:
    if not force and not _is_stale():
        print(f"Bracket announcements are fresh (checked within the last {STALE_AFTER_DAYS} days) — nothing to do.", flush=True)
        return

    print(f"Discovering announcement URLs from {SEARCH_URL}...", flush=True)
    urls = discover_announcement_urls(SEARCH_URL)
    print(f"  Found {len(urls)} announcements.", flush=True)

    docs = []
    for url in urls:
        print(f"Downloading {url}...", flush=True)
        doc = fetch_announcement(url)
        chunks = chunk_announcement(doc, CHUNK_CATEGORY)
        print(f"  {doc['title']} ({doc['published_date']}, {len(doc['text'])} chars, {len(chunks)} chunks)", flush=True)
        docs.append(doc)
        replace_content_chunks(url, chunks)

    db = get_db()
    db[COLLECTION].bulk_write(
        [ReplaceOne({"url": d["url"]}, d, upsert=True) for d in docs], ordered=False
    )
    db[META_COLLECTION].update_one(
        {"_id": "last_updated"},
        {"$set": {"timestamp": datetime.now(timezone.utc)}},
        upsert=True,
    )
    print("Done.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--if-stale",
        action="store_true",
        help=f"Only refresh if the last update was more than {STALE_AFTER_DAYS} days ago.",
    )
    args = parser.parse_args()

    config = load_config()
    init_db(config.mongodb_uri, config.mongodb_db)

    try:
        refresh(force=not args.if_stale)
    except Exception as e:
        print(f"Error refreshing Commander Bracket announcements: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
