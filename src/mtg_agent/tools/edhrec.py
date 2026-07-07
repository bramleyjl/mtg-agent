import re

from mtg_agent.clients import edhrec
from mtg_agent.config import Config
from mtg_agent.db import mongodb
from mtg_agent.scripts import refresh_edhrec

_TAG_STRIP_RE = re.compile(r"[^a-z0-9\s-]")
_TAG_SPACE_RE = re.compile(r"\s+")


def _tag_slug(tag: str) -> str:
    slug = _TAG_STRIP_RE.sub("", tag.lower())
    return _TAG_SPACE_RE.sub("-", slug.strip())


def _deck_commander(deck: dict) -> dict | None:
    commanders = deck.get("commanders", [])
    if not commanders:
        return None
    oracle_id = commanders[0].get("scryfall", {}).get("oracle_id")
    if not oracle_id:
        return None
    return {"oracle_id": oracle_id, "name": commanders[0]["name"]}


def _deck_oracle_ids(deck: dict) -> set[str]:
    commanders = deck.get("commanders", [])
    mainboard = deck.get("mainboard", [])
    ids = {c["scryfall"]["oracle_id"] for c in commanders + mainboard if c.get("scryfall", {}).get("oracle_id")}
    return ids


async def compare_deck_to_edhrec(slug: str, config: Config, scope: str = "default") -> dict:
    """
    Gap-analysis: which of a deck's own cards are EDHREC staples for its
    commander+scope, and which popular cards it's missing.
    """
    deck_conf = config.decks_by_slug.get(slug)
    if not deck_conf:
        return {"error": f"Unknown deck slug: '{slug}'"}

    deck = mongodb.get_deck(slug)
    if not deck:
        return {"error": f"Deck '{slug}' not yet synced. Run sync_deck('{slug}') first."}

    commander = _deck_commander(deck)
    if not commander:
        return {"error": f"Deck '{slug}' has no commander on file."}

    db = mongodb.get_db()
    meta = db["edhrec_commander_meta"].find_one(
        {"commander_oracle_id": commander["oracle_id"], "scope": scope}, {"_id": 0}
    )
    if not meta:
        return {
            "error": f"No EDHREC data for '{commander['name']}' scope '{scope}' yet. "
            f"Run refresh_all_data_sources() or get_edhrec_tag_data() first for a tag scope."
        }

    stats = list(db["card_usage_stats"].find(
        {"commander_oracle_id": commander["oracle_id"], "scope": scope}, {"_id": 0}
    ))
    stats.sort(key=lambda s: -(s.get("num_decks") or 0))

    deck_oracle_ids = _deck_oracle_ids(deck)

    in_deck = [s for s in stats if s["oracle_id"] in deck_oracle_ids]
    missing = [s for s in stats if s["oracle_id"] not in deck_oracle_ids]

    return {
        "slug": slug,
        "commander": commander["name"],
        "scope": scope,
        "total_decks": meta.get("total_decks"),
        "cards_in_deck": [
            {
                "name": s["card_name"], "category": s["category"],
                "synergy": s["synergy"], "inclusion_pct": s["inclusion_pct"],
            }
            for s in in_deck
        ],
        "popular_cards_missing": [
            {
                "name": s["card_name"], "category": s["category"],
                "synergy": s["synergy"], "inclusion_pct": s["inclusion_pct"],
            }
            for s in missing[:25]
        ],
    }


async def get_edhrec_tag_data(slug: str, tag: str, config: Config) -> dict:
    """
    Fetch (or refresh) a commander's tag/theme-scoped EDHREC page on demand, and
    upsert it into card_usage_stats/edhrec_commander_meta under scope "tag:<slug>".
    Once fetched, this scope is picked up automatically by future weekly refreshes.
    """
    deck_conf = config.decks_by_slug.get(slug)
    if not deck_conf:
        return {"error": f"Unknown deck slug: '{slug}'"}

    deck = mongodb.get_deck(slug)
    if not deck:
        return {"error": f"Deck '{slug}' not yet synced. Run sync_deck('{slug}') first."}

    commander = _deck_commander(deck)
    if not commander:
        return {"error": f"Deck '{slug}' has no commander on file."}

    tag_slug = _tag_slug(tag)
    scope = f"tag:{tag_slug}"

    db = mongodb.get_db()
    upserted, unresolved = refresh_edhrec.sync_scope(db, commander, scope, tag_slug)
    if upserted == 0 and unresolved == 0:
        return {"error": f"No EDHREC page found for '{commander['name']}' tag '{tag}' (tried slug '{tag_slug}')."}

    return await compare_deck_to_edhrec(slug, config, scope=scope)
