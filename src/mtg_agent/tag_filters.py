"""
Filters Scryfall Tagger's oracle tags (mtg_agent.db.mongodb: scryfall_oracle_tags)
down to gameplay-relevant labels, excluding trivia/flavor/reprint-cycle tags that
carry no deckbuilding signal (e.g. "alliteration", "cycle-zen-fetchland").

This denylist was reviewed 2026-08-04 against every tag slug actually attached
to a card across all 13 of John's decks (927 distinct slugs — not the full
~4500 in the collection, which includes many tags no deck John plays will ever
surface). Verified against each tag's Scryfall description before excluding,
not just its label text — several superficially joke-sounding labels
("warlord", "moxen", "uninspired", "karnstructs") turned out to name genuine
functional card-design categories and were kept. Expect to extend both sets
as more decks (or the untouched remainder of the ~4500) surface tags that
should (or shouldn't) have been filtered.
"""

EXCLUDED_PREFIXES = (
    "cycle-",
    "supercycle-",
    "type-errata",
    "unique-",  # factoid tags ("only card with this p/t"), not deckbuilding-actionable
    "dnd",  # catches bare "dnd" plus dnd-item/mechanic/book/character/spell/monster
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
    "shares-name-with-a-mechanic",
    "notorious-templating",
    "rules-nightmare",
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
    "bible-reference",
    # storyline/marketing-tie-in trivia (*-storyline-in-cards family + one-offs)
    "usg-storyline-in-cards",
    "tmp-storyline-in-cards",
    "sth-storyline-in-cards",
    "exo-storyline-in-cards",
    "wth-storyline-in-cards",
    "marvel-storyline-name",
    "fulfilled-futureshift",
    "great-designer-search-3",
    "commander-set-booster-cards",
    "preexisting-dnd-background",
    # aesthetic/naming trivia with no rules or deckbuilding meaning
    "aesthetic-counter",
    "meme",
    "fun-ruling",
    "rhyming-name",
    "deprecated-legend-type",
    "mob-name",
    "sports-name",
    "portmanteau",
    "anagram",
    "mathy-name",
    "personal-text",
    "40k-model",
    "sword-of-x-and-y",
    "inscryption-achievement",
    "wannabe-dark-confidant",  # flavor-named riff on Dark Confidant; the real functional tag is "life-for-cards"
    "cr-107-3f-x-card",  # rules-citation trivia, distinct from unique-cr-reference (now covered by unique- prefix)
}


def is_gameplay_tag(slug: str) -> bool:
    """True if a tag slug is deckbuilding-relevant (not trivia/flavor/reprint-cycle noise)."""
    if slug in EXCLUDED_SLUGS:
        return False
    return not slug.startswith(EXCLUDED_PREFIXES)
