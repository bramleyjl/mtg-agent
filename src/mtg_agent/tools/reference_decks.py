from mtg_agent.clients import moxfield
from mtg_agent.db import mongodb
from mtg_agent.tools.decks import enrich_deck_cards


async def sync_reference_deck(deck_data: dict, source_url: str | None = None) -> dict:
    """
    Store a Moxfield deck that belongs to someone else — e.g. a decklist linked from a
    strategy article — in `reference_decklists`, entirely separate from `decks` (John's
    own). No Notion or decks.yaml involvement: this collection exists purely as CW
    reference material, keyed by moxfield_id rather than a hand-picked slug.
    """
    moxfield_id = deck_data.get("publicId")
    if not moxfield_id:
        return {"error": "Moxfield deck data missing publicId"}

    owner_username = moxfield.extract_owner_username(deck_data)
    moxfield_updated_at = deck_data.get("lastUpdatedAtUtc")

    stored = mongodb.get_reference_decklist(moxfield_id)
    if stored and moxfield_updated_at and stored.get("moxfield_updated_at") == moxfield_updated_at:
        return {
            "skipped": moxfield_id,
            "reason": "already up to date",
            "name": stored.get("name", moxfield_id),
            "owner_username": stored.get("owner_username"),
        }

    enriched = await enrich_deck_cards(deck_data)

    doc = {
        "moxfield_id": moxfield_id,
        "owner_username": owner_username,
        "name": enriched["mox_name"],
        "title": enriched["mox_title"],
        "moxfield_updated_at": moxfield_updated_at,
        "commanders": enriched["commander_entries"],
        "mainboard": enriched["mainboard"],
        "maybeboard": enriched["maybeboard"],
        "stats": enriched["stats"],
        "source_url": source_url or (stored or {}).get("source_url"),
    }
    mongodb.upsert_reference_decklist(moxfield_id, doc)

    return {
        "synced": moxfield_id,
        "name": enriched["mox_name"],
        "title": enriched["mox_title"],
        "owner_username": owner_username,
        "card_count": len(enriched["mainboard"]),
        "enriched": len(enriched["enriched_cards"]),
        "missing_from_scryfall": enriched["missing"],
        "source_url": doc["source_url"],
    }
