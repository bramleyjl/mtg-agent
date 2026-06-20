import json
import os

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from mtg_agent.config import load_config
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
    type line, etc.) plus the Notion deck page content (EDH game history, notes, links).

    Prefer get_deck() for lightweight queries; use this only when card text or
    game history is needed.
    """
    return await decks.get_deck_full(slug, config)



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



@mcp.custom_route("/sync-deck", methods=["POST"])
async def http_sync_deck(request: Request) -> JSONResponse:
    """
    HTTP endpoint for the browser extension. Accepts pre-fetched Moxfield deck data
    so the extension can pass its authenticated response directly, bypassing the 403.
    Body: { "moxfield_id": "...", "deck_data": { ...Moxfield API response... } }
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    moxfield_id = body.get("moxfield_id")
    deck_data = body.get("deck_data")

    if not moxfield_id or not deck_data:
        return JSONResponse({"error": "Missing moxfield_id or deck_data"}, status_code=400)

    slug = next(
        (d.slug for d in config.decks if d.moxfield_id == moxfield_id),
        None,
    )
    if not slug:
        return JSONResponse(
            {"error": f"No deck registered with moxfield_id '{moxfield_id}'. Add it to decks.yaml first."},
            status_code=404,
        )

    result = await decks.sync_deck(slug, config, prefetched_data=deck_data)
    if "error" in result:
        return JSONResponse(result, status_code=500)
    return JSONResponse(result)


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
