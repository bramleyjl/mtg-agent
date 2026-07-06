from mtg_agent.config import Config
from mtg_agent.db import mongodb


def _deck_oracle_ids(deck: dict) -> tuple[set[str], set[str], dict[str, str]]:
    """Return (commander_ids, all_ids, oracle_id -> card_name) for a stored deck doc."""
    commanders = deck.get("commanders", [])
    mainboard = deck.get("mainboard", [])
    commander_ids = {c["scryfall"]["oracle_id"] for c in commanders if c.get("scryfall", {}).get("oracle_id")}
    all_ids = commander_ids | {c["scryfall"]["oracle_id"] for c in mainboard if c.get("scryfall", {}).get("oracle_id")}
    name_by_id = {
        c["scryfall"]["oracle_id"]: c["name"]
        for c in commanders + mainboard
        if c.get("scryfall", {}).get("oracle_id")
    }
    return commander_ids, all_ids, name_by_id


async def find_combos_in_deck(slug: str, config: Config) -> dict:
    """
    Cross-reference a deck's current card list against ingested Commander Spellbook
    combo data (see mtg_agent.scripts.refresh_commander_spellbook).

    A combo counts as "found" only if every specific card it needs (`uses`) is in
    the deck AND every generic requirement (`requires`, e.g. "any creature with
    Persist or Undying") is satisfied by at least one card the deck actually runs
    — resolved via commander_spellbook_templates, not just checked by name.

    Note: a piece marked `must_be_commander` only needs to be present in the deck
    (mainboard or commander slot) to count as "found" — it is NOT excluded if the
    card is in the 99 rather than actually the deck's commander. Check each
    combo's `commander_zone_violations` field before assuming it's truly castable
    as described; a non-null value means the combo won't function as-is because
    that piece isn't in the command zone.
    """
    deck_conf = config.decks_by_slug.get(slug)
    if not deck_conf:
        return {"error": f"Unknown deck slug: '{slug}'"}

    deck = mongodb.get_deck(slug)
    if not deck:
        return {"error": f"Deck '{slug}' not yet synced. Run sync_deck('{slug}') first."}

    commander_ids, all_ids, name_by_id = _deck_oracle_ids(deck)
    if not all_ids:
        return {"slug": slug, "combos": []}

    db = mongodb.get_db()
    templates = {t["template_id"]: set(t["oracle_ids"]) for t in db["commander_spellbook_templates"].find()}

    results = []
    for combo in db["commander_combos"].find({"uses.oracle_id": {"$in": list(all_ids)}}):
        use_ids = [u.get("oracle_id") for u in combo.get("uses", [])]
        if not use_ids or not all(oid in all_ids for oid in use_ids):
            continue

        satisfied_requires = []
        fully_satisfied = True
        for req in combo.get("requires", []):
            candidates = [oid for oid in all_ids if oid in templates.get(req["template_id"], set())]
            if not candidates:
                fully_satisfied = False
                break
            satisfied_requires.append({
                "template_name": req["template_name"],
                "satisfied_by": [name_by_id.get(oid, oid) for oid in candidates],
            })
        if not fully_satisfied:
            continue

        commander_zone_violations = [
            u["name"] for u in combo["uses"]
            if u.get("must_be_commander") and u["oracle_id"] not in commander_ids
        ]

        results.append({
            "variant_id": combo["variant_id"],
            "uses": [u["name"] for u in combo["uses"]],
            "requires": satisfied_requires,
            "produces": [p.get("feature_name") for p in combo.get("produces", [])],
            "description": combo.get("description"),
            "popularity": combo.get("popularity"),
            "commander_zone_violations": commander_zone_violations or None,
        })

    results.sort(key=lambda r: -(r["popularity"] or 0))
    return {"slug": slug, "combo_count": len(results), "combos": results}
