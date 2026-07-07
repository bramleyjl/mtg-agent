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

**Scope boundary:** `content_chunks` is only for unstructured prose queried by "what does this say about X" — not a catch-all for every non-Scryfall source. Decklists (personal or the future "other people's decklists" CW source) are structured data queried by field (cards, quantities, commander, curve) and get their own schema'd collections, same as `decks` today — they never go through the chunking pipeline. The one partial exception: free-text `notes` inside structured `game_history` records could eventually feed `content_chunks` if they get long enough to need semantic search, while the rest of that record stays structured. `player_preferences` (John's stated playstyle/deckbuilding opinions, captured in-session) is another deliberate exception: each entry is already atomic on write, so it skips the chunking pipeline entirely and gets its own collection with `deck_slug` scoping and `stated_at`-based recency tiebreaking — see `docs/data_sources_roadmap.md` for the full design rationale.

Search today is MongoDB `$text` keyword search (self-hosted Community edition doesn't support `$vectorSearch`, which is Atlas-only). This is scaffolding, not final: see `docs/data_sources_roadmap.md` for the planned migration to embedding-based semantic search once the primer/CW-article corpus grows enough to need it — the `content_chunks` schema is designed so adding an `embedding` field later is additive, not a rewrite.

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
- **Every `scripts/refresh_*.py` ingestion script must expose a reusable `refresh(force: bool = False) -> None` function** (not logic inlined in `main()`), so it can be called in-process — not just invoked via `python -m`. `main()` should be a thin CLI wrapper around it (parse args, call `refresh(force=...)`). This is what lets `tools/data_sources.py`'s `refresh_all_data_sources()` MCP tool run every source's refresh in one call without shelling out. If a script manages multiple independently-stale things (see `refresh_commander_spellbook.py`'s `refresh()` for combos + separate `refresh_templates()` for templates), expose each as its own `refresh`-style function and register both in `tools/data_sources.py`'s `_SOURCES` list.

## Server Setup (pangolin)

After deploying with `scripts/deploy_pangolin.sh`, do these one-time steps on the server:

**1. Create `.env`** at `/home/admin/Projects/mcps/mtg-agent/.env`:
```
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=mtg_agent
DECKS_CONFIG=/home/admin/Projects/mcps/mtg-agent/decks.yaml
NOTION_MCP_URL=http://localhost:8766/mcp
MCP_TRANSPORT=streamable-http
MCP_HOST=0.0.0.0
MCP_PORT=8765
```

**2. Initial Scryfall bulk data load** (one-time, takes a few minutes):
```bash
ssh pangolin 'cd /home/admin/Projects/mcps/mtg-agent && .venv/bin/python -m mtg_agent.scripts.refresh_scryfall_bulk'
```

**3. Cron jobs** — add to the `admin` user's crontab (`crontab -e` on pangolin). Five lines cover nine refresh scripts; each script still self-gates via `--if-stale` against its own staleness window, so a nightly trigger only does real work when something's actually due:

```
0 3 * * * cd /home/admin/Projects/mcps/mtg-agent && .venv/bin/python -m mtg_agent.scripts.refresh_scryfall_bulk --if-stale >> /tmp/scryfall_bulk_refresh.log 2>&1
0 4 * * * cd /home/admin/Projects/mcps/mtg-agent && .venv/bin/python -m mtg_agent.scripts.refresh_comprehensive_rules --if-stale >> /tmp/comprehensive_rules_refresh.log 2>&1 ; .venv/bin/python -m mtg_agent.scripts.refresh_commander_banlist --if-stale >> /tmp/commander_banlist_refresh.log 2>&1 ; .venv/bin/python -m mtg_agent.scripts.refresh_commander_brackets --if-stale >> /tmp/commander_brackets_refresh.log 2>&1 ; .venv/bin/python -m mtg_agent.scripts.refresh_commander_bracket_announcements --if-stale >> /tmp/commander_bracket_announcements_refresh.log 2>&1 ; .venv/bin/python -m mtg_agent.scripts.refresh_commander_banr_announcements --if-stale >> /tmp/commander_banr_announcements_refresh.log 2>&1
0 5 * * * cd /home/admin/Projects/mcps/mtg-agent && .venv/bin/python -m mtg_agent.scripts.refresh_deck_working_notes --if-stale >> /tmp/deck_working_notes_refresh.log 2>&1
0 9 * * * cd /home/admin/Projects/mcps/mtg-agent && .venv/bin/python -m mtg_agent.scripts.refresh_commander_spellbook --if-stale >> /tmp/commander_spellbook_refresh.log 2>&1
0 6 * * 0 cd /home/admin/Projects/mcps/mtg-agent && .venv/bin/python -m mtg_agent.scripts.refresh_edhrec --if-stale >> /tmp/edhrec_refresh.log 2>&1
```

**3am — `refresh_scryfall_bulk`** manages four Scryfall datasets. `oracle_cards`, `rulings`, and `oracle_tags` gate on a 7-day staleness window (`STALE_AFTER_DAYS` in the script) since card text/tags only change on set-release cadence. `default_cards` (which carries `prices`, used for deck price totals) has **no gate at all** — it always refreshes under `--if-stale`, since prices are guaranteed to differ every single day and a staleness check would never actually skip anything. Populates `scryfall_oracle`, `scryfall_bulk`, `scryfall_rulings`, `scryfall_oracle_tags`. Logs at `/tmp/scryfall_bulk_refresh.log`.

**4am — five WotC-sourced scripts, chained with `;`** (so one failing doesn't block the others), all gated on an 8-week (56 day) staleness window since official Commander-format content only changes on set-release/announcement cadence:
- `refresh_comprehensive_rules` — downloads the current Comprehensive Rules `.txt` (re-derives the dated download link from the rules landing page each run, since the filename changes every update), populates `rules_numbered`/`rules_glossary`.
- `refresh_commander_banlist` — scrapes `magic.wizards.com/en/banned-restricted-list`, populates `commander_banned_list` (named cards + blanket-ban categories like Conspiracy-type or ante cards). Reference/audit source — Scryfall's own `legalities.commander` already reflects these bans per card.
- `refresh_commander_brackets` — scrapes `magic.wizards.com/en/formats/commander`, populates `commander_brackets` (overview + 5 bracket definitions) and `commander_game_changers` (53 cards). This page is beta/actively revised by the Commander Format Panel, so it's the most likely of these five to need a manual out-of-cycle run.
- `refresh_commander_bracket_announcements` — auto-discovers announcement URLs each run via WotC's filtered article search (`?search=Commander%20Bracket`) and re-fetches all of them into `commander_bracket_announcements`.
- `refresh_commander_banr_announcements` — same auto-discovery pattern via `?search=Commander+Banned+and+Restricted`, populates `commander_banr_announcements` with WotC's stated *reasoning* per ban/unban. Only surfaces announcements from when WotC took over B&R from the Rules Committee (2024 onward) — intentional, not a gap.

Run any of the five without `--if-stale` for a manual out-of-cycle update (e.g. John usually hears about B&R changes same-day, well inside the 8-week window).

**5am — `refresh_deck_working_notes`** reconciles manual edits to a deck's Notion page body (the per-deck working-notes document — theme, strengths/weaknesses, restraints, current focus, recurring patterns, turns-to-win, similar decklists) into MongoDB's `working_notes` field on `decks`. This is the fallback path only: the primary path is the `update_deck_working_notes` MCP tool (`tools/decks.py`), which the agent calls directly — it writes to Notion and MongoDB in the same operation, so the two never drift on agent-driven updates. This script exists to catch the case where John hand-edits a deck's Notion page body himself, bypassing that tool. Staleness isn't a fixed time window like the other scripts — each deck's Notion `last_edited_time` is compared against its own `working_notes_synced_at` in MongoDB, and only pages edited more recently get their body re-pulled. `refresh()` is async (needs notion-mcp calls), unlike the other scripts in this list — `main()` wraps it in `asyncio.run()` for the cron/CLI entry point, and `tools/data_sources.py`'s `refresh_all_data_sources()` awaits it directly since that caller is already async.

**9am — `refresh_commander_spellbook`** manages two independently-staled things:
- **Combos** (`refresh()`) — staleness checked against the **remote** bulk file's `Last-Modified` header, not local data age, since new combos track card releases rather than a calendar. Downloads the full `variants.json` bulk file from `json.commanderspellbook.com` (~550MB), filters to `legalities.commander == true`, populates `commander_combos` (~95k variants).
- **Templates** (`refresh_templates()`) — some combo pieces are generic ("any creature with Persist or Undying") rather than a specific card; each of Commander Spellbook's 167 template categories is resolved to the concrete commander-legal oracle_ids satisfying it via Scryfall, stored in `commander_spellbook_templates`. Gated on a 7-day window, but incrementally: an already-resolved template only re-queries Scryfall for cards released since its last check (plus a 3-day overlap buffer) and unions the result — not a full re-resolve — so this stays fast on a weekly cadence even though the initial resolve of all 167 templates took ~15 minutes.

Both `commander_combos` and `commander_spellbook_templates` feed `find_combos_in_deck(slug)`, an MCP tool that cross-references a deck's current cards against both exact-card and generic-template combo pieces. Run without `--if-stale` for a manual update.

**Sunday 6am — `refresh_edhrec`** ingests EDHREC's unofficial JSON API (`json.edhrec.com/pages/commanders/<slug>.json`, no auth) for John's own 13 commanders only, re-derived from the `decks` collection each run rather than hardcoded. Weekly cadence (community data, not card-release-driven) — staleness is checked per-commander against `edhrec_commander_meta`'s own `last_synced`, not a shared clock. Populates two collections, both keyed by `scope` (`default` / `bracket_2` / `bracket_3` / `bracket_4` / `tag:<slug>`): `card_usage_stats` (one row per commander+card+scope: synergy, num_decks, potential_decks, inclusion_pct) and `edhrec_commander_meta` (one row per commander+scope: total_decks, bracket_counts, tag_counts). B1/B5 are skipped — not brackets John plays; each bracket sub-page recomputes its own denominator/rankings from scratch, it's not a filtered slice of the default page. Card names are resolved against `scryfall_oracle`; double-faced/split cards (EDHREC lists front-face name only, e.g. `"Birgi, God of Storytelling"`) are resolved via a `"^Front // "` prefix-match fallback. Tag/theme scopes (e.g. `tag:combo`) are **not** pre-fetched — they're created on demand via the `get_edhrec_tag_data(slug, tag)` MCP tool, and once created, `refresh()` automatically picks up and refreshes any existing `tag:*` scope going forward (no separate tracked-tags list). `compare_deck_to_edhrec(slug, scope="default")` is the gap-analysis MCP tool: which of a deck's cards are EDHREC staples for that commander+scope, and which popular cards it's missing. See `docs/data_sources_roadmap.md` for the full schema and confirmed API-shape notes (bracket-slug-to-WotC-title mapping, ad-hoc filter inaccessibility, `/combos/` page being Commander Spellbook data re-served).

**On-demand refresh:** `refresh_all_data_sources(force: bool = False)` is an MCP tool that runs every source above in one call — `force=False` mirrors the cron (only refreshes what's actually stale), `force=True` refreshes everything unconditionally (budget a few minutes; the 167 Spellbook templates alone take ~1-2 sec each even on the incremental path, and EDHREC's 13 commanders x 4+ scopes each add up too). Use this at the start of a session when you want guaranteed-fresh data without waiting for the next cron run.
