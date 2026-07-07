from datetime import datetime, timezone

from mtg_agent.db import mongodb


async def record_player_preference(
    text: str,
    deck_slug: str | None = None,
    topic_tags: list[str] | None = None,
    session_context: str | None = None,
) -> dict:
    """
    Record one atomic player-stated preference or playstyle opinion, surfaced
    organically in conversation (not a formal edit command — see
    update_deck_working_notes for that). Append-only; no update/dedup on write.
    """
    doc = {
        "text": text,
        "deck_slug": deck_slug,
        "topic_tags": topic_tags or [],
        "session_context": session_context,
        "stated_at": datetime.now(timezone.utc),
    }
    preference_id = mongodb.insert_player_preference(doc)
    return {"id": preference_id, "stated_at": doc["stated_at"].isoformat()}


async def search_player_preferences(query: str, deck_slug: str | None = None) -> list[dict]:
    """Keyword search over recorded player preferences, optionally scoped to one deck."""
    return mongodb.search_player_preferences(query, deck_slug=deck_slug)
