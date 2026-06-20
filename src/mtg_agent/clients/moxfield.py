import httpx

MOXFIELD_API = "https://api2.moxfield.com/v3/decks/all"

HEADERS = {
    "User-Agent": "mtg-agent/0.1 (personal deckbuilding assistant)",
    "Accept": "application/json",
}


async def fetch_deck(moxfield_id: str) -> dict:
    """Fetch a deck from the Moxfield unofficial API."""
    url = f"{MOXFIELD_API}/{moxfield_id}"
    async with httpx.AsyncClient(headers=HEADERS, timeout=15.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


def parse_deck_name(raw_name: str) -> tuple[str, str]:
    """
    Moxfield deck names follow "Name - Title" format.
    Returns (name, title); title is empty string if no separator found.
    """
    if " - " in raw_name:
        name, _, title = raw_name.partition(" - ")
        return name.strip(), title.strip()
    return raw_name.strip(), ""


def _get_boards(deck_data: dict) -> dict:
    """Return the boards dict regardless of whether they're nested under 'boards' or top-level."""
    if "boards" in deck_data:
        return deck_data["boards"]
    return deck_data


def extract_card_list(deck_data: dict) -> tuple[list[dict], list[dict]]:
    """
    Returns (commander_entries, mainboard_entries).
    Each entry: {"name": str, "scryfall_id": str | None, "quantity": int}
    scryfall_id is the specific printing the user has selected in Moxfield.
    """
    boards = _get_boards(deck_data)

    commanders = []
    for card in boards.get("commanders", {}).get("cards", {}).values():
        commanders.append({
            "name": card["card"]["name"],
            "scryfall_id": card["card"].get("scryfall_id"),
            "quantity": 1,
        })

    mainboard = []
    for card in boards.get("mainboard", {}).get("cards", {}).values():
        mainboard.append({
            "name": card["card"]["name"],
            "scryfall_id": card["card"].get("scryfall_id"),
            "quantity": card["quantity"],
        })

    return commanders, mainboard
