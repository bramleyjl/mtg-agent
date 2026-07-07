import re
from datetime import datetime, timezone

from mtg_agent.chunking import chunk_text
from mtg_agent.db import mongodb

CATEGORY = "player_theory"


def _slugify(title: str) -> str:
    slug = title.lower().strip()
    slug = re.sub(r"[,'\.]", "", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug


async def record_player_theory(title: str, text: str) -> dict:
    """
    Record a long-form player-theory essay (e.g. bracket-system philosophy,
    local meta reality) built through conversation. Re-recording under the
    same title replaces the prior version — delete-then-reinsert, same
    semantics as a revised WotC announcement.
    """
    slug = _slugify(title)
    source_url = f"internal://player_theory/{slug}"
    now = datetime.now(timezone.utc)
    chunks = [
        {
            "source_url": source_url,
            "title": title,
            "published_date": now,
            "category": CATEGORY,
            "chunk_index": i,
            "text": chunk,
        }
        for i, chunk in enumerate(chunk_text(text))
    ]
    mongodb.replace_content_chunks(source_url, chunks)
    return {"source_url": source_url, "chunk_count": len(chunks), "recorded_at": now.isoformat()}


async def search_player_theory(query: str) -> list[dict]:
    """Keyword search over recorded player-theory essays."""
    return mongodb.search_content_chunks(query, category=CATEGORY)
