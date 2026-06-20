from mtg_agent.clients.scryfall import search_cards as _search_scryfall
from mtg_agent.db.mongodb import get_cached_card


async def search_cards(query: str, page: int = 1) -> dict:
    """
    Search for cards using Scryfall's full query syntax.
    Supports all Scryfall operators: color identity, type, text, CMC, etc.
    Example queries:
      - "lightning bolt"
      - "t:creature c:r cmc<=3"
      - "o:\"draw a card\" id<=breya"
    """
    return await _search_scryfall(query, page=page)


async def get_card(name: str) -> dict | None:
    """
    Look up a single card by exact name.
    Priority: per-deck cache → bulk dataset → live Scryfall API.
    """
    from mtg_agent.db.mongodb import get_bulk_card, upsert_card_cache

    cached = get_cached_card(name) or get_bulk_card(name)
    if cached:
        return cached

    import httpx
    from mtg_agent.clients.scryfall import get_card_by_name

    async with httpx.AsyncClient(timeout=15.0) as client:
        data = await get_card_by_name(client, name)
        if data:
            upsert_card_cache(name, data)
        return data
