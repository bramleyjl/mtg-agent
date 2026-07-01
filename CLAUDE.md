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

## RAG / Content Chunking Framework

Three-tier default chunking strategy, chosen per source category rather than one universal approach (`src/mtg_agent/chunking.py`):

1. **Structured documents** (Comprehensive Rules `rules_numbered`/`rules_glossary`) — already atomic at ingestion via the source's own numbering (e.g. rule `903.5c`). No re-chunking; just full-text-indexed in place. Search: `search_rules()`/`search_glossary()` in `db/mongodb.py`.
2. **Articles** (WotC announcements now; future primers/Discord/Reddit posts) — long-form prose with no inherent addressable structure. Paragraph-chunked via `chunk_text()` (merges short paragraphs, splits oversized ones on sentence boundaries) into the shared `content_chunks` collection, tagged with a `category` field for filtering. Search: `search_content_chunks()`.
3. **Reference lists** (banned list, Game Changers, brackets overview) — small enough (dozens of short entries) that whole-list retrieval already works; no chunking needed.

**Scope boundary:** `content_chunks` is only for unstructured prose queried by "what does this say about X" — not a catch-all for every non-Scryfall source. Decklists (personal or the future "other people's decklists" CW source) are structured data queried by field (cards, quantities, commander, curve) and get their own schema'd collections, same as `decks` today — they never go through the chunking pipeline. The one partial exception: free-text `notes` inside structured `game_history` records could eventually feed `content_chunks` if they get long enough to need semantic search, while the rest of that record stays structured.

Search today is MongoDB `$text` keyword search (self-hosted Community edition doesn't support `$vectorSearch`, which is Atlas-only). This is scaffolding, not final: see the RAG roadmap memory for the planned migration to embedding-based semantic search once the primer/CW-article corpus grows enough to need it — the `content_chunks` schema is designed so adding an `embedding` field later is additive, not a rewrite.

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

**4. Comprehensive Rules refresh cron job** — same crontab, runs daily but the `--if-stale` flag internally gates on an 8-week (56 day) staleness window since the rules only change on set-release cadence:
```
0 4 * * * cd /home/admin/mtg_agent && .venv/bin/python -m mtg_agent.scripts.refresh_comprehensive_rules --if-stale >> /tmp/comprehensive_rules_refresh.log 2>&1
```
Downloads the current Comprehensive Rules `.txt` from wizards.com (re-derives the dated download link from the rules landing page each run, since the filename changes every update) and populates `rules_numbered` and `rules_glossary` in MongoDB. Run without `--if-stale` for a manual out-of-cycle update (e.g. after hearing about a rules change before the 8-week window is up).

**5. Commander banned list refresh cron job** — same crontab, same 8-week gate:
```
0 5 * * * cd /home/admin/mtg_agent && .venv/bin/python -m mtg_agent.scripts.refresh_commander_banlist --if-stale >> /tmp/commander_banlist_refresh.log 2>&1
```
Scrapes `magic.wizards.com/en/banned-restricted-list` and populates `commander_banned_list` (individually named banned cards + blanket-ban categories like Conspiracy-type or ante cards). This is a reference/audit source — Scryfall's own `legalities.commander` field already reflects these bans per card — so it exists for the authoritative list text itself, including the blanket categories that aren't individual card names. Run without `--if-stale` for a manual update.

**6. Commander Brackets / Game Changers refresh cron job** — same crontab, same 8-week gate:
```
0 6 * * * cd /home/admin/mtg_agent && .venv/bin/python -m mtg_agent.scripts.refresh_commander_brackets --if-stale >> /tmp/commander_brackets_refresh.log 2>&1
```
Scrapes `magic.wizards.com/en/formats/commander` (both live in the same page's embedded data blob) and populates `commander_brackets` (overview + 5 bracket definitions with full prose) and `commander_game_changers` (53 cards, keyed by name with color category). Note: this page is beta/actively revised by the Commander Format Panel, so it's the most likely of the three official sources to need a manual out-of-cycle run. Run without `--if-stale` for a manual update.

**7. Commander Bracket announcements refresh cron job** — same crontab, same 8-week gate:
```
0 7 * * * cd /home/admin/mtg_agent && .venv/bin/python -m mtg_agent.scripts.refresh_commander_bracket_announcements --if-stale >> /tmp/commander_bracket_announcements_refresh.log 2>&1
```
Auto-discovers announcement URLs each run from WotC's own filtered article search (`magic.wizards.com/en/news/announcements?search=Commander%20Bracket`, confirmed server-side filtered) and re-fetches all of them into `commander_bracket_announcements` — cheap since there are only a handful. Unlike the initial hand-maintained-URL-list approach, this now genuinely needs periodic re-checking (to catch newly published announcements), even though each individual article's own content is frozen once live. Run without `--if-stale` for a manual update.

**8. Commander Banned & Restricted announcements refresh cron job** — same crontab, same 8-week gate, same auto-discovery pattern:
```
0 8 * * * cd /home/admin/mtg_agent && .venv/bin/python -m mtg_agent.scripts.refresh_commander_banr_announcements --if-stale >> /tmp/commander_banr_announcements_refresh.log 2>&1
```
Auto-discovers via `magic.wizards.com/en/news/announcements?search=Commander+Banned+and+Restricted` and populates `commander_banr_announcements`. Unlike the plain banned-list scrape (step 6), these carry WotC's stated *reasoning* for each ban/unban and broader commentary on card classes or format direction. Only surfaces announcements from when WotC took over B&R from the Rules Committee (2024 onward) — intentional, not a gap. Run without `--if-stale` for a manual update; John usually hears about B&R changes same-day.
