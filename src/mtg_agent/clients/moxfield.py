import re
from collections import defaultdict

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


def _card_tags(entry: dict) -> list[str]:
    """Extract Moxfield category tags from a card entry wrapper."""
    tags = entry.get("tags") or entry.get("categories") or []
    return [t for t in tags if isinstance(t, str)]


def extract_card_list(deck_data: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Returns (commander_entries, mainboard_entries, maybeboard_entries).
    Each entry: {"name": str, "scryfall_id": str | None, "quantity": int, "tags": list[str]}
    scryfall_id is the specific printing the user has selected in Moxfield.
    tags are Moxfield's custom card category labels (e.g. "Ramp", "Draw", "Removal").
    """
    boards = _get_boards(deck_data)

    commanders = []
    for entry in boards.get("commanders", {}).get("cards", {}).values():
        commanders.append({
            "name": entry["card"]["name"],
            "scryfall_id": entry["card"].get("scryfall_id"),
            "quantity": 1,
            "tags": _card_tags(entry),
        })

    mainboard = []
    for entry in boards.get("mainboard", {}).get("cards", {}).values():
        mainboard.append({
            "name": entry["card"]["name"],
            "scryfall_id": entry["card"].get("scryfall_id"),
            "quantity": entry["quantity"],
            "tags": _card_tags(entry),
        })

    maybeboard = []
    for board_key in ("maybeboard", "considering", "sideboard"):
        board = boards.get(board_key, {}).get("cards", {})
        if board:
            for entry in board.values():
                maybeboard.append({
                    "name": entry["card"]["name"],
                    "scryfall_id": entry["card"].get("scryfall_id"),
                    "quantity": entry.get("quantity", 1),
                    "tags": _card_tags(entry),
                    "board": board_key,
                })
            break  # use the first non-empty board found

    return commanders, mainboard, maybeboard


def extract_deck_meta(deck_data: dict) -> dict:
    """Pull deck-level metadata beyond name and timestamp."""
    hubs = [h.get("name") for h in (deck_data.get("hubs") or []) if h.get("name")]
    return {
        "description": deck_data.get("description") or None,
        "format": deck_data.get("format") or None,
        "created_at": deck_data.get("createdAtUtc") or None,
        "hubs": hubs or None,
        "color_percentages": deck_data.get("colorPercentages") or None,
        "color_identity_percentages": deck_data.get("colorIdentityPercentages") or None,
        "bracket": deck_data.get("bracket") or deck_data.get("userBracket") or None,
    }


# Mana symbol regex: matches {W}, {U}, {B}, {R}, {G}, {C}, {X}, {2/W}, etc.
_PIP_RE = re.compile(r"\{([^}]+)\}")
_COLOR_PIPS = {"W", "U", "B", "R", "G"}


def _classify_type(type_line: str, card_faces: list | None = None, layout: str | None = None) -> str:
    if card_faces:
        if layout == "modal_dfc":
            # Player chooses face at cast time — land face is always available.
            if any("land" in (f.get("type_line") or "").lower() for f in card_faces):
                return "land"
        elif layout == "transform":
            # Flips conditionally — only the front face determines card type.
            type_line = card_faces[0].get("type_line") or type_line
    tl = type_line.lower()
    if "land" in tl:
        return "land"
    if "creature" in tl:
        return "creature"
    if "instant" in tl:
        return "instant"
    if "sorcery" in tl:
        return "sorcery"
    if "artifact" in tl:
        return "artifact"
    if "enchantment" in tl:
        return "enchantment"
    if "planeswalker" in tl:
        return "planeswalker"
    return "other"


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def compute_deck_stats(card_entries: list[dict], land_count: int | None = None) -> dict:
    """
    Compute deck statistics from card entries that have been enriched with Scryfall data.
    Excludes commanders (pass mainboard only). Respects quantity for basic lands and
    treats MDFCs with a land face as lands.
    """
    cmcs_no_land: list[float] = []
    cmcs_all: list[float] = []
    curve: dict[str, int] = defaultdict(int)
    pips: dict[str, int] = defaultdict(int)
    types: dict[str, int] = defaultdict(int)

    for entry in card_entries:
        scryfall = entry.get("scryfall", {})
        if not scryfall:
            continue

        qty = entry.get("quantity", 1)
        type_line = scryfall.get("type_line", "")
        card_faces = scryfall.get("card_faces")
        layout = scryfall.get("layout")
        card_type = _classify_type(type_line, card_faces, layout)
        types[card_type] += qty

        cmc = scryfall.get("cmc", 0) or 0
        cmcs_all.extend([cmc] * qty)

        if card_type != "land":
            cmcs_no_land.extend([cmc] * qty)
            bucket = str(min(int(cmc), 7))  # 7+ grouped together
            curve[bucket] += qty

        mana_cost = scryfall.get("mana_cost", "") or ""
        for sym in _PIP_RE.findall(mana_cost):
            sym_upper = sym.upper()
            # Split handles both plain pips ("G" -> ["G"]) and hybrid ones
            # ("B/G" -> ["B", "G"], counted toward both colors) uniformly —
            # do not also match sym_upper itself, or plain pips double-count.
            for part in sym_upper.split("/"):
                if part in _COLOR_PIPS:
                    pips[part] += qty

    n_lands = land_count if land_count is not None else types.get("land", 0)
    deck_size = sum(entry.get("quantity", 1) for entry in card_entries)
    avg_lands_in_hand = round(7 * n_lands / deck_size, 2) if deck_size else 0.0

    return {
        "avg_cmc": round(sum(cmcs_no_land) / len(cmcs_no_land), 2) if cmcs_no_land else 0.0,
        "avg_cmc_with_lands": round(sum(cmcs_all) / len(cmcs_all), 2) if cmcs_all else 0.0,
        "median_cmc": _median(cmcs_no_land),
        "median_cmc_with_lands": _median(cmcs_all),
        "total_cmc": sum(cmcs_all),
        "avg_lands_in_opening_hand": avg_lands_in_hand,
        "mana_curve": dict(curve),
        "color_pip_counts": dict(pips),
        "type_counts": dict(types),
    }
