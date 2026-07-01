"""
Download the official Commander Brackets and Game Changers list from wizards.com
and upsert into MongoDB. Both live on the same page, embedded in a Contentful-backed
JS data blob (topic/copy pairs) rather than plain rendered HTML.

Populates:
  commander_brackets       — one doc per bracket (1-5) plus the overview, keyed by
                              bracket number ("overview", "1".."5"), with title + prose
  commander_game_changers  — one doc per Game Changer card, keyed by name, with its
                              color category (White/Blue/.../Colorless)

Run:               python -m mtg_agent.scripts.refresh_commander_brackets
Stale check only:  python -m mtg_agent.scripts.refresh_commander_brackets --if-stale
"""

import argparse
import codecs
import html as htmllib
import re
import sys
from datetime import datetime, timedelta, timezone

import httpx
from pymongo import ReplaceOne

from mtg_agent.config import load_config
from mtg_agent.db.mongodb import get_db, init_db

FORMAT_PAGE_URL = "https://magic.wizards.com/en/formats/commander"
STALE_AFTER_DAYS = 56  # ~8 weeks
META_COLLECTION = "commander_brackets_meta"
BRACKETS_COLLECTION = "commander_brackets"
GAME_CHANGERS_COLLECTION = "commander_game_changers"

_TOPIC_RE = re.compile(r'topic:"([^"]+)",copy:"((?:[^"\\]|\\.)*)"')
_AUTO_CARD_RE = re.compile(r"<auto-card>([^<]+)</auto-card>")

_BRACKET_TITLES = {
    "Bracket 1: Exhibition": "1",
    "Bracket 2: Core": "2",
    "Bracket 3: Upgraded": "3",
    "Bracket 4: Optimized": "4",
    "Bracket 5: cEDH": "5",
}


def _last_updated() -> datetime | None:
    meta = get_db()[META_COLLECTION].find_one({"_id": "last_updated"})
    return meta["timestamp"] if meta else None


def _is_stale() -> bool:
    last = _last_updated()
    if last is None:
        return True
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return last < now - timedelta(days=STALE_AFTER_DAYS)


def _decode(raw: str) -> str:
    return htmllib.unescape(codecs.decode(raw, "unicode_escape"))


def _parse_brackets(html: str) -> list[dict]:
    start = html.index('identifier:"brackets"')
    end = html.index('identifier:"gamechangers"')
    docs = []
    for topic, copy in _TOPIC_RE.findall(html[start:end]):
        text = _decode(copy)
        if topic == "Commander Brackets Overview":
            docs.append({"number": "overview", "title": topic, "text": text})
        elif topic in _BRACKET_TITLES:
            docs.append({"number": _BRACKET_TITLES[topic], "title": topic, "text": text})
    return docs


def _parse_game_changers(html: str) -> list[dict]:
    start = html.index('identifier:"gamechangers"')
    # Section ends at the next distinct identifier block.
    end = html.index('identifier:"', start + len('identifier:"gamechangers"'))
    docs = []
    for topic, copy in _TOPIC_RE.findall(html[start:end]):
        if topic == "What are Game Changers?":
            continue
        text = _decode(copy)
        for name in _AUTO_CARD_RE.findall(text):
            docs.append({"name": name, "color_category": topic})
    return docs


def refresh(force: bool = False) -> None:
    if not force and not _is_stale():
        print(f"Brackets/Game Changers are fresh (checked within the last {STALE_AFTER_DAYS} days) — nothing to do.", flush=True)
        return

    print(f"Downloading {FORMAT_PAGE_URL}...", flush=True)
    resp = httpx.get(FORMAT_PAGE_URL, timeout=15.0, follow_redirects=True)
    resp.raise_for_status()

    brackets = _parse_brackets(resp.text)
    print(f"  Parsed {len(brackets)} bracket entries.", flush=True)
    game_changers = _parse_game_changers(resp.text)
    print(f"  Parsed {len(game_changers)} Game Changer cards.", flush=True)

    db = get_db()
    if brackets:
        db[BRACKETS_COLLECTION].bulk_write(
            [ReplaceOne({"number": d["number"]}, d, upsert=True) for d in brackets], ordered=False
        )
    # Full delete+reinsert: the Game Changers list can shrink (unbans/removals), not just grow.
    db[GAME_CHANGERS_COLLECTION].delete_many({})
    if game_changers:
        db[GAME_CHANGERS_COLLECTION].bulk_write(
            [ReplaceOne({"name": d["name"]}, d, upsert=True) for d in game_changers], ordered=False
        )

    db[META_COLLECTION].update_one(
        {"_id": "last_updated"},
        {"$set": {"timestamp": datetime.now(timezone.utc), "source_url": FORMAT_PAGE_URL}},
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
        print(f"Error refreshing Commander Brackets/Game Changers: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
