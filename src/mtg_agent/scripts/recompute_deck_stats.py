"""
Refresh every deck's per-card oracle data from the local scryfall_oracle
collection, then recompute the cached `stats` field — no Moxfield or live
Scryfall API calls needed, since scryfall_oracle is already kept fresh by
refresh_scryfall_bulk.py.

Why this exists: a deck's mainboard/commanders/maybeboard entries carry a
`.scryfall` snapshot taken at the deck's *last actual Moxfield sync*. If
ORACLE_FIELDS gains new fields (or a bug in a previously-missing field like
`layout` gets fixed) after that sync, the deck's stored snapshot silently
keeps the old/incomplete data — sync_deck() only re-fetches from Moxfield
when Moxfield's own copy changes, so a schema/field fix never reaches an
untouched deck otherwise. This showed up concretely: Glarb's stored
`layout` was null, so _classify_type() couldn't tell `transform` cards
(e.g. Primal Amulet // Primal Wellspring, front-face-only) apart from
`modal_dfc` cards (either face playable) and silently over-counted lands.

Also recomputes `stats` afterward (compute_deck_stats() can independently
drift out of sync the same way — see the earlier stats-only version of this
script). Run this any time ORACLE_FIELDS or compute_deck_stats() changes.

Run: python -m mtg_agent.scripts.recompute_deck_stats
"""

from mtg_agent.clients import moxfield
from mtg_agent.config import load_config
from mtg_agent.db.mongodb import get_db, get_oracle_card, init_db


def _refresh_oracle_data(entries: list[dict]) -> int:
    """Replace each entry's `.scryfall` sub-object with fresh local oracle data. Returns count changed."""
    changed = 0
    for entry in entries:
        fresh = get_oracle_card(entry["name"])
        if fresh and fresh != entry.get("scryfall"):
            entry["scryfall"] = fresh
            changed += 1
    return changed


def main() -> None:
    config = load_config()
    init_db(config.mongodb_uri, config.mongodb_db)
    db = get_db()

    decks = list(db["decks"].find(
        {}, {"slug": 1, "commanders": 1, "mainboard": 1, "maybeboard": 1, "stats": 1}
    ))
    print(f"Found {len(decks)} decks.", flush=True)

    for deck in decks:
        slug = deck["slug"]
        commanders = deck.get("commanders", [])
        mainboard = deck.get("mainboard", [])
        maybeboard = deck.get("maybeboard", [])
        old_stats = deck.get("stats", {})

        cards_changed = (
            _refresh_oracle_data(commanders)
            + _refresh_oracle_data(mainboard)
            + _refresh_oracle_data(maybeboard)
        )

        new_stats = moxfield.compute_deck_stats(mainboard)
        new_stats["price_usd_total"] = old_stats.get("price_usd_total", 0)
        stats_changed = new_stats != old_stats

        if not cards_changed and not stats_changed:
            print(f"  {slug}: unchanged", flush=True)
            continue

        db["decks"].update_one({"slug": slug}, {"$set": {
            "commanders": commanders,
            "mainboard": mainboard,
            "maybeboard": maybeboard,
            "stats": new_stats,
        }})
        print(f"  {slug}: {cards_changed} card(s) re-enriched; "
              f"land {old_stats.get('type_counts', {}).get('land')} -> {new_stats['type_counts'].get('land')}, "
              f"avg_lands_in_hand {old_stats.get('avg_lands_in_opening_hand')} -> "
              f"{new_stats['avg_lands_in_opening_hand']}", flush=True)

    print("Done.", flush=True)


if __name__ == "__main__":
    main()
