"""
Download the official Commander banned list from wizards.com and upsert into MongoDB.

Populates `commander_banned_list` with two kinds of entries:
  type "card"     — an individually named banned card (e.g. "Black Lotus")
  type "category" — a blanket ban category (e.g. "25 cards with the Conspiracy card type")

Scryfall's own `legalities.commander` field already reflects these bans at the
card level — this collection exists so the authoritative banned-list text itself
(including the blanket categories, which aren't individual card names) is
available for reference, independent of Scryfall's legality data.

Run:               python -m mtg_agent.scripts.refresh_commander_banlist
Stale check only:  python -m mtg_agent.scripts.refresh_commander_banlist --if-stale
"""

import argparse
import html as htmllib
import re
import sys
from datetime import datetime, timedelta, timezone

import httpx
from pymongo import ReplaceOne

from mtg_agent.config import load_config
from mtg_agent.db.mongodb import get_db, init_db

BANLIST_URL = "https://magic.wizards.com/en/banned-restricted-list"
STALE_AFTER_DAYS = 56  # ~8 weeks
META_COLLECTION = "commander_banned_meta"
COLLECTION = "commander_banned_list"

_LI_RE = re.compile(r"<li>(.*?)</li>", re.DOTALL)


def _last_updated() -> datetime | None:
    meta = get_db()[META_COLLECTION].find_one({"_id": "last_updated"})
    return meta["timestamp"] if meta else None


def _is_stale() -> bool:
    last = _last_updated()
    if last is None:
        return True
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return last < now - timedelta(days=STALE_AFTER_DAYS)


def _clean_text(raw: str) -> str:
    return htmllib.unescape(re.sub(r"<[^>]+>", "", raw)).strip()


def _parse_banlist(html: str) -> list[dict]:
    start = html.index('id="commander-banned"')
    list_links_start = html.index("list-links", start)
    section_end = html.index("</ul>", list_links_start) + len("</ul>")
    section = html[start:section_end]

    categories_start = section.index("<ul>")
    categories_end = section.index("</ul>", categories_start) + len("</ul>")
    categories_html = section[categories_start:categories_end]
    cards_html = section[categories_end:section_end]

    docs = [
        {"name": _clean_text(item), "type": "category"}
        for item in _LI_RE.findall(categories_html)
    ]
    docs += [
        {"name": _clean_text(item), "type": "card"}
        for item in _LI_RE.findall(cards_html)
    ]
    return docs


def refresh(force: bool = False) -> None:
    if not force and not _is_stale():
        print(f"Banned list is fresh (checked within the last {STALE_AFTER_DAYS} days) — nothing to do.", flush=True)
        return

    print(f"Downloading {BANLIST_URL}...", flush=True)
    resp = httpx.get(BANLIST_URL, timeout=15.0, follow_redirects=True)
    resp.raise_for_status()

    docs = _parse_banlist(resp.text)
    print(f"  Parsed {len(docs)} entries ({sum(d['type'] == 'card' for d in docs)} named cards, "
          f"{sum(d['type'] == 'category' for d in docs)} categories).", flush=True)

    db = get_db()
    db[COLLECTION].delete_many({})
    if docs:
        db[COLLECTION].bulk_write(
            [ReplaceOne({"name": d["name"]}, d, upsert=True) for d in docs], ordered=False
        )

    db[META_COLLECTION].update_one(
        {"_id": "last_updated"},
        {"$set": {"timestamp": datetime.now(timezone.utc), "source_url": BANLIST_URL}},
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
        print(f"Error refreshing Commander banned list: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
