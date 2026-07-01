import asyncio
from typing import Any

import httpx

SCRYFALL_API = "https://api.scryfall.com"

# Scryfall requests a minimum 50-100ms between requests
_REQUEST_DELAY = 0.075

ORACLE_FIELDS = {
    "oracle_id", "name", "mana_cost", "cmc", "type_line", "oracle_text",
    "colors", "color_identity", "keywords", "legalities",
    "power", "toughness", "loyalty", "produced_mana",
    "layout",       # modal_dfc vs transform — needed to distinguish unconditional MDFC lands
    "card_faces",   # for double-faced cards
}

PRINTING_FIELDS = {
    "id", "oracle_id", "name", "set", "set_name", "collector_number",
    "rarity", "prices", "image_uris", "border_color", "frame",
    "frame_effects", "full_art", "promo", "reprint", "digital",
    "finishes", "lang", "released_at", "artist", "illustration_id",
    "flavor_text",
}


def _trim_card(data: dict[str, Any]) -> dict[str, Any]:
    """Trim to Oracle-level fields for the scryfall_oracle collection."""
    return {k: v for k, v in data.items() if k in ORACLE_FIELDS}


def _trim_printing(data: dict[str, Any]) -> dict[str, Any]:
    """Trim to printing-level fields for the scryfall_bulk collection."""
    return {k: v for k, v in data.items() if k in PRINTING_FIELDS}


async def get_card_by_name(
    client: httpx.AsyncClient, name: str
) -> dict[str, Any] | None:
    """Exact card name lookup. Returns trimmed card data or None if not found."""
    await asyncio.sleep(_REQUEST_DELAY)
    try:
        response = await client.get(
            f"{SCRYFALL_API}/cards/named",
            params={"exact": name},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return _trim_card(response.json())
    except httpx.HTTPStatusError:
        return None


async def search_cards(query: str, page: int = 1) -> dict[str, Any]:
    """
    Full Scryfall search. Returns the raw search response with cards list
    and has_more / next_page fields.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{SCRYFALL_API}/cards/search",
            params={"q": query, "page": page, "order": "name"},
        )
        if response.status_code == 404:
            return {"data": [], "has_more": False, "total_cards": 0}
        response.raise_for_status()
        raw = response.json()
        return {
            "total_cards": raw.get("total_cards", 0),
            "has_more": raw.get("has_more", False),
            "cards": [_trim_card(c) for c in raw.get("data", [])],
        }
