# MTG Deckbuilding Agent

An AI-powered deckbuilding assistant for Magic: The Gathering, focused on the Commander (EDH) format. The agent is designed to learn John's preferences as a player over time and provide personalized deck advice.

## Project Goals

- Answer questions about existing decklists (card choices, synergies, weaknesses)
- Suggest changes to decks for specific reasons: power adjustment, problem-solving, theme shifts
- Grow smarter over time as more personal match history and preference data is added
- Eventually support natural conversation about deck strategy and theory

## Architecture Overview

**Data layers (in priority order):**

1. **Scryfall API** — canonical card data source (Oracle text, mana cost, color identity, Commander legality, types). Free and comprehensive. This is the ground truth for all card information.
2. **Personal decklists** — John's actual Commander decks, stored as structured data. The agent's primary working material.
3. **Match history** — game outcomes and notes, used to inform preference modeling over time.
4. **Community knowledge (RAG)** — articles and forum discussions from EDHREC, Commander's Herald, r/EDH, etc., embedded in a vector store and retrieved semantically.

**Key integrations:**
- MongoDB (already connected via MCP) — primary store for decklists, match history, preferences, and vector embeddings
- Scryfall API — card lookup and search
- notion-mcp — handles all Notion interactions (deck page updates, task management); mtg-agent calls it directly over HTTP during sync operations so Notion auth lives only in notion-mcp

## Commander Format Rules

- 100-card singleton (exactly 1 copy of each card except basic lands)
- 1 designated commander card (legendary creature or planeswalker with commander text)
- All cards in the deck must match the commander's color identity
- Commander lives in the command zone and can be recast for an increasing cost
- Multiplayer format (typically 4 players), starting life total 40
- Banned list maintained separately from other formats

## Player Context

John's preferences, play style, and deck history are tracked in the memory system and updated over time. See memory files for current state.

## Development Phases

**Phase 1 (MVP):** Claude can answer questions about decklists using Scryfall card data as context.

**Phase 2:** Personal decklist storage + retrieval; diff-based change suggestions.

**Phase 3:** Match history integration; preference modeling starts.

**Phase 4:** Community knowledge RAG pipeline (articles, EDHREC data).

## Setup Notes

- Scryfall API is free with no auth required; be respectful of rate limits (10 req/sec max, prefer bulk data downloads for large queries)
- EDHREC has an unofficial API useful for commander-specific recommendations
- Decklists can be imported from Moxfield/Archidekt export formats (plain text: `1 Card Name`)

## Server Setup (pangolin)

After deploying with `scripts/deploy_pangolin.sh`, do these one-time steps on the server:

**1. Create `.env`** at `/home/admin/mtg_agent/.env`:
```
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=mtg_agent
DECKS_CONFIG=/home/admin/mtg_agent/decks.yaml
NOTION_MCP_URL=http://localhost:8766/mcp
MCP_TRANSPORT=streamable-http
MCP_HOST=0.0.0.0
MCP_PORT=8765
```

**2. Initial Scryfall bulk data load** (one-time, takes a few minutes):
```bash
ssh pangolin 'cd /home/admin/mtg_agent && .venv/bin/python -m mtg_agent.scripts.refresh_scryfall_bulk'
```

**3. Daily refresh cron job** — add to the `admin` user's crontab (`crontab -e` on pangolin):
```
0 3 * * * cd /home/admin/mtg_agent && .venv/bin/python -m mtg_agent.scripts.refresh_scryfall_bulk --if-stale >> /tmp/scryfall_bulk_refresh.log 2>&1
```
This runs nightly at 3am and skips if data is less than 7 days old. Check logs at `/tmp/scryfall_bulk_refresh.log`.
