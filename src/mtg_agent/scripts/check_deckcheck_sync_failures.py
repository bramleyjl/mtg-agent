"""
Check for unacknowledged DeckCheck AI-analysis sync failures (see
tools/decks.py's sync_deckcheck_analysis) and surface them as hook output for
a Claude Code SessionStart hook (.claude/settings.json in this repo) — a
commander-name match miss there is logged instead of raised, so this is the
only place that miss becomes visible.

Prints Claude Code hookSpecificOutput JSON with additionalContext when there
are unacknowledged failures; prints nothing (exit 0) otherwise. Connects
directly via pymongo with a short timeout rather than going through
db/mongodb.py's init_db() (which runs the full _ensure_indexes() pass and has
~30s connection timeouts) — a SessionStart hook needs to be fast and fail
silently if Mongo isn't reachable from wherever `claude` is running, not add
latency or noise to every session start.

Run: python -m mtg_agent.scripts.check_deckcheck_sync_failures
"""

import json
import os

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError


def main() -> None:
    load_dotenv()
    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGODB_DB", "mtg_agent")

    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=2000, connectTimeoutMS=2000)
        failures = list(client[db_name]["deckcheck_sync_failures"].find({"acknowledged": False}, {"_id": 0}))
    except PyMongoError:
        return

    if not failures:
        return

    lines = [
        f"- {f['logged_at']}: commanders={f.get('commanders')} deckview_id={f.get('deckview_id')} ({f.get('reason')})"
        for f in failures
    ]
    context = (
        f"{len(failures)} DeckCheck analysis sync(s) failed to match a deck "
        "(logged by sync_deckcheck_analysis in tools/decks.py, likely a commander "
        "not yet in decks.yaml, or a name-matching mismatch):\n" + "\n".join(lines)
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))


if __name__ == "__main__":
    main()
