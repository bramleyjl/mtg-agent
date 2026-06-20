from pathlib import Path

import httpx
import yaml

from mtg_agent.clients import moxfield, scryfall
from mtg_agent.clients.notion_mcp import update_deck_page
from mtg_agent.config import Config
from mtg_agent.db import mongodb
from mtg_agent.db.mongodb import get_bulk_card, get_printing_by_id


async def session_sync(config: Config) -> list[dict]:
    """
    For each configured deck: push current name/title from MongoDB to Notion via notion-mcp,
    and return a status row with timestamps so stale decks are visible.
    """
    results = []
    for deck_conf in config.decks:
        stored = mongodb.get_deck(deck_conf.slug)
        row: dict = {
            "slug": deck_conf.slug,
            "last_synced": stored.get("last_synced") if stored else None,
            "moxfield_updated_at": stored.get("moxfield_updated_at") if stored else None,
            "notion": None,
        }

        if not stored:
            row["notion"] = "skipped — not yet synced from Moxfield"
            results.append(row)
            continue

        if config.notion_mcp_url:
            try:
                await update_deck_page(
                    config.notion_mcp_url,
                    deck_conf.notion_id,
                    stored["name"],
                    stored.get("title", ""),
                )
                row["notion"] = "updated"
            except Exception as e:
                row["notion"] = f"error: {e}"
        else:
            row["notion"] = "skipped — NOTION_MCP_URL not set"

        results.append(row)
    return results


async def list_decks(config: Config) -> list[dict]:
    """Return summary of all configured decks, including sync timestamps from MongoDB."""
    results = []
    for d in config.decks:
        stored = mongodb.get_deck(d.slug)
        results.append({
            "slug": d.slug,
            "name": d.name,
            "title": d.title,
            "colors": d.colors,
            "bracket": d.bracket,
            "notes": d.notes,
            "last_synced": stored.get("last_synced") if stored else None,
            "moxfield_updated_at": stored.get("moxfield_updated_at") if stored else None,
        })
    return results


async def get_deck(slug: str, config: Config) -> dict | None:
    """
    Retrieve a deck from MongoDB. Returns error dict if not yet synced.
    Includes full card list with Scryfall data.
    """
    deck_conf = config.decks_by_slug.get(slug)
    if not deck_conf:
        return None

    stored = mongodb.get_deck(slug)
    if not stored:
        return {
            "error": f"Deck '{slug}' not yet synced. Run sync_deck('{slug}') first.",
            "config": {
                "slug": deck_conf.slug,
                "name": deck_conf.name,
                "colors": deck_conf.colors,
                "bracket": deck_conf.bracket,
            },
        }
    return stored


def _update_decks_yaml(decks_path: str, slug: str, name: str, title: str) -> None:
    path = Path(decks_path)
    with open(path) as f:
        raw = yaml.safe_load(f)

    for deck in raw["decks"]:
        if deck["slug"] == slug:
            deck["name"] = name
            deck["title"] = title
            break

    with open(path, "w") as f:
        yaml.dump(raw, f, allow_unicode=True, sort_keys=False)


async def sync_deck(slug: str, config: Config, prefetched_data: dict | None = None) -> dict:
    """
    Fetch deck from Moxfield, enrich each card via Scryfall, store in MongoDB.
    Also updates decks.yaml and the Notion page with the current name/title from Moxfield.
    If prefetched_data is provided, skips the Moxfield fetch (used by the browser extension endpoint).
    Returns a summary of what was synced.
    """
    deck_conf = config.decks_by_slug.get(slug)
    if not deck_conf:
        return {"error": f"Unknown deck slug: '{slug}'"}

    deck_data = prefetched_data if prefetched_data is not None else await moxfield.fetch_deck(deck_conf.moxfield_id)

    moxfield_updated_at = deck_data.get("updatedAtUtc")
    if moxfield_updated_at:
        stored = mongodb.get_deck(slug)
        if stored and stored.get("moxfield_updated_at") == moxfield_updated_at:
            return {
                "skipped": slug,
                "reason": "already up to date",
                "moxfield_updated_at": moxfield_updated_at,
                "last_synced": stored.get("last_synced"),
            }

    mox_name, mox_title = moxfield.parse_deck_name(deck_data.get("name", deck_conf.name))
    commander_entries_raw, mainboard_entries_raw = moxfield.extract_card_list(deck_data)

    all_entries = commander_entries_raw + mainboard_entries_raw
    # Deduplicate by (scryfall_id or name) to avoid redundant lookups
    seen: set[str] = set()
    unique_entries: list[dict] = []
    for e in all_entries:
        key = e["scryfall_id"] or e["name"]
        if key not in seen:
            seen.add(key)
            unique_entries.append(e)

    enriched_cards: dict[str, dict] = {}  # keyed by name
    missing: list[str] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        for entry in unique_entries:
            name = entry["name"]

            # Always enrich from oracle data (has type_line, mana_cost, oracle_text).
            # Priority: oracle bulk by name → per-deck cache → live Scryfall API.
            # scryfall_id is stored separately for printing-specific queries (prices, border, etc.)
            card_data = get_bulk_card(name) or mongodb.get_cached_card(name)
            if card_data:
                enriched_cards[name] = card_data
                continue

            card_data = await scryfall.get_card_by_name(client, name)
            if card_data:
                mongodb.upsert_card_cache(name, card_data)
                enriched_cards[name] = card_data
            else:
                missing.append(name)

    def build_entry(e: dict) -> dict:
        result = {"name": e["name"], "quantity": e["quantity"]}
        if e["scryfall_id"]:
            result["scryfall_id"] = e["scryfall_id"]
        if e["name"] in enriched_cards:
            result["scryfall"] = enriched_cards[e["name"]]
        return result

    commander_entries = [build_entry(e) for e in commander_entries_raw]
    mainboard = [build_entry(e) for e in mainboard_entries_raw]

    mongodb.upsert_deck(slug, {
        "slug": slug,
        "name": mox_name,
        "title": mox_title,
        "moxfield_id": deck_conf.moxfield_id,
        "notion_id": deck_conf.notion_id,
        "colors": deck_conf.colors,
        "bracket": deck_conf.bracket,
        "notes": deck_conf.notes,
        "moxfield_updated_at": moxfield_updated_at,
        "commanders": commander_entries,
        "mainboard": mainboard,
    })

    update_results: dict = {}

    try:
        _update_decks_yaml(config.decks_path, slug, mox_name, mox_title)
        update_results["decks_yaml"] = "updated"
    except Exception as e:
        update_results["decks_yaml"] = f"error: {e}"

    if config.notion_mcp_url:
        try:
            await update_deck_page(config.notion_mcp_url, deck_conf.notion_id, mox_name, mox_title)
            update_results["notion"] = "updated"
        except Exception as e:
            update_results["notion"] = f"error: {e}"
    else:
        update_results["notion"] = "skipped — NOTION_MCP_URL not set"

    return {
        "synced": slug,
        "name": mox_name,
        "title": mox_title,
        "moxfield_updated_at": moxfield_updated_at,
        "commanders": [e["name"] for e in commander_entries_raw],
        "card_count": len(mainboard),
        "enriched": len(enriched_cards),
        "missing_from_scryfall": missing,
        "updates": update_results,
    }
