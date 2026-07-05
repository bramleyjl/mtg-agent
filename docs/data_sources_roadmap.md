# Data Sources Roadmap

Tracks build-out of the agent's data layer, split into two categories:

- **HD (Hard Data)** — authoritative, structured, or official sources: card data, rules, format legality, personal decklists/match history. Ground truth, no interpretation involved.
- **CW (Community Wisdom)** — aggregated opinion/experience from the player base: EDHREC recs, deckbuilding articles, forum/Discord discussion. Useful signal, not ground truth, and gets ingested via the RAG chunking pipeline (see `CLAUDE.md` § RAG / Content Chunking Framework) rather than structured collections.

Status legend: ✅ Live · 🔧 Partial · 📋 Planned

## Hard Data (HD)

| Source | Status | Collection(s) | Notes |
|---|---|---|---|
| Scryfall bulk card data | ✅ Live | `scryfall_bulk` | `refresh_scryfall_bulk.py`, nightly cron w/ `--if-stale` (7-day gate) |
| Scryfall oracle cards | ✅ Live | `scryfall_oracle` | Canonical one-row-per-oracle-id card text/identity |
| Scryfall rulings | ✅ Live | `scryfall_rulings` | Keyed by `oracle_id` |
| Scryfall/EDHREC oracle tags | ✅ Live | `scryfall_oracle_tags` | Functional tags per card, sourced via Scryfall's tagger data |
| Personal decklists (Moxfield sync) | ✅ Live | `decks` | `clients/moxfield.py` fetch + `compute_deck_stats`; synced via Notion page + `session_sync.py` |
| Match/game history | ✅ Live | `game_history` | Synced from Notion via `sync_game_history` MCP tool; enemy commander stats aggregation in `mongodb.py` |
| Comprehensive Rules | ✅ Live | `rules_numbered`, `rules_glossary` | `refresh_comprehensive_rules.py`, daily cron, 8-week staleness gate |
| Commander banned list | ✅ Live | `commander_banned_list` | `refresh_commander_banlist.py`, daily cron, 8-week gate |
| Commander Brackets + Game Changers | ✅ Live | `commander_brackets`, `commander_game_changers` | `refresh_commander_brackets.py`, daily cron, 8-week gate |
| Commander Bracket announcements | ✅ Live | `commander_bracket_announcements` | `refresh_commander_bracket_announcements.py`, auto-discovers URLs, daily cron |
| Commander B&R announcements | ✅ Live | `commander_banr_announcements` | `refresh_commander_banr_announcements.py`, auto-discovers URLs, daily cron. Only covers 2024+ (WotC-era B&R) |
| Draw-probability / hypergeometric calculator | ✅ Live | n/a (pure compute) | `tools/probability.py` — not a data source, but a derived-data tool over `decks` |
| Preference modeling | 📋 Planned | n/a | Phase 3 in `CLAUDE.md` — derive player preferences from `game_history` over time |
| Other people's decklists (as HD, e.g. tournament/meta decklists) | 📋 Planned | new collection, TBD | Referenced in `CLAUDE.md` chunking scope-boundary note as a possible future structured collection distinct from the CW article corpus |

## Community Wisdom (CW)

| Source | Status | Collection(s) | Notes |
|---|---|---|---|
| WotC official announcements | ✅ Live (arguably HD, not CW) | `content_chunks` (category-tagged) | Currently the only populated source in the shared prose-chunking pipeline; listed here because it validated the CW ingestion path even though its content is official, not community |
| EDHREC recommendations/synergy data | 📋 Planned | TBD | Unofficial API exists; no ingestion code yet. Would likely be structured (per-card recs) rather than prose-chunked |
| Commander's Herald articles | 📋 Planned | `content_chunks` (new `category`) | No fetch/parse client yet |
| r/EDH (Reddit) discussion | 📋 Planned | `content_chunks` (new `category`) | No fetch/parse client yet; would need a discussion-thread-specific chunking strategy (chunking.py currently only handles long-form articles) |
| Discord discussion | 📋 Planned | `content_chunks` (new `category`) | Mentioned as a future prose source in `chunking.py` docstring; no client |
| Embedding-based semantic search | 📋 Planned | `content_chunks.embedding` (additive field) | Referenced in `CLAUDE.md` as the planned upgrade once the CW article corpus is large enough to need it — MongoDB Community edition doesn't support `$vectorSearch` (Atlas-only), so current search is `$text` keyword search throughout |

## Open questions for the next planning pass

- Where's the line between "HD: other people's decklists" and "CW: EDHREC synergy data" when EDHREC recs are themselves derived from aggregated decklists?
- Priority order for the four planned CW sources (EDHREC / Commander's Herald / Reddit / Discord) — which unblocks the most useful agent behavior first?
- Whether Reddit/Discord ingestion is even in scope given their discussion-thread (not article) shape — may need a 4th chunking tier.
