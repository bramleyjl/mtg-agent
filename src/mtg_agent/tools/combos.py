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


def _load_templates(db) -> dict[str, set[str]]:
    return {t["template_id"]: set(t["oracle_ids"]) for t in db["commander_spellbook_templates"].find()}


def _check_requires(
    combo: dict, all_ids: set[str], name_by_id: dict[str, str], templates: dict[str, set[str]]
) -> tuple[list[dict], bool]:
    """Returns (satisfied_requires, fully_satisfied) for a combo's generic `requires` pieces."""
    satisfied_requires = []
    for req in combo.get("requires", []):
        candidates = [oid for oid in all_ids if oid in templates.get(req["template_id"], set())]
        if not candidates:
            return satisfied_requires, False
        satisfied_requires.append({
            "template_name": req["template_name"],
            "satisfied_by": [name_by_id.get(oid, oid) for oid in candidates],
        })
    return satisfied_requires, True


async def find_combos_in_deck(slug: str, config: Config) -> dict:
    """
    Cross-reference a deck's current card list against ingested Commander Spellbook
    combo data (see mtg_agent.scripts.refresh_commander_spellbook). Only combos the
    deck already fully has are returned — use find_almost_combos() for combos it's
    close to completing but doesn't have every piece for yet.

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

    Returns combos sorted by popularity descending. `popularity_percentile` (0-100)
    gives that raw count context against the full ingested combo corpus.
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
    templates = _load_templates(db)

    results = []
    for combo in db["commander_combos"].find({"uses.oracle_id": {"$in": list(all_ids)}}):
        use_ids = [u.get("oracle_id") for u in combo.get("uses", [])]
        if not use_ids or not all(oid in all_ids for oid in use_ids):
            continue

        satisfied_requires, fully_satisfied = _check_requires(combo, all_ids, name_by_id, templates)
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
            "popularity_percentile": combo.get("popularity_percentile"),
            "commander_zone_violations": commander_zone_violations or None,
        })

    results.sort(key=lambda r: (-(r["popularity"] or 0)))
    return {"slug": slug, "combo_count": len(results), "combos": results}


async def find_almost_combos(slug: str, config: Config, max_missing: int = 1) -> dict:
    """
    Find combos this deck has at least one but not all pieces for — the companion
    to find_combos_in_deck() for "what should I add" rather than "what do I
    already have". Fully-owned combos are excluded here; see find_combos_in_deck().

    A combo qualifies only if its `requires` template pieces are already fully
    satisfiable by cards the deck runs (same rule as find_combos_in_deck()) and its
    color identity fits within the deck's own colors. max_missing caps how many
    `uses` pieces can be absent (default 1 — "one card away").

    Each result's missing_pieces flags commander_change_required on any piece that
    must be the commander — completing that piece means swapping commanders, a
    bigger ask than adding a card to the 99, so those combos sort after otherwise-
    equal ones that don't need it. commander_zone_violations covers the opposite
    case: an owned piece that's in the 99 instead of the command zone.

    Results are sorted by fewest missing pieces first, then by popularity descending.
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

    deck_colors = set(deck.get("colors") or [])

    db = mongodb.get_db()
    templates = _load_templates(db)

    results = []
    for combo in db["commander_combos"].find({"uses.oracle_id": {"$in": list(all_ids)}}):
        uses = combo.get("uses", [])
        if not uses:
            continue

        missing = [u for u in uses if u["oracle_id"] not in all_ids]
        if not missing or len(missing) > max_missing:
            continue

        if not set(combo.get("identity") or "") <= deck_colors:
            continue

        satisfied_requires, fully_satisfied = _check_requires(combo, all_ids, name_by_id, templates)
        if not fully_satisfied:
            continue

        owned = [u for u in uses if u["oracle_id"] not in {m["oracle_id"] for m in missing}]
        commander_zone_violations = [
            u["name"] for u in owned
            if u.get("must_be_commander") and u["oracle_id"] not in commander_ids
        ]
        missing_pieces = [
            {"name": u["name"], "must_be_commander": u.get("must_be_commander", False),
             "commander_change_required": u.get("must_be_commander", False)}
            for u in missing
        ]

        results.append({
            "variant_id": combo["variant_id"],
            "missing_pieces": missing_pieces,
            "owned_pieces": [u["name"] for u in owned],
            "requires": satisfied_requires,
            "produces": [p.get("feature_name") for p in combo.get("produces", [])],
            "description": combo.get("description"),
            "popularity": combo.get("popularity"),
            "popularity_percentile": combo.get("popularity_percentile"),
            "commander_zone_violations": commander_zone_violations or None,
        })

    results.sort(key=lambda r: (
        len(r["missing_pieces"]),
        any(m["commander_change_required"] for m in r["missing_pieces"]),
        -(r["popularity"] or 0),
    ))
    return {"slug": slug, "combo_count": len(results), "max_missing": max_missing, "combos": results}
