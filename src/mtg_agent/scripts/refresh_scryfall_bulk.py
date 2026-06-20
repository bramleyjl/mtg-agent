"""
Download Scryfall bulk files and upsert into MongoDB.

Manages four datasets:
  oracle_cards  — one canonical entry per Oracle ID; primary card lookup collection
  default_cards — every English printing; used for price, border, set, and art queries
  rulings       — Oracle rulings per card (keyed by oracle_id)
  oracle_tags   — EDHREC/Scryfall tagger data (functional tags per card)

Run all:           python -m mtg_agent.scripts.refresh_scryfall_bulk
Specific dataset:  python -m mtg_agent.scripts.refresh_scryfall_bulk --datasets oracle_cards rulings
Stale check only:  python -m mtg_agent.scripts.refresh_scryfall_bulk --if-stale
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from pymongo import ReplaceOne

from mtg_agent.clients.scryfall import _trim_card, _trim_printing
from mtg_agent.config import load_config
from mtg_agent.db.mongodb import get_db, init_db

BULK_LIST_URL = "https://api.scryfall.com/bulk-data"
STALE_AFTER_DAYS = 7
BATCH_SIZE = 500
META_COLLECTION = "scryfall_bulk_meta"

_TOKEN_LAYOUTS = {"token", "emblem", "double_faced_token", "art_series"}

DATASETS: dict[str, dict[str, Any]] = {
    "oracle_cards": {
        "collection": "scryfall_oracle",
        "key": "oracle_id",
        "transform": _trim_card,
        "skip": lambda card: card.get("layout") in _TOKEN_LAYOUTS,
    },
    "default_cards": {
        "collection": "scryfall_bulk",
        "key": "id",
        "transform": _trim_printing,
    },
    "rulings": {
        "collection": "scryfall_rulings",
        "key": "oracle_id",
        "group_by": "oracle_id",
    },
    "oracle_tags": {
        "collection": "scryfall_oracle_tags",
        "key": "id",
        "transform": lambda entry: entry,
    },
}


def _last_updated(dataset: str) -> datetime | None:
    db = get_db()
    meta = db[META_COLLECTION].find_one({"_id": f"last_updated_{dataset}"})
    return meta["timestamp"] if meta else None


def _is_stale(dataset: str) -> bool:
    last = _last_updated(dataset)
    if last is None:
        return True
    return last < datetime.now(timezone.utc) - timedelta(days=STALE_AFTER_DAYS)



def _fetch_bulk_uris() -> dict[str, str]:
    """Return mapping of bulk data type → download_uri from Scryfall."""
    resp = httpx.get(BULK_LIST_URL, timeout=15.0)
    resp.raise_for_status()
    return {item["type"]: item["download_uri"] for item in resp.json()["data"]}


def _load_json_stream(uri: str) -> list:
    """Stream-download a bulk JSON file and parse it. Returns the full list."""
    print(f"  Downloading {uri.split('/')[-1].split('?')[0]}...", flush=True)
    with httpx.stream("GET", uri, timeout=300.0) as resp:
        resp.raise_for_status()
        raw = b"".join(resp.iter_bytes())
    return json.loads(raw)


def _upsert_batch(collection: str, key: str, batch: list[dict]) -> None:
    ops = [
        ReplaceOne({key: doc[key]}, doc, upsert=True)
        for doc in batch
        if doc.get(key) is not None
    ]
    if ops:
        get_db()[collection].bulk_write(ops, ordered=False)


def _refresh_cards(dataset: str, uri: str) -> None:
    cfg = DATASETS[dataset]
    collection, key = cfg["collection"], cfg["key"]
    skip = cfg.get("skip")

    cards = _load_json_stream(uri)
    print(f"  Upserting {len(cards)} cards...", flush=True)

    batch: list[dict] = []
    stored = 0
    for card in cards:
        if skip and skip(card):
            continue
        batch.append(cfg["transform"](card))
        stored += 1
        if len(batch) >= BATCH_SIZE:
            _upsert_batch(collection, key, batch)
            batch = []
    if batch:
        _upsert_batch(collection, key, batch)

    print(f"  Done — {stored} cards stored (skipped {len(cards) - stored}).", flush=True)


def refresh_rulings(uri: str) -> None:
    cfg = DATASETS["rulings"]
    collection, key = cfg["collection"], cfg["key"]

    rulings = _load_json_stream(uri)
    print(f"  Grouping {len(rulings)} rulings by oracle_id...", flush=True)

    grouped: dict[str, list] = {}
    for ruling in rulings:
        oid = ruling.get("oracle_id")
        if oid:
            grouped.setdefault(oid, []).append(
                {"published_at": ruling.get("published_at"), "comment": ruling.get("comment")}
            )

    print(f"  Upserting {len(grouped)} oracle_id groups...", flush=True)
    batch: list[dict] = []
    for oracle_id, entries in grouped.items():
        batch.append({"oracle_id": oracle_id, "rulings": entries})
        if len(batch) >= BATCH_SIZE:
            _upsert_batch(collection, key, batch)
            batch = []
    if batch:
        _upsert_batch(collection, key, batch)

    print(f"  Done — {len(grouped)} cards have rulings.", flush=True)


def refresh_oracle_tags(uri: str) -> None:
    cfg = DATASETS["oracle_tags"]
    collection, key = cfg["collection"], cfg["key"]

    tags = _load_json_stream(uri)
    print(f"  Upserting {len(tags)} oracle tag entries...", flush=True)

    batch: list[dict] = []
    for entry in tags:
        batch.append(cfg["transform"](entry))
        if len(batch) >= BATCH_SIZE:
            _upsert_batch(collection, key, batch)
            batch = []
    if batch:
        _upsert_batch(collection, key, batch)

    print(f"  Done — {len(tags)} entries stored.", flush=True)


REFRESH_FNS = {
    "oracle_cards": lambda uri: _refresh_cards("oracle_cards", uri),
    "default_cards": lambda uri: _refresh_cards("default_cards", uri),
    "rulings": refresh_rulings,
    "oracle_tags": refresh_oracle_tags,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--if-stale",
        action="store_true",
        help=f"Skip datasets that were refreshed within the last {STALE_AFTER_DAYS} days.",
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=list(DATASETS.keys()),
        default=list(DATASETS.keys()),
        help="Which datasets to refresh (default: all).",
    )
    args = parser.parse_args()

    config = load_config()
    init_db(config.mongodb_uri, config.mongodb_db)

    to_refresh = args.datasets
    if args.if_stale:
        to_refresh = [d for d in to_refresh if _is_stale(d)]
        if not to_refresh:
            print("All datasets are fresh — nothing to refresh.", flush=True)
            sys.exit(0)
        print(f"Stale datasets: {', '.join(to_refresh)}", flush=True)

    print("Fetching Scryfall bulk data index...", flush=True)
    try:
        uris = _fetch_bulk_uris()
    except Exception as e:
        print(f"Failed to fetch Scryfall bulk index: {e}", flush=True)
        sys.exit(1)

    for dataset in to_refresh:
        if dataset not in uris:
            print(f"  Warning: '{dataset}' not found in Scryfall bulk index — skipping.", flush=True)
            continue
        print(f"\n[{dataset}]", flush=True)
        try:
            REFRESH_FNS[dataset](uris[dataset])
            get_db()[META_COLLECTION].update_one(
                {"_id": f"last_updated_{dataset}"},
                {"$set": {"timestamp": datetime.now(timezone.utc)}},
                upsert=True,
            )
        except Exception as e:
            print(f"  Error refreshing {dataset}: {e}", flush=True)

    print("\nAll done.", flush=True)


if __name__ == "__main__":
    main()
