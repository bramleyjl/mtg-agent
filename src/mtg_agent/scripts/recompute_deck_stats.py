"""
Recompute the cached `stats` field for every deck from its already-stored,
already-Scryfall-enriched mainboard — no Moxfield or Scryfall calls needed.

Why this exists: sync_deck() skips all recomputation (including stats) whenever
Moxfield's own copy of a deck hasn't changed since the last sync (a deliberate
optimization to avoid redundant API calls). That means fixes to
compute_deck_stats() (e.g. the quantity-counting / MDFC-land-classification
fixes) never take effect for a deck unless it happens to get edited on
Moxfield afterward. Run this any time compute_deck_stats() changes to refresh
every deck's cached stats immediately, independent of Moxfield activity.

Run: python -m mtg_agent.scripts.recompute_deck_stats
"""

from mtg_agent.clients import moxfield
from mtg_agent.config import load_config
from mtg_agent.db.mongodb import get_db, init_db


def main() -> None:
    config = load_config()
    init_db(config.mongodb_uri, config.mongodb_db)
    db = get_db()

    decks = list(db["decks"].find({}, {"slug": 1, "mainboard": 1, "stats": 1}))
    print(f"Found {len(decks)} decks.", flush=True)

    for deck in decks:
        slug = deck["slug"]
        mainboard = deck.get("mainboard", [])
        old_stats = deck.get("stats", {})
        new_stats = moxfield.compute_deck_stats(mainboard)
        new_stats["price_usd_total"] = old_stats.get("price_usd_total", 0)

        if new_stats == old_stats:
            print(f"  {slug}: unchanged", flush=True)
            continue

        db["decks"].update_one({"slug": slug}, {"$set": {"stats": new_stats}})
        print(f"  {slug}: updated (land {old_stats.get('type_counts', {}).get('land')} -> "
              f"{new_stats['type_counts'].get('land')}, "
              f"avg_lands_in_hand {old_stats.get('avg_lands_in_opening_hand')} -> "
              f"{new_stats['avg_lands_in_opening_hand']})", flush=True)

    print("Done.", flush=True)


if __name__ == "__main__":
    main()
