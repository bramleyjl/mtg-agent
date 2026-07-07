"""
Download the Commander Spellbook combo bulk file and upsert into MongoDB.

Commander Spellbook publishes every combo "variant" (a specific card-for-card
combo instance) as a single bulk JSON file, S3/CloudFront-hosted like a
Scryfall bulk file. We filter to commander-legal variants and store them in
`commander_combos`, one document per variant.

Some combo pieces are "variable" rather than a specific card — e.g. any cheap
artifact creature, or any "deals damage on cast" effect (an "Impact Tremors"
type). Commander Spellbook represents these as generic `requires` template
slots (template_id/template_name) rather than concrete cards. Each template
maps to a Scryfall search query (via its own `/templates/` endpoint), so we
resolve every template to the concrete set of commander-legal oracle_ids that
satisfy it and store that in `commander_spellbook_templates`. This makes a
combo checkable against a real decklist end-to-end: "uses" pieces are exact
oracle_id matches, "requires" pieces are satisfied if the deck owns any card
in the matching template's resolved oracle_ids.

Two independent staleness clocks:
  - combos:    checked against the *remote* bulk file's Last-Modified header,
               since new combos only appear alongside new card releases.
  - templates: checked on a fixed local window (cards satisfying a template
               change slowly). A template already resolved in a prior run is
               only re-queried for cards released since its last resolve (plus
               a small overlap buffer) and unioned into its stored oracle_ids
               — not re-fetched from scratch — so weekly runs stay cheap even
               though the initial resolve of all 167 templates is not. Only a
               brand-new template, or one whose scryfallQuery text changed
               upstream, gets a full resolve.

Run:                    python -m mtg_agent.scripts.refresh_commander_spellbook
Combos only, if-stale:  python -m mtg_agent.scripts.refresh_commander_spellbook --if-stale
Skip template resolve:  python -m mtg_agent.scripts.refresh_commander_spellbook --skip-templates
"""

import argparse
import bisect
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
import json
from pymongo import ReplaceOne

from mtg_agent.config import load_config
from mtg_agent.db.mongodb import get_db, init_db

BULK_URL = "https://json.commanderspellbook.com/variants.json"
TEMPLATES_URL = "https://backend.commanderspellbook.com/templates/"
SCRYFALL_SEARCH_URL = "https://api.scryfall.com/cards/search"
SCRYFALL_REQUEST_DELAY = 0.2
# Re-check this many days of overlap on an incremental resolve, to absorb any
# indexing lag around Scryfall's bulk data rather than risk missing a card.
INCREMENTAL_OVERLAP_DAYS = 3

META_COLLECTION = "commander_combos_meta"
COLLECTION = "commander_combos"
TEMPLATES_COLLECTION = "commander_spellbook_templates"
TEMPLATES_STALE_DAYS = 7
BATCH_SIZE = 500


def _remote_last_modified() -> str | None:
    resp = httpx.head(BULK_URL, timeout=15.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.headers.get("last-modified") or resp.headers.get("etag")


def _stored_last_modified() -> str | None:
    meta = get_db()[META_COLLECTION].find_one({"_id": "last_modified"})
    return meta["value"] if meta else None


def _is_stale(remote: str | None) -> bool:
    if remote is None:
        return True
    return remote != _stored_last_modified()


def _popularity_percentile(popularity: int | None, pop_values: list[int]) -> float | None:
    """Percentile rank of a combo's popularity against every measured combo in this refresh."""
    if popularity is None or not pop_values:
        return None
    rank = bisect.bisect_right(pop_values, popularity)
    return round(100 * rank / len(pop_values), 1)


def _to_doc(variant: dict, pop_values: list[int]) -> dict:
    popularity = variant.get("popularity")
    return {
        "variant_id": variant["id"],
        "combo_group_id": [c["id"] for c in variant.get("of", [])],
        "identity": variant.get("identity"),
        "uses": [
            {
                "oracle_id": u["card"].get("oracleId"),
                "name": u["card"].get("name"),
                "quantity": u.get("quantity"),
                "zone_locations": u.get("zoneLocations"),
                "must_be_commander": u.get("mustBeCommander", False),
            }
            for u in variant.get("uses", [])
        ],
        "requires": [
            {
                "template_id": r["template"]["id"],
                "template_name": r["template"].get("name"),
                "quantity": r.get("quantity"),
            }
            for r in variant.get("requires", [])
        ],
        "produces": [
            {"feature_id": p["feature"]["id"], "feature_name": p["feature"].get("name"), "quantity": p.get("quantity")}
            for p in variant.get("produces", [])
        ],
        "description": variant.get("description"),
        "legalities": variant.get("legalities"),
        "popularity": popularity,
        "popularity_percentile": _popularity_percentile(popularity, pop_values),
        "last_synced": datetime.now(timezone.utc),
    }


def refresh(force: bool = False) -> None:
    remote = _remote_last_modified()
    if not force and not _is_stale(remote):
        print("Commander Spellbook bulk file is unchanged — nothing to do.", flush=True)
        return

    print(f"Downloading {BULK_URL}...", flush=True)
    with httpx.stream("GET", BULK_URL, timeout=300.0, follow_redirects=True) as resp:
        resp.raise_for_status()
        raw = b"".join(resp.iter_bytes())
    payload = json.loads(raw)
    variants = payload["variants"]
    print(f"  Parsed {len(variants)} total variants (bulk timestamp: {payload.get('timestamp')}).", flush=True)

    commander_legal = [v for v in variants if v.get("legalities", {}).get("commander")]
    print(f"  {len(commander_legal)} are commander-legal — upserting...", flush=True)

    pop_values = sorted(
        v["popularity"] for v in commander_legal if v.get("popularity") is not None
    )

    db = get_db()
    batch: list[dict] = []
    for variant in commander_legal:
        batch.append(_to_doc(variant, pop_values))
        if len(batch) >= BATCH_SIZE:
            db[COLLECTION].bulk_write(
                [ReplaceOne({"variant_id": d["variant_id"]}, d, upsert=True) for d in batch], ordered=False
            )
            batch = []
    if batch:
        db[COLLECTION].bulk_write(
            [ReplaceOne({"variant_id": d["variant_id"]}, d, upsert=True) for d in batch], ordered=False
        )

    db[META_COLLECTION].update_one(
        {"_id": "last_modified"},
        {"$set": {"value": remote, "checked_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    print("Done.", flush=True)


def _fetch_all_templates() -> list[dict]:
    """Paginate Commander Spellbook's /templates/ endpoint."""
    templates: list[dict] = []
    url: str | None = f"{TEMPLATES_URL}?limit=100"
    while url:
        resp = httpx.get(url, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
        templates.extend(data["results"])
        url = data.get("next")
    return templates


def _resolve_template_oracle_ids(scryfall_api_url: str) -> list[str]:
    """Paginate a template's Scryfall search (already scoped to legal:commander) and collect oracle_ids."""
    oracle_ids: list[str] = []
    url: str | None = scryfall_api_url
    while url:
        time.sleep(SCRYFALL_REQUEST_DELAY)
        resp = httpx.get(url, timeout=15.0)
        if resp.status_code == 404:
            break  # query matched zero cards
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("retry-after", 2))
            time.sleep(retry_after)
            continue  # retry the same page
        resp.raise_for_status()
        data = resp.json()
        oracle_ids.extend(c["oracle_id"] for c in data.get("data", []) if c.get("oracle_id"))
        url = data.get("next_page") if data.get("has_more") else None
    return oracle_ids


def _incremental_query_url(scryfall_query: str, since: datetime) -> str:
    """
    Build a Scryfall search restricted to cards released since a template's last
    resolve (with a small overlap buffer), so a re-run only fetches new prints
    instead of re-querying the template's entire matching card pool.
    """
    cutoff = (since - timedelta(days=INCREMENTAL_OVERLAP_DAYS)).strftime("%Y-%m-%d")
    q = f"({scryfall_query}) legal:commander date>={cutoff}"
    return f"{SCRYFALL_SEARCH_URL}?q={quote(q)}"


def _templates_are_stale() -> bool:
    meta = get_db()["commander_spellbook_templates_meta"].find_one({"_id": "last_synced"})
    if meta is None:
        return True
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return meta["timestamp"] < now - timedelta(days=TEMPLATES_STALE_DAYS)


def refresh_templates(force: bool = False) -> None:
    if not force and not _templates_are_stale():
        print("Commander Spellbook templates are fresh — nothing to do.", flush=True)
        return

    templates = _fetch_all_templates()
    print(f"  Resolving {len(templates)} templates against Scryfall (rate-limited)...", flush=True)

    db = get_db()
    recent_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
    resumed_recently = {
        d["template_id"]
        for d in db[TEMPLATES_COLLECTION].find({"last_synced": {"$gte": recent_cutoff}}, {"template_id": 1})
    }
    if resumed_recently:
        print(f"  Skipping {len(resumed_recently)} templates resolved within the last 2 hours (resuming a prior run).", flush=True)

    # Existing docs let us resolve incrementally: a template whose query text
    # hasn't changed only needs cards released since its last resolve, unioned
    # into what's already stored — not a full re-query of its entire card pool.
    existing_by_id = {d["template_id"]: d for d in db[TEMPLATES_COLLECTION].find()}

    ops = []
    incremental_count = 0
    full_count = 0
    for i, tmpl in enumerate(templates, 1):
        if tmpl["id"] in resumed_recently:
            continue

        existing = existing_by_id.get(tmpl["id"])
        if existing and existing.get("scryfall_query") == tmpl.get("scryfallQuery") and existing.get("oracle_ids") is not None:
            new_ids = _resolve_template_oracle_ids(_incremental_query_url(tmpl["scryfallQuery"], existing["last_synced"]))
            oracle_ids = sorted(set(existing["oracle_ids"]) | set(new_ids))
            incremental_count += 1
        else:
            # New template, or its query definition changed upstream — needs a full resolve.
            oracle_ids = _resolve_template_oracle_ids(tmpl["scryfallApi"])
            full_count += 1

        ops.append(ReplaceOne(
            {"template_id": tmpl["id"]},
            {
                "template_id": tmpl["id"],
                "name": tmpl.get("name"),
                "scryfall_query": tmpl.get("scryfallQuery"),
                "oracle_ids": oracle_ids,
                "card_count": len(oracle_ids),
                "last_synced": datetime.now(timezone.utc),
            },
            upsert=True,
        ))
        # Flush incrementally — a transient failure partway through (e.g. a
        # rate limit) shouldn't lose already-resolved templates.
        if len(ops) >= 25:
            db[TEMPLATES_COLLECTION].bulk_write(ops, ordered=False)
            print(f"    {i}/{len(templates)} templates resolved...", flush=True)
            ops = []

    if ops:
        db[TEMPLATES_COLLECTION].bulk_write(ops, ordered=False)

    print(f"  ({incremental_count} incremental, {full_count} full resolves)", flush=True)

    db["commander_spellbook_templates_meta"].update_one(
        {"_id": "last_synced"},
        {"$set": {"timestamp": datetime.now(timezone.utc)}},
        upsert=True,
    )
    print(f"  Done — {len(templates)} templates resolved.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--if-stale",
        action="store_true",
        help="Only refresh combos if the remote bulk file has changed since the last sync.",
    )
    parser.add_argument(
        "--skip-templates",
        action="store_true",
        help="Skip template resolution (combos only).",
    )
    args = parser.parse_args()

    config = load_config()
    init_db(config.mongodb_uri, config.mongodb_db)

    try:
        refresh(force=not args.if_stale)
        if not args.skip_templates:
            refresh_templates(force=not args.if_stale)
    except Exception as e:
        print(f"Error refreshing Commander Spellbook data: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
