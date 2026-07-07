"""
Client for EDHREC's unofficial JSON API (no auth, no official docs).

Slug derivation: lowercase, strip commas/apostrophes/periods, spaces -> hyphens
(confirmed against 5 real commanders including hyphenated/split names — see
docs/data_sources_roadmap.md for the verification notes).

Page shapes, both keyed the same way (13 disjoint card-list categories, each
card carrying name/synergy/num_decks/potential_decks):
  - default:  GET json.edhrec.com/pages/commanders/<slug>.json
  - bracket:  GET json.edhrec.com/pages/commanders/<slug>/<bracket-slug>.json
  - tag:      GET json.edhrec.com/pages/commanders/<slug>/<tag-slug>.json

EDHREC's own per-card `id` is NOT a Scryfall UUID — cards must be resolved by
name against scryfall_oracle (see refresh_edhrec.py).
"""

import re

import httpx

BASE_URL = "https://json.edhrec.com/pages/commanders"

# WotC's own bracket terminology, not "bracket-N" — see docs/data_sources_roadmap.md.
BRACKET_SLUGS = {
    2: "core",
    3: "upgraded",
    4: "optimized",
}

_STRIP_CHARS_RE = re.compile(r"[,'.]")
_SPACE_RE = re.compile(r"\s+")


def commander_slug(name: str) -> str:
    slug = _STRIP_CHARS_RE.sub("", name.lower())
    slug = _SPACE_RE.sub("-", slug.strip())
    return slug


def fetch_commander_page(slug: str, sub_page: str | None = None) -> dict | None:
    """
    Fetch a commander's default, bracket, or tag JSON page. Returns None if the
    page doesn't exist (e.g. an invalid tag slug, or a commander EDHREC has no
    data for) — confirmed a missing page 404s for the top-level commander page
    but 403s for a missing sub-page (S3/CloudFront access-denied on a missing
    key, not a real auth failure), so both are treated as "not found" here.
    Raises on any other HTTP error.
    """
    url = f"{BASE_URL}/{slug}.json" if sub_page is None else f"{BASE_URL}/{slug}/{sub_page}.json"
    resp = httpx.get(url, timeout=15.0, follow_redirects=True)
    if resp.status_code in (404, 403):
        return None
    resp.raise_for_status()
    return resp.json()


def parse_card_lists(page: dict) -> list[dict]:
    """
    Flatten a commander page's cardlists into (category, name, synergy, num_decks,
    potential_decks) rows. Categories are confirmed disjoint (no card appears in
    more than one), so no merge/precedence logic is needed.
    """
    cardlists = page.get("container", {}).get("json_dict", {}).get("cardlists", [])
    rows = []
    for cardlist in cardlists:
        category = cardlist.get("tag") or cardlist.get("header")
        for card in cardlist.get("cardviews", []):
            rows.append({
                "category": category,
                "name": card.get("name"),
                "synergy": card.get("synergy"),
                "num_decks": card.get("num_decks"),
                "potential_decks": card.get("potential_decks"),
            })
    return rows


def parse_meta(page: dict) -> dict:
    """
    Extract commander-level aggregate fields. total_decks/bracket_counts/tag_counts
    are top-level page fields (not nested under container.json_dict) — confirmed via
    live fetch: bracket_counts is a bracket-number -> deck-count dict (e.g. {"3": 1815}
    on the default page, collapsing to just its own bracket, e.g. {"3": 1815}, on a
    bracket sub-page), tag_counts is a tag-name -> deck-count dict.
    """
    card = page.get("container", {}).get("json_dict", {}).get("card", {})
    return {
        "total_decks": card.get("num_decks"),
        "bracket_counts": page.get("bracket_counts"),
        "tag_counts": page.get("tag_counts"),
    }
