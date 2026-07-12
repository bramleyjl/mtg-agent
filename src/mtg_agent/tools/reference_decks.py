from collections import Counter

from mtg_agent.clients import moxfield
from mtg_agent.db import mongodb
from mtg_agent.tools.decks import enrich_deck_cards

VALID_DECK_TYPES = {"opponent_meta", "design_exemplar", "primer_reference"}

# Card-count threshold for a Scryfall Tagger label to count as a deck-defining
# strategy signal (vs. incidental — a handful of cards sharing a tag by chance).
_MIN_CARDS_FOR_SIGNAL = 5


def generate_strategy_tags(mainboard: list[dict]) -> list[str]:
    """
    Derive 3-5 deck-level strategy_tags from the Scryfall Tagger labels each mainboard
    card already carries (`entry["scryfall_tags"]`, populated by enrich_deck_cards() via
    mongodb.get_tags_for_oracle_ids() — gameplay-only, trivia/flavor tags pre-filtered).
    Rather than reimplementing oracle-text pattern matching, this reuses that curated
    community tagging data: count how many mainboard cards carry each label, keep labels
    that clear a deck-defining threshold, most-common first. Conservative by design —
    err on leaving a tag off rather than over-tagging.
    """
    counts: Counter[str] = Counter()
    for entry in mainboard:
        qty = entry.get("quantity", 1)
        for label in entry.get("scryfall_tags") or []:
            counts[label] += qty

    signal_tags = [label for label, count in counts.most_common() if count >= _MIN_CARDS_FOR_SIGNAL]
    return signal_tags[:5]


async def sync_reference_deck(
    deck_data: dict,
    source_url: str | None = None,
    deck_type: str | None = None,
    owner_username: str | None = None,
) -> dict:
    """
    Store a Moxfield deck that belongs to someone else — e.g. a decklist linked from a
    strategy article, or a recurring opponent's deck — in `reference_decklists`, entirely
    separate from `decks` (John's own). No Notion or decks.yaml involvement: this
    collection exists purely as CW reference material, keyed by moxfield_id rather than
    a hand-picked slug.

    deck_type: one of "opponent_meta" | "design_exemplar" | "primer_reference". Invalid
    values are ignored (left unset) rather than rejected, since a partial payload from
    the extension shouldn't block ingestion.
    """
    moxfield_id = deck_data.get("publicId")
    if not moxfield_id:
        return {"error": "Moxfield deck data missing publicId"}

    resolved_owner_username = owner_username or moxfield.extract_owner_username(deck_data)
    moxfield_updated_at = deck_data.get("lastUpdatedAtUtc")

    stored = mongodb.get_reference_decklist(moxfield_id)
    if stored and moxfield_updated_at and stored.get("moxfield_updated_at") == moxfield_updated_at:
        # Card data is unchanged, so skip the re-enrich, but a re-sync can still be
        # carrying new metadata (source_url, deck_type) from the extension form that
        # the caller wants applied — e.g. re-running sync just to attach a source_url
        # or correct the type. Apply those without touching cards/stats/tags.
        metadata_update: dict = {}
        if source_url and source_url != stored.get("source_url"):
            metadata_update["source_url"] = source_url
        if deck_type in VALID_DECK_TYPES and deck_type != stored.get("type"):
            metadata_update["type"] = deck_type
        if owner_username and owner_username != stored.get("owner_username"):
            metadata_update["owner_username"] = owner_username
        if metadata_update:
            mongodb.update_reference_decklist_metadata(moxfield_id, metadata_update)
            stored = {**stored, **metadata_update}

        return {
            "skipped": moxfield_id,
            "reason": "already up to date",
            "name": stored.get("name", moxfield_id),
            "owner_username": stored.get("owner_username"),
            "type": stored.get("type"),
            "source_url": stored.get("source_url"),
            "metadata_updated": bool(metadata_update),
        }

    enriched = await enrich_deck_cards(deck_data)
    proposed_tags = generate_strategy_tags(enriched["mainboard"])

    resolved_type = deck_type if deck_type in VALID_DECK_TYPES else (stored or {}).get("type")

    doc = {
        "moxfield_id": moxfield_id,
        "owner_username": resolved_owner_username,
        "name": enriched["mox_name"],
        "title": enriched["mox_title"],
        "moxfield_updated_at": moxfield_updated_at,
        "commanders": enriched["commander_entries"],
        "mainboard": enriched["mainboard"],
        "maybeboard": enriched["maybeboard"],
        "stats": enriched["stats"],
        "source_url": source_url or (stored or {}).get("source_url"),
        "type": resolved_type,
        "strategy_tags": (stored or {}).get("strategy_tags") or proposed_tags,
    }
    mongodb.upsert_reference_decklist(moxfield_id, doc)

    return {
        "synced": moxfield_id,
        "name": enriched["mox_name"],
        "title": enriched["mox_title"],
        "owner_username": resolved_owner_username,
        "type": resolved_type,
        "card_count": len(enriched["mainboard"]),
        "enriched": len(enriched["enriched_cards"]),
        "missing_from_scryfall": enriched["missing"],
        "source_url": doc["source_url"],
        "proposed_tags": proposed_tags,
    }
