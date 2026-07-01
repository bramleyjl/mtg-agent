import json
import os
import re

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from mtg_agent.clients.moxfield import parse_deck_name
from mtg_agent.config import load_config
from mtg_agent.db import mongodb
from mtg_agent.db.mongodb import init_db
from mtg_agent.tools import cards, decks

config = load_config()
init_db(config.mongodb_uri, config.mongodb_db)

mcp = FastMCP(
    "mtg-agent",
    host=os.getenv("MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("MCP_PORT", "8765")),
)


@mcp.tool()
async def list_decks() -> list[dict]:
    """List all configured Commander decks with their colors, bracket, and notes."""
    return await decks.list_decks(config)


@mcp.tool()
async def get_deck(slug: str) -> dict | None:
    """
    Retrieve a deck's top-level properties and card list (names + oracle_ids only).
    Lightweight — safe to call for any deck overview or card-list work.

    Use list_decks() to see available slugs.
    Use get_deck_full() when you need oracle text, rulings, or Notion game history.
    """
    return await decks.get_deck(slug, config)


@mcp.tool()
async def get_deck_full(slug: str) -> dict | None:
    """
    Retrieve full deck context: complete Scryfall card data (oracle text, mana cost,
    type line, etc.) plus structured game history from MongoDB.

    Prefer get_deck() for lightweight queries; use this only when card text or
    game history is needed.
    """
    return await decks.get_deck_full(slug, config)


@mcp.tool()
async def sync_game_history(slug: str) -> dict:
    """
    Sync game history for a deck from Notion to MongoDB.
    Fetches only new game records not already stored (incremental).
    Run this after logging new games in Notion to bring MongoDB up to date.
    """
    return await decks.sync_game_history(slug, config)


@mcp.tool()
async def normalize_enemy_commanders() -> dict:
    """
    Resolve short/informal enemy commander names to full Scryfall card names
    across all game history records. Updates both MongoDB and Notion game pages.
    Run once after initial game history import, and again after adding new games
    with non-canonical commander names.
    """
    return await decks.normalize_enemy_commanders(config)


@mcp.tool()
async def get_enemy_commander_stats(deck_slug: str = "") -> list:
    """
    Aggregate enemy commander appearances and win rates from game history.
    Pass a deck_slug to filter to a specific deck, or omit for all decks.
    Returns commanders sorted by appearances descending.
    """
    return mongodb.get_enemy_commander_stats(deck_slug or None)



@mcp.tool()
async def search_cards(query: str, page: int = 1) -> dict:
    """
    Search for MTG cards using Scryfall's full query syntax.

    Examples:
      - "lightning bolt"
      - "t:creature c:r cmc<=3"
      - "o:\\"draw a card\\" id<=breya"
      - "is:commander id:WUB"

    Returns up to 175 cards per page; check has_more for pagination.
    """
    return await cards.search_cards(query, page=page)


@mcp.tool()
async def get_card(name: str) -> dict | None:
    """
    Look up a single card by exact name. Checks local cache first,
    then falls back to Scryfall.
    """
    return await cards.get_card(name)



_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


@mcp.custom_route("/sync-deck", methods=["POST", "OPTIONS"])
async def http_sync_deck(request: Request) -> JSONResponse:
    """
    HTTP endpoint for the browser extension. Accepts pre-fetched Moxfield deck data
    so the extension can pass its authenticated response directly, bypassing the 403.
    Body: { "moxfield_id": "...", "deck_data": { ...Moxfield API response... } }
    """
    if request.method == "OPTIONS":
        return JSONResponse(None, status_code=204, headers=_CORS_HEADERS)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400, headers=_CORS_HEADERS)

    moxfield_id = body.get("moxfield_id")
    deck_data = body.get("deck_data")

    if not moxfield_id or not deck_data:
        return JSONResponse({"error": "Missing moxfield_id or deck_data"}, status_code=400, headers=_CORS_HEADERS)

    # Resolve slug: config match → existing DB record → auto-generate from deck name
    config_deck = next((d for d in config.decks if d.moxfield_id == moxfield_id), None)
    if config_deck:
        slug = config_deck.slug
    else:
        stored = mongodb.get_deck_by_moxfield_id(moxfield_id)
        if stored:
            slug = stored["slug"]
        else:
            raw_name, _ = parse_deck_name(deck_data.get("name", moxfield_id))
            slug = re.sub(r"[^a-z0-9]+", "_", raw_name.lower()).strip("_") or moxfield_id

    result = await decks.sync_deck(slug, config, prefetched_data=deck_data, moxfield_id=moxfield_id)
    status = 500 if "error" in result else 200
    return JSONResponse(result, status_code=status, headers=_CORS_HEADERS)


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
