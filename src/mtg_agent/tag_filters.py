"""
Filters Scryfall Tagger's oracle tags (mtg_agent.db.mongodb: scryfall_oracle_tags)
down to gameplay-relevant labels, excluding trivia/flavor/reprint-cycle tags that
carry no deckbuilding signal (e.g. "alliteration", "cycle-zen-fetchland").

This denylist is a first pass based on tags observed so far, not an exhaustive
review of all ~4500 tags in the collection — expect to extend EXCLUDED_SLUGS as
more decks surface tags that should (or shouldn't) have been filtered.
"""

EXCLUDED_PREFIXES = (
    "cycle-",
    "supercycle-",
    "type-errata",
)

EXCLUDED_SLUGS = {
    "alliteration",
    "punny-name",
    "misnomer",
    "single-english-word-name",
    "three-letter-name",
    "real-life-animal-name",
    "real-life-plant-name",
    "eponymous",
    "namesake-spell",
    "invitational-card",
    "shares-name-with-a-set",
    "notorious-templating",
    "rules-nightmare",
    "usg-storyline-in-cards",
    "unique-type-line",
    "mixed-subtypes",
    "vanity-card",
    "virtual-vanilla",
    "virtual-french-vanilla",
    "cda-power",
    "cda-toughness",
    "maro-sorcerer",
    "quadratic",
    "exponential",
    "player-spotlight",
    "has-identical-token",
    "card-game-reference",
    "flavor-text-matters",
    "references-keyword",
    "flavor-matters",
    "flavors-of-vanilla",
    "unique-cr-reference",
    "bible-reference",
}


def is_gameplay_tag(slug: str) -> bool:
    """True if a tag slug is deckbuilding-relevant (not trivia/flavor/reprint-cycle noise)."""
    if slug in EXCLUDED_SLUGS:
        return False
    return not slug.startswith(EXCLUDED_PREFIXES)
