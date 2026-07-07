"""
Ingest EDHREC per-commander card usage/synergy data for John's own commanders.

Only commanders actually in play (re-derived from the `decks` collection each
run, not hardcoded) are fetched — unlike Commander Spellbook's bulk file, this
is a per-commander API call with no fixed-cost argument for going broader.

Four scopes are always refreshed per commander: `default`, `bracket_2`,
`bracket_3`, `bracket_4` (B1/B5 skipped — not brackets John plays). Any
`tag:<slug>` scope already present for a commander (created on-demand via
get_edhrec_tag_data()) is refreshed too, so a tag "graduates" into the
recurring refresh automatically the first time it's asked about — no separate
tracked-tags list to maintain.

Two collections populated, both scoped by `scope` (see docs/data_sources_roadmap.md
for full schema/rationale):
  - card_usage_stats:     one row per (commander, card, scope)
  - edhrec_commander_meta: one row per (commander, scope) — total_decks/bracket_counts/tag_counts

Cadence: weekly staleness gate (community data, not card-release-driven),
checked per-commander against edhrec_commander_meta's own last_synced.

Run:               python -m mtg_agent.scripts.refresh_edhrec
Stale check only:  python -m mtg_agent.scripts.refresh_edhrec --if-stale
"""

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone

from pymongo import ReplaceOne

from mtg_agent.clients import edhrec
from mtg_agent.config import load_config
from mtg_agent.db.mongodb import get_db, init_db

STALE_DAYS = 7


def _bracket_scopes() -> list[tuple[str, str | None]]:
    return [("default", None)] + [
        (f"bracket_{n}", slug) for n, slug in edhrec.BRACKET_SLUGS.items()
    ]


def _existing_tag_scopes(db, commander_oracle_id: str) -> list[tuple[str, str | None]]:
    scopes = db["edhrec_commander_meta"].distinct(
        "scope", {"commander_oracle_id": commander_oracle_id, "scope": {"$regex": "^tag:"}}
    )
    return [(scope, scope.split(":", 1)[1]) for scope in scopes]


def _resolve_dfc_front_faces(db, missing_names: set[str]) -> dict[str, str]:
    """
    EDHREC lists double-faced/split cards by front-face name only, but
    scryfall_oracle stores the combined "Front // Back" name — resolve any
    exact-match miss by prefix-matching "^Front\\s*//" (confirmed this accounts
    for nearly all unresolved cards, e.g. "Birgi, God of Storytelling" ->
    "Birgi, God of Storytelling // Harnfel, Horn of Bounty").
    """
    resolved = {}
    for name in missing_names:
        doc = db["scryfall_oracle"].find_one(
            {"name": re.compile(f"^{re.escape(name)}\\s*//")}, {"name": 1, "oracle_id": 1, "_id": 0}
        )
        if doc:
            resolved[name] = doc["oracle_id"]
    return resolved


def _commander_is_stale(db, commander_oracle_id: str) -> bool:
    meta = db["edhrec_commander_meta"].find_one(
        {"commander_oracle_id": commander_oracle_id, "scope": "default"}, {"last_synced": 1}
    )
    if not meta:
        return True
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return meta["last_synced"] < now - timedelta(days=STALE_DAYS)


def list_commanders(db) -> list[dict]:
    """Dedupe by oracle_id across all decks' commanders lists."""
    by_id: dict[str, dict] = {}
    for deck in db["decks"].find({}, {"commanders": 1, "_id": 0}):
        for c in deck.get("commanders", []):
            oid = c.get("scryfall", {}).get("oracle_id")
            if oid and oid not in by_id:
                by_id[oid] = {"oracle_id": oid, "name": c["name"]}
    return list(by_id.values())


def sync_scope(db, commander: dict, scope: str, sub_page: str | None) -> tuple[int, int]:
    """Returns (cards_upserted, cards_unresolved)."""
    page = edhrec.fetch_commander_page(edhrec.commander_slug(commander["name"]), sub_page=sub_page)
    if page is None:
        print(f"    {commander['name']} [{scope}]: no EDHREC page (404) — skipping.", flush=True)
        return 0, 0

    now = datetime.now(timezone.utc)
    rows = edhrec.parse_card_lists(page)

    names = {r["name"] for r in rows}
    oracle_by_name = {
        doc["name"]: doc["oracle_id"]
        for doc in db["scryfall_oracle"].find({"name": {"$in": list(names)}}, {"name": 1, "oracle_id": 1, "_id": 0})
    }
    still_missing = names - oracle_by_name.keys()
    if still_missing:
        oracle_by_name.update(_resolve_dfc_front_faces(db, still_missing))

    ops = []
    unresolved = 0
    for row in rows:
        oracle_id = oracle_by_name.get(row["name"])
        if not oracle_id:
            unresolved += 1
            continue
        num_decks, potential_decks = row.get("num_decks"), row.get("potential_decks")
        inclusion_pct = round(100 * num_decks / potential_decks, 2) if num_decks and potential_decks else None
        doc = {
            "commander_oracle_id": commander["oracle_id"],
            "commander_name": commander["name"],
            "oracle_id": oracle_id,
            "card_name": row["name"],
            "scope": scope,
            "category": row["category"],
            "synergy": row.get("synergy"),
            "num_decks": num_decks,
            "potential_decks": potential_decks,
            "inclusion_pct": inclusion_pct,
            "last_synced": now,
        }
        ops.append(ReplaceOne(
            {"commander_oracle_id": commander["oracle_id"], "oracle_id": oracle_id, "scope": scope},
            doc,
            upsert=True,
        ))
    if ops:
        db["card_usage_stats"].bulk_write(ops, ordered=False)

    meta = edhrec.parse_meta(page)
    meta_doc = {
        "commander_oracle_id": commander["oracle_id"],
        "commander_name": commander["name"],
        "scope": scope,
        "total_decks": meta["total_decks"],
        "tag_counts": meta["tag_counts"],
        "last_synced": now,
    }
    # bracket_counts is tautological on bracket_2/3/4 scopes (100% of that
    # population is definitionally that bracket) — only stored on default/tag:*.
    if scope == "default" or scope.startswith("tag:"):
        meta_doc["bracket_counts"] = meta["bracket_counts"]
    db["edhrec_commander_meta"].update_one(
        {"commander_oracle_id": commander["oracle_id"], "scope": scope},
        {"$set": meta_doc},
        upsert=True,
    )

    return len(ops), unresolved


def sync_commander(db, commander: dict) -> None:
    scopes = _bracket_scopes() + _existing_tag_scopes(db, commander["oracle_id"])
    for scope, sub_page in scopes:
        upserted, unresolved = sync_scope(db, commander, scope, sub_page)
        note = f" ({unresolved} card(s) unresolved against scryfall_oracle)" if unresolved else ""
        print(f"    {commander['name']} [{scope}]: {upserted} cards synced{note}", flush=True)


def refresh(force: bool = False) -> None:
    db = get_db()
    commanders = list_commanders(db)
    print(f"Checking EDHREC data for {len(commanders)} commander(s)...", flush=True)

    for commander in commanders:
        if not force and not _commander_is_stale(db, commander["oracle_id"]):
            continue
        print(f"  Syncing {commander['name']}...", flush=True)
        sync_commander(db, commander)

    print("Done.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--if-stale",
        action="store_true",
        help="Only refresh commanders whose EDHREC data is more than 7 days old.",
    )
    args = parser.parse_args()

    config = load_config()
    init_db(config.mongodb_uri, config.mongodb_db)

    try:
        refresh(force=not args.if_stale)
    except Exception as e:
        print(f"Error refreshing EDHREC data: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
