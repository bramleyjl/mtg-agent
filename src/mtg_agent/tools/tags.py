from mtg_agent.db import mongodb


def search_tags(query: str, limit: int = 25) -> list[dict]:
    """
    Search Scryfall Tagger's oracle tags by keyword (matches label or slug).
    Use this to discover a tag's exact slug before calling get_cards_by_tag() —
    there are ~4500 tags, too many to memorize. Trivia/flavor/reprint-cycle tags
    are excluded by default (see mtg_agent.tag_filters).
    """
    return mongodb.search_tags(query, limit=limit)


def get_cards_by_tag(tag: str, limit: int = 200) -> dict:
    """
    Return every card carrying a given Scryfall oracle tag (exact label or slug,
    case-insensitive), sorted by tag weight then name. Use search_tags() first if
    unsure of the exact slug.
    """
    return mongodb.get_cards_by_tag(tag, limit=limit)
