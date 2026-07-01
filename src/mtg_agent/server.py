import json
import os
import re

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mtg_agent.clients.moxfield import parse_deck_name
from mtg_agent.config import load_config
from mtg_agent.db import mongodb
from mtg_agent.db.mongodb import init_db
from mtg_agent.tools import cards, decks, probability

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


@mcp.tool()
async def calculate_draw_probability(
    deck_size: int,
    successes_in_deck: int,
    sample_size: int,
    min_successes: int = 1,
) -> dict:
    """
    Hypergeometric draw probability for a card/category in a deck.

    Example: "I run 10 ramp spells in a 99-card deck, what's the chance I've
    drawn at least 1 by turn 3?" (multiplayer Commander, draw every turn) ->
      deck_size=99, successes_in_deck=10, sample_size=10 (7 + 3 draws), min_successes=1
    Use cards_seen_by_turn() to compute sample_size from a turn number.

    Returns probability_exactly/at_least/at_most for min_successes.
    """
    return probability.hypergeometric_probability(
        deck_size, successes_in_deck, sample_size, min_successes
    )


@mcp.tool()
async def cards_seen_by_turn(turn: int, starting_hand: int = 7) -> int:
    """
    Cards seen by the end of a given turn's draw step. Commander is
    multiplayer, so every player draws every turn including turn 1 (the
    "skip first draw" rule only applies in two-player games). Feed the
    result into calculate_draw_probability()'s sample_size.
    """
    return probability.cards_seen_by_turn(turn, starting_hand=starting_hand)


@mcp.tool()
async def get_comprehensive_rule(number: str) -> dict | None:
    """
    Look up a single Comprehensive Rules entry by rule number, e.g. "903.5c"
    (a subrule), "903" (the Commander section header), or "9" (a top-level
    section like "Casual Variants"). Use get_comprehensive_rules_section()
    to browse all entries under a section, or get_rules_glossary_term() for
    a defined term.
    """
    return mongodb.get_rule(number)


@mcp.tool()
async def get_comprehensive_rules_section(section: str) -> list[dict]:
    """
    Return all Comprehensive Rules entries under a top-level section (1-9),
    e.g. "9" for Casual Variants (includes rule 903 "Commander").
    """
    return mongodb.get_rules_section(section)


@mcp.tool()
async def get_rules_glossary_term(term: str) -> dict | None:
    """Look up a Comprehensive Rules glossary term's official definition (case-insensitive)."""
    return mongodb.get_glossary_term(term)


@mcp.tool()
async def get_commander_banned_list() -> list[dict]:
    """
    Return the full official Commander banned list: individually named banned
    cards plus blanket ban categories (e.g. all Conspiracy-type cards, all
    "ante" cards). For whether one specific card is banned, prefer get_card()
    — Scryfall's legalities.commander field is the source of truth for
    per-card legality; this list is the reference text itself.
    """
    return mongodb.get_commander_banned_list()


@mcp.tool()
async def get_commander_brackets() -> list[dict]:
    """Return the official Commander Brackets definitions: overview plus brackets 1 (Exhibition) through 5 (cEDH)."""
    return mongodb.get_commander_brackets()


@mcp.tool()
async def get_commander_game_changers() -> list[dict]:
    """
    Return the full official Commander Game Changers list (53 cards, grouped
    by color category). Game Changers aren't banned — legal everywhere, but
    capped at 3 in Bracket 3 and unrestricted in Brackets 4-5, excluded from
    Brackets 1-2. For whether one specific card is a Game Changer, prefer
    get_card() — Scryfall's game_changer field is the source of truth for
    per-card status; this list is the reference text itself.
    """
    return mongodb.get_game_changers()


@mcp.tool()
async def list_commander_bracket_announcements() -> list[dict]:
    """
    List the official Commander Format Panel announcements about the Brackets
    system (title, date, author, url — no body text). Use
    get_commander_bracket_announcement() with a url from this list to read
    the full article, e.g. for WotC's stated reasoning behind a bracket change.
    """
    return mongodb.list_commander_bracket_announcements()


@mcp.tool()
async def get_commander_bracket_announcement(url: str) -> dict | None:
    """Retrieve the full text of one Commander Bracket announcement by its url (from list_commander_bracket_announcements())."""
    return mongodb.get_commander_bracket_announcement(url)


@mcp.tool()
async def list_commander_banr_announcements() -> list[dict]:
    """
    List the official Commander Banned & Restricted announcements (title,
    date, author, url — no body text). Use get_commander_banr_announcement()
    with a url from this list to read WotC's full stated reasoning for a
    ban/unban or format-direction commentary. Only covers announcements from
    when WotC took over B&R from the Rules Committee (2024 onward).
    """
    return mongodb.list_commander_banr_announcements()


@mcp.tool()
async def get_commander_banr_announcement(url: str) -> dict | None:
    """Retrieve the full text of one Commander Banned & Restricted announcement by its url (from list_commander_banr_announcements())."""
    return mongodb.get_commander_banr_announcement(url)


@mcp.tool()
async def search_wotc_announcements(query: str, category: str = "") -> list[dict]:
    """
    Keyword search over chunked WotC announcement text (Bracket and Banned &
    Restricted announcements) — use this instead of pulling a full article
    with get_commander_bracket_announcement()/get_commander_banr_announcement()
    when you just need the relevant paragraph(s), e.g. "why was Nadu banned"
    or "WotC's reasoning on the Lutri companion restriction."

    Returns matching chunks (source title, url, text) ranked by relevance.
    Pass category="commander_bracket_announcements" or
    category="commander_banr_announcements" to filter to one source; omit
    to search across both.
    """
    return mongodb.search_content_chunks(query, category=category or None)


@mcp.tool()
async def search_comprehensive_rules(query: str) -> list[dict]:
    """
    Keyword search over the Comprehensive Rules by content, for when you
    don't know the exact rule number — e.g. "commander tax" or "state-based
    actions." Returns matching rules ranked by relevance. Use
    get_comprehensive_rule() once you have the specific number.
    """
    return mongodb.search_rules(query)


@mcp.tool()
async def search_rules_glossary(query: str) -> list[dict]:
    """Keyword search over Comprehensive Rules glossary terms/definitions by content."""
    return mongodb.search_glossary(query)


_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def _json_response(data, status_code: int = 200) -> Response:
    """Return a JSON response without a Content-Length header to avoid h11 mismatches on large payloads."""
    body = json.dumps(data).encode()
    return Response(
        content=body,
        status_code=status_code,
        headers={**_CORS_HEADERS, "Content-Type": "application/json"},
    )


@mcp.custom_route("/sync-deck", methods=["POST", "OPTIONS"])
async def http_sync_deck(request: Request) -> JSONResponse:
    """
    HTTP endpoint for the browser extension. Accepts pre-fetched Moxfield deck data
    so the extension can pass its authenticated response directly, bypassing the 403.
    Body: { "moxfield_id": "...", "deck_data": { ...Moxfield API response... } }
    """
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_CORS_HEADERS)

    try:
        body = await request.json()
    except Exception:
        return _json_response({"error": "Invalid JSON body"}, status_code=400)

    moxfield_id = body.get("moxfield_id")
    deck_data = body.get("deck_data")

    if not moxfield_id or not deck_data:
        return _json_response({"error": "Missing moxfield_id or deck_data"}, status_code=400)

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
    return _json_response(result, status_code=status)


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
