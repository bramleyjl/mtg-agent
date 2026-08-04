import re
from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient, ASCENDING, TEXT
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import OperationFailure


_client: MongoClient | None = None
_db: Database | None = None


def init_db(uri: str, db_name: str) -> None:
    global _client, _db
    _client = MongoClient(uri)
    _db = _client[db_name]
    _ensure_indexes()


def get_db() -> Database:
    if _db is None:
        raise RuntimeError("Database not initialized — call init_db() first")
    return _db


def decks() -> Collection:
    return get_db()["decks"]


def _create_index(coll: Collection, keys: list, **kwargs) -> None:
    """Create an index, ignoring conflicts when the field is already indexed under a different name."""
    try:
        coll.create_index(keys, **kwargs)
    except OperationFailure as e:
        if e.code != 85:  # 85 = IndexOptionsConflict (already exists, different name)
            raise


def _ensure_indexes() -> None:
    db = get_db()
    _create_index(db["decks"], [("slug", ASCENDING)], unique=True)
    _create_index(db["decks"], [("moxfield_id", ASCENDING)])
    _create_index(db["decks"], [("notion_id", ASCENDING)])
    _create_index(db["game_history"], [("notion_id", ASCENDING)], unique=True)
    _create_index(db["game_history"], [("deck_slug", ASCENDING)])
    _create_index(db["game_history"], [("date", ASCENDING)])
    _create_index(db["scryfall_oracle"], [("oracle_id", ASCENDING)], unique=True)
    _create_index(db["scryfall_oracle"], [("name", ASCENDING)])
    _create_index(db["scryfall_bulk"], [("id", ASCENDING)], unique=True)
    _create_index(db["scryfall_bulk"], [("name", ASCENDING)])
    _create_index(db["scryfall_bulk"], [("oracle_id", ASCENDING)])
    _create_index(db["scryfall_oracle_tags"], [("id", ASCENDING)], unique=True)
    _create_index(db["scryfall_oracle_tags"], [("taggings.oracle_id", ASCENDING)])
    _create_index(db["scryfall_oracle_tags"], [("label", TEXT), ("description", TEXT)])
    _create_index(db["scryfall_rulings"], [("oracle_id", ASCENDING)], unique=True)
    _create_index(db["rules_numbered"], [("number", ASCENDING)], unique=True)
    _create_index(db["rules_numbered"], [("section", ASCENDING)])
    _create_index(db["rules_glossary"], [("term", ASCENDING)], unique=True)
    _create_index(db["commander_banned_list"], [("name", ASCENDING)], unique=True)
    _create_index(db["commander_brackets"], [("number", ASCENDING)], unique=True)
    _create_index(db["commander_game_changers"], [("name", ASCENDING)], unique=True)
    _create_index(db["commander_bracket_announcements"], [("url", ASCENDING)], unique=True)
    _create_index(db["commander_banr_announcements"], [("url", ASCENDING)], unique=True)
    _create_index(db["commander_combos"], [("variant_id", ASCENDING)], unique=True)
    _create_index(db["commander_combos"], [("uses.oracle_id", ASCENDING)])
    _create_index(db["commander_spellbook_templates"], [("template_id", ASCENDING)], unique=True)
    _create_index(db["commander_spellbook_templates"], [("oracle_ids", ASCENDING)])
    _create_index(
        db["card_usage_stats"],
        [("commander_oracle_id", ASCENDING), ("oracle_id", ASCENDING), ("scope", ASCENDING)],
        unique=True,
    )
    _create_index(db["card_usage_stats"], [("oracle_id", ASCENDING)])
    _create_index(
        db["edhrec_commander_meta"],
        [("commander_oracle_id", ASCENDING), ("scope", ASCENDING)],
        unique=True,
    )
    # Structured-document tier: already atomic at ingestion, just full-text-index in place.
    _create_index(db["rules_numbered"], [("title", TEXT), ("text", TEXT)])
    _create_index(db["rules_glossary"], [("term", TEXT), ("definition", TEXT)])
    # Article tier: shared chunk store for long-form prose (announcements, future primers).
    _create_index(db["content_chunks"], [("source_url", ASCENDING)])
    _create_index(db["content_chunks"], [("category", ASCENDING)])
    _create_index(db["content_chunks"], [("topic_tags", ASCENDING)])
    _create_index(db["content_chunks"], [("title", TEXT), ("text", TEXT)])
    # Short-form tier: atomic player-stated preferences, one document per statement.
    _create_index(db["player_preferences"], [("deck_slug", ASCENDING)])
    _create_index(db["player_preferences"], [("stated_at", ASCENDING)])
    _create_index(db["player_preferences"], [("text", TEXT)])
    # Reference decklists: other people's Moxfield decks (e.g. linked from strategy
    # articles), kept structured like `decks` but entirely separate — no slug, no
    # Notion/decks.yaml involvement.
    _create_index(db["reference_decklists"], [("moxfield_id", ASCENDING)], unique=True)
    _create_index(db["reference_decklists"], [("source_url", ASCENDING)])
    _create_index(db["reference_decklists"], [("type", ASCENDING)])
    _create_index(db["reference_decklists"], [("commanders.name", ASCENDING)])
    # DeckCheck AI-analysis sync: per-deck field lives on `decks` itself (see
    # sync_deckcheck_analysis in tools/decks.py); this collection only tracks
    # syncs that couldn't be matched to a deck, surfaced at CLI session start.
    _create_index(db["decks"], [("commanders.name", ASCENDING)])
    _create_index(db["deckcheck_sync_failures"], [("acknowledged", ASCENDING)])


def upsert_deck(slug: str, data: dict[str, Any]) -> None:
    data["last_synced"] = datetime.now(timezone.utc)
    decks().update_one({"slug": slug}, {"$set": data}, upsert=True)


def get_deck(slug: str) -> dict[str, Any] | None:
    return decks().find_one({"slug": slug}, {"_id": 0})


def get_deck_by_notion_id(notion_id: str) -> dict[str, Any] | None:
    return decks().find_one({"notion_id": notion_id}, {"_id": 0})


def get_deck_by_moxfield_id(moxfield_id: str) -> dict[str, Any] | None:
    return decks().find_one({"moxfield_id": moxfield_id}, {"_id": 0})


def get_deck_by_commander_name(commander_name: str) -> dict[str, Any] | None:
    return decks().find_one({"commanders.name": commander_name}, {"_id": 0})


def log_deckcheck_sync_failure(doc: dict[str, Any]) -> None:
    doc["logged_at"] = datetime.now(timezone.utc)
    doc["acknowledged"] = False
    get_db()["deckcheck_sync_failures"].insert_one(doc)


def get_unacknowledged_deckcheck_sync_failures() -> list[dict[str, Any]]:
    return list(get_db()["deckcheck_sync_failures"].find({"acknowledged": False}, {"_id": 0}))


def acknowledge_deckcheck_sync_failures() -> None:
    get_db()["deckcheck_sync_failures"].update_many({"acknowledged": False}, {"$set": {"acknowledged": True}})


def upsert_reference_decklist(moxfield_id: str, data: dict[str, Any]) -> None:
    data["last_synced"] = datetime.now(timezone.utc)
    get_db()["reference_decklists"].update_one(
        {"moxfield_id": moxfield_id}, {"$set": data}, upsert=True
    )


def get_reference_decklist(moxfield_id: str) -> dict[str, Any] | None:
    return get_db()["reference_decklists"].find_one({"moxfield_id": moxfield_id}, {"_id": 0})


def get_all_reference_decklists() -> list[dict[str, Any]]:
    return list(get_db()["reference_decklists"].find({}, {"_id": 0}))


def get_reference_decklists_by_type(deck_type: str) -> list[dict[str, Any]]:
    return list(get_db()["reference_decklists"].find({"type": deck_type}, {"_id": 0}))


def get_reference_decklists_by_commander(
    commander_name: str, deck_type: str = "design_exemplar"
) -> list[dict[str, Any]]:
    return list(
        get_db()["reference_decklists"].find(
            {"commanders.name": commander_name, "type": deck_type}, {"_id": 0}
        )
    )


def update_reference_decklist_tags(moxfield_id: str, new_tags: list[str]) -> None:
    get_db()["reference_decklists"].update_one(
        {"moxfield_id": moxfield_id}, {"$set": {"strategy_tags": new_tags}}
    )


def update_reference_decklist_metadata(moxfield_id: str, fields: dict[str, Any]) -> None:
    get_db()["reference_decklists"].update_one({"moxfield_id": moxfield_id}, {"$set": fields})


def upsert_game_record(record: dict[str, Any]) -> None:
    get_db()["game_history"].update_one(
        {"notion_id": record["notion_id"]},
        {"$set": record},
        upsert=True,
    )


def get_game_history(deck_slug: str) -> list[dict[str, Any]]:
    return list(get_db()["game_history"].find(
        {"deck_slug": deck_slug},
        {"_id": 0},
        sort=[("date", ASCENDING)],
    ))


def get_known_game_ids(deck_slug: str) -> set[str]:
    docs = get_db()["game_history"].find({"deck_slug": deck_slug}, {"notion_id": 1, "_id": 0})
    return {d["notion_id"] for d in docs}


def resolve_commander_name(name: str) -> str | None:
    """
    Resolve a shortened commander name to its full Scryfall card name.
    Returns the resolved name, or None if already exact or unresolvable.
    Skips dual-commander pair strings (containing "//").

    Tries comma OR space after the prefix so both "Lurrus, the Dream-Den" and
    "Feldon of the Third Path" / "Niv-Mizzet Reborn" are reachable. When
    multiple cards match (e.g. "Titania" → two cards), cross-references known
    deck commanders to break the tie.
    """
    if "//" in name:
        return None
    db = get_db()
    # Only skip resolution if the exact name is itself a Legendary (i.e. already a commander).
    # Non-Legendary exact matches (e.g. Vanguard cards) shouldn't block resolution.
    exact = db["scryfall_oracle"].find_one({"name": name}, {"type_line": 1, "_id": 0})
    if exact and "Legendary" in (exact.get("type_line") or ""):
        return None
    pattern = re.compile(f"^{re.escape(name)}[, ]", re.IGNORECASE)
    matches = list(db["scryfall_oracle"].find(
        {"name": pattern, "type_line": re.compile("Legendary")},
        {"name": 1, "_id": 0},
    ).limit(10))
    if len(matches) == 1:
        return matches[0]["name"]
    if len(matches) > 1:
        # Break tie by preferring a commander John actually plays
        known = {
            c["name"]
            for deck in db["decks"].find({}, {"commanders.name": 1, "_id": 0})
            for c in deck.get("commanders", [])
        }
        deck_matches = [m["name"] for m in matches if m["name"] in known]
        if len(deck_matches) == 1:
            return deck_matches[0]
    if matches:
        return None

    # Fallback: the name may already be a comma-stripped full name written back to
    # Notion by a previous sync (e.g. "Sidisi Brood Tyrant" from "Sidisi, Brood
    # Tyrant") — the pattern above requires a comma/space right after the exact
    # prefix, which a stripped name no longer has. Compare comma-insensitively.
    first_word = re.escape(name.split(" ")[0])
    candidates = db["scryfall_oracle"].find(
        {"name": re.compile(f"^{first_word}[, ]", re.IGNORECASE), "type_line": re.compile("Legendary")},
        {"name": 1, "_id": 0},
    ).limit(20)
    norm_target = name.replace(",", "").lower()
    for c in candidates:
        if c["name"].replace(",", "").lower() == norm_target:
            return c["name"]
    return None


def get_enemy_commander_stats(deck_slug: str | None = None) -> list[dict[str, Any]]:
    """Aggregate enemy commander appearances and win rates from game_history."""
    pipeline: list[dict] = []
    if deck_slug:
        pipeline.append({"$match": {"deck_slug": deck_slug}})
    pipeline += [
        {"$unwind": "$enemy_commanders"},
        {"$group": {
            "_id": "$enemy_commanders",
            "appearances": {"$sum": 1},
            "wins": {"$sum": {"$cond": [{"$eq": ["$winner", "$enemy_commanders"]}, 1, 0]}},
        }},
        {"$project": {
            "_id": 0,
            "commander": "$_id",
            "appearances": 1,
            "wins": 1,
            "win_rate": {"$round": [{"$divide": ["$wins", "$appearances"]}, 2]},
        }},
        {"$sort": {"appearances": -1, "wins": -1}},
    ]
    return list(get_db()["game_history"].aggregate(pipeline))


def get_oracle_card(name: str) -> dict[str, Any] | None:
    """Look up canonical Oracle data for a card by name."""
    return get_db()["scryfall_oracle"].find_one({"name": name}, {"_id": 0})


def get_bulk_card(name: str) -> dict[str, Any] | None:
    """Look up canonical Oracle data for a card by name. Alias for get_oracle_card."""
    return get_oracle_card(name)


def get_printings(name: str) -> list[dict[str, Any]]:
    """Return all English printings of a card from the scryfall_bulk collection."""
    return list(get_db()["scryfall_bulk"].find({"name": name}, {"_id": 0}))


def get_printing_by_id(scryfall_id: str) -> dict[str, Any] | None:
    """Look up a specific printing by Scryfall card ID."""
    return get_db()["scryfall_bulk"].find_one({"id": scryfall_id}, {"_id": 0})


def get_prices_by_scryfall_ids(scryfall_ids: list[str]) -> dict[str, dict]:
    """Batch lookup prices from scryfall_bulk keyed by scryfall_id."""
    docs = get_db()["scryfall_bulk"].find(
        {"id": {"$in": scryfall_ids}},
        {"_id": 0, "id": 1, "prices": 1},
    )
    return {d["id"]: d.get("prices", {}) for d in docs}


def get_card_rulings(oracle_id: str) -> list[dict[str, Any]]:
    """Return Oracle rulings for a card by oracle_id."""
    doc = get_db()["scryfall_rulings"].find_one({"oracle_id": oracle_id}, {"_id": 0})
    return doc["rulings"] if doc else []


_TAG_WEIGHT_RANK = {"very_strong": 0, "strong": 1, "median": 2, "low": 3}


def _sort_tag_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(hits, key=lambda h: (_TAG_WEIGHT_RANK.get(h["weight"], 9), h["label"]))


def get_tags_for_oracle_ids(
    oracle_ids: list[str], gameplay_only: bool = True
) -> dict[str, list[dict[str, Any]]]:
    """
    Batch reverse-lookup: oracle_id -> [{label, weight}, ...] (sorted by weight,
    strongest first), scanning scryfall_oracle_tags.taggings for the given ids.
    gameplay_only=True (default) drops trivia/flavor/reprint-cycle tags — see
    mtg_agent.tag_filters.is_gameplay_tag.
    """
    if not oracle_ids:
        return {}
    from mtg_agent.tag_filters import is_gameplay_tag

    by_id: dict[str, list[dict[str, Any]]] = {oid: [] for oid in oracle_ids}
    cursor = get_db()["scryfall_oracle_tags"].find(
        {"taggings.oracle_id": {"$in": oracle_ids}},
        {"_id": 0, "slug": 1, "label": 1, "taggings": 1},
    )
    for tag in cursor:
        if gameplay_only and not is_gameplay_tag(tag["slug"]):
            continue
        for tagging in tag["taggings"]:
            oid = tagging.get("oracle_id")
            if oid in by_id:
                by_id[oid].append({"label": tag["label"], "weight": tagging.get("weight", "median")})

    return {oid: _sort_tag_hits(hits) for oid, hits in by_id.items()}


def get_tags_for_oracle_id(oracle_id: str, gameplay_only: bool = True) -> list[dict[str, Any]]:
    """Single-card convenience wrapper around get_tags_for_oracle_ids()."""
    return get_tags_for_oracle_ids([oracle_id], gameplay_only=gameplay_only).get(oracle_id, [])


def search_tags(query: str, gameplay_only: bool = True, limit: int = 25) -> list[dict[str, Any]]:
    """
    Search Scryfall tag labels/descriptions by keyword. Ranks whole-word matches
    (e.g. "ramp" matching "land ramp") above plain substring matches (e.g. "ramp"
    inside "gives trample") so common query words don't get buried. Use this to
    discover a tag's exact slug before calling get_cards_by_tag().
    """
    from mtg_agent.tag_filters import is_gameplay_tag

    pattern = re.compile(re.escape(query), re.IGNORECASE)
    word_pattern = re.compile(rf"(^|[\s-]){re.escape(query)}($|[\s-])", re.IGNORECASE)
    cursor = get_db()["scryfall_oracle_tags"].find(
        {"$or": [{"label": pattern}, {"slug": pattern}]},
        {"_id": 0, "label": 1, "slug": 1, "description": 1, "taggings": 1},
    ).limit(500)

    candidates = []
    for tag in cursor:
        if gameplay_only and not is_gameplay_tag(tag["slug"]):
            continue
        is_word_match = bool(word_pattern.search(tag["label"]) or word_pattern.search(tag["slug"]))
        candidates.append((
            0 if is_word_match else 1,
            {
                "label": tag["label"],
                "slug": tag["slug"],
                "description": tag.get("description"),
                "card_count": len(tag["taggings"]),
            },
        ))

    candidates.sort(key=lambda c: (c[0], -c[1]["card_count"]))
    return [c[1] for c in candidates[:limit]]


def get_cards_by_tag(tag: str, gameplay_only: bool = True, limit: int = 200) -> dict[str, Any]:
    """
    Return all cards carrying a given tag (exact label or slug match, case-insensitive),
    joined against scryfall_oracle for names, sorted by weight then name.
    """
    pattern = re.compile(f"^{re.escape(tag)}$", re.IGNORECASE)
    doc = get_db()["scryfall_oracle_tags"].find_one(
        {"$or": [{"label": pattern}, {"slug": pattern}]},
        {"_id": 0, "label": 1, "slug": 1, "description": 1, "taggings": 1},
    )
    if not doc:
        return {"error": f"No tag found matching '{tag}'. Try search_tags() to find the right slug."}
    if gameplay_only:
        from mtg_agent.tag_filters import is_gameplay_tag
        if not is_gameplay_tag(doc["slug"]):
            return {"error": f"'{doc['label']}' is filtered out as a non-gameplay tag."}

    oracle_ids = [t["oracle_id"] for t in doc["taggings"]]
    weight_by_id = {t["oracle_id"]: t.get("weight", "median") for t in doc["taggings"]}
    names = get_db()["scryfall_oracle"].find(
        {"oracle_id": {"$in": oracle_ids}}, {"_id": 0, "oracle_id": 1, "name": 1}
    )
    name_by_id = {c["oracle_id"]: c["name"] for c in names}

    cards = [
        {"name": name_by_id.get(oid, oid), "oracle_id": oid, "weight": weight_by_id[oid]}
        for oid in oracle_ids
        if oid in name_by_id
    ]
    cards.sort(key=lambda c: (_TAG_WEIGHT_RANK.get(c["weight"], 9), c["name"]))

    return {
        "label": doc["label"],
        "slug": doc["slug"],
        "description": doc.get("description"),
        "total_cards": len(cards),
        "cards": cards[:limit],
    }


def get_rule(number: str) -> dict[str, Any] | None:
    """Look up a single Comprehensive Rules entry by its rule number (e.g. '903.5c')."""
    return get_db()["rules_numbered"].find_one({"number": number}, {"_id": 0})


def get_rules_section(section: str) -> list[dict[str, Any]]:
    """Return all Comprehensive Rules entries under a top-level section (e.g. '9' for Additional Rules)."""
    return list(get_db()["rules_numbered"].find(
        {"section": section}, {"_id": 0}, sort=[("number", ASCENDING)]
    ))


def get_glossary_term(term: str) -> dict[str, Any] | None:
    """Look up a Comprehensive Rules glossary entry by term (case-insensitive)."""
    return get_db()["rules_glossary"].find_one(
        {"term": re.compile(f"^{re.escape(term)}$", re.IGNORECASE)}, {"_id": 0}
    )


def is_commander_banned(card_name: str) -> bool:
    """Check whether a card is on the official Commander banned list by exact name."""
    return get_db()["commander_banned_list"].find_one(
        {"name": card_name, "type": "card"}, {"_id": 0}
    ) is not None


def get_commander_banned_list() -> list[dict[str, Any]]:
    """Return the full official Commander banned list (named cards + blanket ban categories)."""
    return list(get_db()["commander_banned_list"].find({}, {"_id": 0}))


def get_commander_brackets() -> list[dict[str, Any]]:
    """Return the official Commander Brackets definitions (overview + brackets 1-5)."""
    return list(get_db()["commander_brackets"].find({}, {"_id": 0}, sort=[("number", ASCENDING)]))


def is_game_changer(card_name: str) -> bool:
    """Check whether a card is on the official Commander Game Changers list by exact name."""
    return get_db()["commander_game_changers"].find_one({"name": card_name}, {"_id": 0}) is not None


def get_game_changers() -> list[dict[str, Any]]:
    """Return the full official Commander Game Changers list, with color category per card."""
    return list(get_db()["commander_game_changers"].find({}, {"_id": 0}))


def list_commander_bracket_announcements() -> list[dict[str, Any]]:
    """List official Commander Format Panel Bracket announcements (metadata only, no body text), oldest first."""
    return list(get_db()["commander_bracket_announcements"].find(
        {}, {"_id": 0, "text": 0}, sort=[("published_date", ASCENDING)]
    ))


def get_commander_bracket_announcement(url: str) -> dict[str, Any] | None:
    """Retrieve the full text of one Commander Bracket announcement by its URL."""
    return get_db()["commander_bracket_announcements"].find_one({"url": url}, {"_id": 0})


def list_commander_banr_announcements() -> list[dict[str, Any]]:
    """List official Commander Banned & Restricted announcements (metadata only, no body text), oldest first."""
    return list(get_db()["commander_banr_announcements"].find(
        {}, {"_id": 0, "text": 0}, sort=[("published_date", ASCENDING)]
    ))


def get_commander_banr_announcement(url: str) -> dict[str, Any] | None:
    """Retrieve the full text of one Commander Banned & Restricted announcement by its URL."""
    return get_db()["commander_banr_announcements"].find_one({"url": url}, {"_id": 0})


def replace_content_chunks(source_url: str, chunks: list[dict[str, Any]]) -> None:
    """
    Replace all chunks for a given source (article tier — see chunking.py).
    Delete-then-insert rather than upsert, since re-ingestion may produce a
    different number of chunks than last time.
    """
    db = get_db()
    db["content_chunks"].delete_many({"source_url": source_url})
    if chunks:
        db["content_chunks"].insert_many(chunks)


def search_content_chunks(
    query: str,
    category: str | None = None,
    topic_tags: list[str] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Keyword search over chunked long-form content (article tier: WotC
    announcements, primers/strategy articles). Optionally filter to one category
    (e.g. "commander_bracket_announcements") and/or by topic_tags (matches if a
    chunk has any of the given tags) — topic_tags is the intended cross-archetype
    retrieval axis for primer/strategy_article content (see tools/articles.py):
    a primer's commander_names may not match the deck being discussed, but its
    topic_tags (e.g. "damage-race-math") can still surface it.
    """
    filter_: dict[str, Any] = {"$text": {"$search": query}}
    if category:
        filter_["category"] = category
    if topic_tags:
        filter_["topic_tags"] = {"$in": topic_tags}
    return list(get_db()["content_chunks"].find(
        filter_,
        {"_id": 0, "score": {"$meta": "textScore"}},
    ).sort([("score", {"$meta": "textScore"})]).limit(limit))


def insert_player_preference(doc: dict[str, Any]) -> str:
    """
    Record one atomic player-stated preference/playstyle statement
    (short-form tier — see docs/data_sources_roadmap.md). Append-only:
    no update/dedup on write, evolution is tracked by stated_at and
    resolved at read time (recency as tiebreaker on conflicting statements).
    """
    result = get_db()["player_preferences"].insert_one(doc)
    return str(result.inserted_id)


def search_player_preferences(query: str, deck_slug: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """
    Keyword search over recorded player preferences, ranked by text
    relevance with recency as a secondary sort (tiebreaker for
    conflicting/evolved statements). Optionally scope to one deck.
    """
    filter_: dict[str, Any] = {"$text": {"$search": query}}
    if deck_slug:
        filter_["deck_slug"] = deck_slug
    return list(get_db()["player_preferences"].find(
        filter_,
        {"_id": 0, "score": {"$meta": "textScore"}},
    ).sort([("score", {"$meta": "textScore"}), ("stated_at", -1)]).limit(limit))


def search_rules(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """
    Keyword search over the Comprehensive Rules (structured-document tier —
    already atomic per rule number, so this searches in place with no
    separate chunk store).
    """
    return list(get_db()["rules_numbered"].find(
        {"$text": {"$search": query}},
        {"_id": 0, "score": {"$meta": "textScore"}},
    ).sort([("score", {"$meta": "textScore"})]).limit(limit))


def search_glossary(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Keyword search over the Comprehensive Rules glossary (structured-document tier)."""
    return list(get_db()["rules_glossary"].find(
        {"$text": {"$search": query}},
        {"_id": 0, "score": {"$meta": "textScore"}},
    ).sort([("score", {"$meta": "textScore"})]).limit(limit))
