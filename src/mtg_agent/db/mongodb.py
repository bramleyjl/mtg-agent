import re
from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient, ASCENDING
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
    _create_index(db["scryfall_rulings"], [("oracle_id", ASCENDING)], unique=True)


def upsert_deck(slug: str, data: dict[str, Any]) -> None:
    data["last_synced"] = datetime.now(timezone.utc)
    decks().update_one({"slug": slug}, {"$set": data}, upsert=True)


def get_deck(slug: str) -> dict[str, Any] | None:
    return decks().find_one({"slug": slug}, {"_id": 0})


def get_deck_by_notion_id(notion_id: str) -> dict[str, Any] | None:
    return decks().find_one({"notion_id": notion_id}, {"_id": 0})


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


def get_card_rulings(oracle_id: str) -> list[dict[str, Any]]:
    """Return Oracle rulings for a card by oracle_id."""
    doc = get_db()["scryfall_rulings"].find_one({"oracle_id": oracle_id}, {"_id": 0})
    return doc["rulings"] if doc else []


def get_card_oracle_tags(oracle_id: str) -> dict[str, Any] | None:
    """Return Scryfall oracle tag entry for a card by oracle_id."""
    return get_db()["scryfall_oracle_tags"].find_one({"oracle_id": oracle_id}, {"_id": 0})
