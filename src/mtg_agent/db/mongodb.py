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
