"""
Session-start sync: push each deck's current name/title from MongoDB to Notion
and print a staleness report.

Run: python -m mtg_agent.scripts.session_sync
"""

import asyncio
import json
import sys

from mtg_agent.config import load_config
from mtg_agent.db.mongodb import init_db
from mtg_agent.tools.decks import session_sync


async def main() -> None:
    config = load_config()
    init_db(config.mongodb_uri, config.mongodb_db)
    results = await session_sync(config)
    print(json.dumps(results, indent=2, default=str))

    stale = [r for r in results if not r.get("moxfield_updated_at")]
    if stale:
        slugs = ", ".join(r["slug"] for r in stale)
        print(f"\nSTALE (never synced from Moxfield): {slugs}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())


def entry_point() -> None:
    asyncio.run(main())
