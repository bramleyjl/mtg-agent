from collections import Counter

from mtg_agent.clients import moxfield
from mtg_agent.config import Config
from mtg_agent.db import mongodb
from mtg_agent.tools.decks import _slim_card, enrich_deck_cards

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


def _slim_reference_deck(stored: dict) -> dict:
    """Return top-level reference-deck properties and card names/oracle_ids only."""
    result: dict = {
        "moxfield_id": stored.get("moxfield_id"),
        "name": stored.get("name"),
        "title": stored.get("title"),
        "owner_username": stored.get("owner_username"),
        "type": stored.get("type"),
        "strategy_tags": stored.get("strategy_tags"),
        "source_url": stored.get("source_url"),
        "last_synced": stored.get("last_synced"),
        "commanders": [_slim_card(c) for c in stored.get("commanders", [])],
        "mainboard": [_slim_card(c) for c in stored.get("mainboard", [])],
    }
    if stored.get("stats"):
        result["stats"] = stored["stats"]
    if stored.get("maybeboard"):
        result["maybeboard"] = [_slim_card(c) for c in stored["maybeboard"]]
    return result


def list_reference_decklists(deck_type: str | None = None, commander_name: str | None = None) -> list[dict]:
    """
    List reference decklists (other people's decks, e.g. linked from strategy
    articles or recurring opponents' lists) — top-level properties and card
    names/oracle_ids only. Filter by deck_type ("opponent_meta" |
    "design_exemplar" | "primer_reference") and/or commander_name; omit both
    to list everything. Use get_reference_decklist() for one deck's full
    Scryfall-enriched card data.
    """
    if commander_name:
        stored = mongodb.get_reference_decklists_by_commander(
            commander_name, deck_type=deck_type or "design_exemplar"
        )
    elif deck_type:
        stored = mongodb.get_reference_decklists_by_type(deck_type)
    else:
        stored = mongodb.get_all_reference_decklists()
    return [_slim_reference_deck(d) for d in stored]


def get_reference_decklist(moxfield_id: str) -> dict | None:
    """
    Retrieve one reference decklist's full Scryfall-enriched card data (including
    each card's scryfall_tags) plus its type/strategy_tags/source_url metadata.
    """
    return mongodb.get_reference_decklist(moxfield_id)


def tune_reference_deck_tags(moxfield_id: str, tags: list[str]) -> dict:
    """
    Overwrite a reference deck's strategy_tags with an explicitly reviewed list —
    the Phase 3 tag-refinement step: generate_strategy_tags() proposes candidates
    at sync time (see sync_reference_deck()'s proposed_tags), but the stored
    strategy_tags only change when this is called with John's approved/edited
    list. Not called automatically; discuss the current tags with John first
    (get_reference_decklist() returns them) rather than auto-applying proposals.
    """
    stored = mongodb.get_reference_decklist(moxfield_id)
    if not stored:
        return {"error": f"No reference decklist found for moxfield_id '{moxfield_id}'"}

    mongodb.update_reference_decklist_tags(moxfield_id, tags)
    return {
        "moxfield_id": moxfield_id,
        "name": stored.get("name"),
        "previous_tags": stored.get("strategy_tags"),
        "strategy_tags": tags,
    }


def _card_map(*card_lists: list[dict]) -> dict[str, str]:
    """oracle_id -> name, across any number of card-entry lists."""
    result: dict[str, str] = {}
    for cards in card_lists:
        for entry in cards:
            oracle_id = entry.get("scryfall", {}).get("oracle_id")
            if oracle_id:
                result[oracle_id] = entry["name"]
    return result


def _oracle_ids(*card_lists: list[dict]) -> set[str]:
    ids: set[str] = set()
    for cards in card_lists:
        ids |= {e["scryfall"]["oracle_id"] for e in cards if e.get("scryfall", {}).get("oracle_id")}
    return ids


def _color_identity(deck: dict) -> list[str]:
    colors: set[str] = set()
    for commander in deck.get("commanders", []):
        colors |= set(commander.get("scryfall", {}).get("color_identity") or [])
    return sorted(colors)


def _tag_profile(mainboard: list[dict], top_n: int = 10) -> list[dict]:
    """Top gameplay tags by card count — a rough 'what this deck leans on' signal."""
    counts: Counter[str] = Counter()
    for entry in mainboard:
        qty = entry.get("quantity", 1)
        for label in entry.get("scryfall_tags") or []:
            counts[label] += qty
    return [{"tag": tag, "card_count": count} for tag, count in counts.most_common(top_n)]


async def compare_deck_to_reference(my_slug: str, ref_moxfield_id: str, config: Config) -> dict:
    """
    Power-level/effect-density comparison between one of John's own decks and a
    single reference decklist (typically type "opponent_meta" — a recurring
    opponent's build). Card overlap (shared / mine-only / reference-only),
    stats deltas (avg CMC, price, curve), color identity, and a rough tag-profile
    diff (top Scryfall Tagger labels by card count on each side).
    """
    deck_conf = config.decks_by_slug.get(my_slug)
    if not deck_conf:
        return {"error": f"Unknown deck slug: '{my_slug}'"}

    my_deck = mongodb.get_deck(my_slug)
    if not my_deck:
        return {"error": f"Deck '{my_slug}' not yet synced. Run sync_deck('{my_slug}') first."}

    ref_deck = mongodb.get_reference_decklist(ref_moxfield_id)
    if not ref_deck:
        return {"error": f"No reference decklist found for moxfield_id '{ref_moxfield_id}'"}

    my_cards = my_deck.get("commanders", []) + my_deck.get("mainboard", [])
    ref_cards = ref_deck.get("commanders", []) + ref_deck.get("mainboard", [])
    my_ids = _oracle_ids(my_cards)
    ref_ids = _oracle_ids(ref_cards)
    names = _card_map(my_cards, ref_cards)

    my_commander_names = [c["name"] for c in my_deck.get("commanders", [])]
    ref_commander_names = [c["name"] for c in ref_deck.get("commanders", [])]

    my_stats = my_deck.get("stats", {})
    ref_stats = ref_deck.get("stats", {})
    stats_fields = ("avg_cmc", "avg_cmc_with_lands", "median_cmc", "price_usd_total")

    return {
        "my_slug": my_slug,
        "ref_moxfield_id": ref_moxfield_id,
        "ref_name": ref_deck.get("name"),
        "ref_type": ref_deck.get("type"),
        "my_commanders": my_commander_names,
        "ref_commanders": ref_commander_names,
        "same_commander": bool(set(my_commander_names) & set(ref_commander_names)),
        "color_identity": {"mine": _color_identity(my_deck), "reference": _color_identity(ref_deck)},
        "stats_comparison": {
            field: {"mine": my_stats.get(field), "reference": ref_stats.get(field)} for field in stats_fields
        },
        "cards_shared": sorted(names[oid] for oid in (my_ids & ref_ids)),
        "cards_only_in_mine": sorted(names[oid] for oid in (my_ids - ref_ids)),
        "cards_only_in_reference": sorted(names[oid] for oid in (ref_ids - my_ids)),
        "tag_profile": {
            "mine": _tag_profile(my_deck.get("mainboard", [])),
            "reference": _tag_profile(ref_deck.get("mainboard", [])),
        },
    }


async def compare_deck_to_reference_group(
    my_slug: str, commander_name: str, config: Config, deck_type: str = "design_exemplar"
) -> dict:
    """
    Card-inclusion-pattern analysis against multiple reference decklists sharing
    a commander (default type "design_exemplar" — other builds of a commander
    John also plays). Same shape as compare_deck_to_edhrec(): which of the
    exemplar group's popular cards does the deck already run, and which is it
    missing (capped at the top 25 by inclusion rate).
    """
    deck_conf = config.decks_by_slug.get(my_slug)
    if not deck_conf:
        return {"error": f"Unknown deck slug: '{my_slug}'"}

    my_deck = mongodb.get_deck(my_slug)
    if not my_deck:
        return {"error": f"Deck '{my_slug}' not yet synced. Run sync_deck('{my_slug}') first."}

    exemplars = mongodb.get_reference_decklists_by_commander(commander_name, deck_type=deck_type)
    if not exemplars:
        return {
            "error": f"No reference decklists found for commander '{commander_name}' type '{deck_type}'. "
            f"Sync one via the browser extension first."
        }

    inclusion_counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    for exemplar in exemplars:
        for entry in exemplar.get("mainboard", []):
            oracle_id = entry.get("scryfall", {}).get("oracle_id")
            if oracle_id:
                inclusion_counts[oracle_id] += 1
                names[oracle_id] = entry["name"]

    my_ids = _oracle_ids(my_deck.get("mainboard", []))
    total = len(exemplars)

    ranked = sorted(inclusion_counts.items(), key=lambda kv: -kv[1])
    in_deck = [(oid, count) for oid, count in ranked if oid in my_ids]
    missing = [(oid, count) for oid, count in ranked if oid not in my_ids]

    def _fmt(oid: str, count: int) -> dict:
        return {"name": names[oid], "num_decks": count, "inclusion_pct": round(100 * count / total, 1)}

    return {
        "slug": my_slug,
        "commander": commander_name,
        "type": deck_type,
        "total_reference_decks": total,
        "cards_in_deck": [_fmt(oid, count) for oid, count in in_deck],
        "popular_cards_missing": [_fmt(oid, count) for oid, count in missing[:25]],
    }
