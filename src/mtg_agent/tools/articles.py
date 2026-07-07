from datetime import datetime, timezone

from mtg_agent.chunking import chunk_text
from mtg_agent.db import mongodb

VALID_CATEGORIES = {"primer", "strategy_article"}


async def record_strategy_article(
    url: str,
    title: str,
    text: str,
    category: str = "strategy_article",
    commander_names: list[str] | None = None,
    topic_tags: list[str] | None = None,
    published_date: str | None = None,
) -> dict:
    """
    Record a long-form external article (a commander-specific primer or a general
    strategy piece) fetched and cleaned by the agent itself (e.g. via WebFetch) — no
    per-site scraper needed, unlike the WotC announcement pipeline. Ingestion is a
    conversation: the agent fetches the article, and title/commander_names/topic_tags
    get worked out with John rather than parsed automatically.

    commander_names is citation metadata only — "this concrete decklist demonstrates
    the article's ideas" — NOT a retrieval filter. A primer's generalizable theory
    (e.g. a Wilson/Noble Heritage primer's "race-math over engine-building"
    philosophy) often applies to mechanically unrelated decks (e.g. Rem Karolus).
    topic_tags is the actual cross-archetype connective tissue for retrieval —
    free-form theory/concept tags, not tied to any one commander.

    category is bookkeeping only (primer vs. strategy_article), same resolution as
    content_type in the roadmap — it does not gate search.

    Re-recording the same url replaces its prior chunks (delete-then-reinsert, same
    semantics as record_player_theory/chunk_announcement).
    """
    if category not in VALID_CATEGORIES:
        return {"error": f"category must be one of {sorted(VALID_CATEGORIES)}"}

    now = datetime.now(timezone.utc)
    chunks = [
        {
            "source_url": url,
            "title": title,
            "published_date": published_date or now.isoformat(),
            "category": category,
            "commander_names": commander_names or None,
            "topic_tags": topic_tags or None,
            "chunk_index": i,
            "text": chunk,
        }
        for i, chunk in enumerate(chunk_text(text))
    ]
    mongodb.replace_content_chunks(url, chunks)
    return {
        "source_url": url,
        "category": category,
        "chunk_count": len(chunks),
        "commander_names": commander_names,
        "topic_tags": topic_tags,
        "recorded_at": now.isoformat(),
    }


async def search_strategy_articles(
    query: str, category: str | None = None, topic_tags: list[str] | None = None
) -> list[dict]:
    """Keyword search over recorded primers/strategy articles, optionally scoped by category and/or topic_tags."""
    return mongodb.search_content_chunks(query, category=category, topic_tags=topic_tags)
