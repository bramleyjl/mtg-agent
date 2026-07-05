# Data Sources Roadmap

Tracks build-out of the agent's data layer, split into two categories:

- **HD (Hard Data)** — authoritative, structured, ground-truth sources: card data, rules, format legality, personal decklist/match stats. No interpretation involved.
- **CW (Community Wisdom)** — opinion, qualitative guidance, or soft signal that has to be interpreted: EDHREC recs, deckbuilding articles, forum/Discord discussion, John's own free-text notes and stated preferences. Gets ingested via the RAG chunking pipeline (see `CLAUDE.md` § RAG / Content Chunking Framework) rather than structured collections, where applicable.

Several sources are genuinely dual-natured — a structured/objective part (HD) alongside a qualitative/interpreted part (CW) — rather than cleanly one or the other.

Status legend: ✅ Live · 🔧 Partial · 📋 Planned

## Hard Data (HD)

| Source | Status | Collection(s) | Notes |
|---|---|---|---|
| Scryfall bulk card data | ✅ Live | `scryfall_bulk` | `refresh_scryfall_bulk.py`, nightly cron w/ `--if-stale` (7-day gate) |
| Scryfall oracle cards | ✅ Live | `scryfall_oracle` | Canonical one-row-per-oracle-id card text/identity |
| Scryfall rulings | ✅ Live | `scryfall_rulings` | Keyed by `oracle_id` |
| Scryfall/EDHREC oracle tags | ✅ Live (ingestion) / 📋 Planned (adoption analysis) | `scryfall_oracle_tags` | Ingestion of the tag data itself is done. Separate planned follow-on: John's own Moxfield decks only partially/inconsistently use tags — do a card-for-card comparison between his current tag usage and EDHREC's full tagging framework/style, to decide whether to wholesale-adopt EDHREC's tagging conventions on his own decks rather than keep a partial/ad-hoc scheme |
| Personal decklists (Moxfield sync) | ✅ Live | `decks` | `clients/moxfield.py` fetch + `compute_deck_stats`; synced via Notion page + `session_sync.py` |
| Comprehensive Rules | ✅ Live | `rules_numbered`, `rules_glossary` | `refresh_comprehensive_rules.py`, daily cron, 8-week staleness gate |
| Commander banned list | ✅ Live | `commander_banned_list` | `refresh_commander_banlist.py`, daily cron, 8-week gate |
| Draw-probability / hypergeometric calculators | ✅ Live | n/a (pure compute) | `tools/probability.py` — not a data source, but a derived-data tool over `decks`. All 4 standard calculator types now implemented: basic single-category, multivariate (multiple simultaneous category minimums), mulligan-adjusted (London mulligan sequence), and sources-needed (Frank Karsten-style inverse solve for color-source count) |

## Dual HD + CW

| Source | Status | Collection(s) | HD part | CW part |
|---|---|---|---|---|
| Match/game history | ✅ Live, 🔧 known gap | `game_history` | Wins/losses, structured outcome fields — feeds win-rate/enemy-commander stats | Free-text `notes` per game are a soft, subjective indicator of what happened/how it felt — candidate for the `content_chunks` semantic layer later per `CLAUDE.md`'s partial-exception note |

**Known gap: past commanders per deck.** `_sync_game_history`/`get_deck` in `tools/decks.py` determines a game's `won` value by matching the winner's commander name against `john_deck["commanders"]` — but that field only reflects the deck's **current** Moxfield commander(s). A deck like Atemsis that used to be built around a different commander (e.g. Eluge) has historical `game_history` records where the winner field is the old commander name — those records will silently mismatch against today's commander list and get miscounted in win-rate calculations.

Fix needs two parts:
1. **A new structured data category for past commanders**, most likely added to each deck's Notion page (Notion is the canonical structured-data source per `CLAUDE.md`, synced into MongoDB `decks` the same way `commanders` is today) — e.g. a `past_commanders` list, without needing precise date ranges, just the full historical set of commander names this deck slug has ever been played under.
2. **Win-rate/`won` logic update** in `tools/decks.py` to match a game's winner against `john_commanders ∪ past_commanders` for that deck, not just the current commander list.

Scoped, not yet implemented — needs a Notion page property decision (new field name/shape) before building.
| Commander Brackets + Game Changers | ✅ Live | `commander_brackets`, `commander_game_changers` | The Game Changers list itself is a discrete, checkable card list | The bracket *definitions* are qualitative prose meant to be interpreted per-deck, not mechanically applied |
| Commander Bracket announcements | ✅ Live | `commander_bracket_announcements` | Official WotC source, timestamped and authoritative | Content is WotC's qualitative reasoning/guidance, requires interpretation same as bracket text |
| Commander B&R announcements | ✅ Live | `commander_banr_announcements` | Official, dated ban/unban facts | Stated *reasoning* behind each decision is qualitative commentary on card classes/format direction |

These two announcement feeds are the **only** WotC announcement sources ingested — there is no separate "general WotC announcements" feed. Each is its own filtered WotC search (`?search=Commander%20Bracket` / `?search=Commander+Banned+and+Restricted` in `clients/wotc_news.py` + the two `refresh_commander_*_announcements.py` scripts), both landing in the shared `content_chunks` collection via `chunk_announcement()`, tagged with distinct `category` values (`commander_bracket` / `commander_banr`).

## Community Wisdom (CW)

| Source | Status | Collection(s) | Notes |
|---|---|---|---|
| Commander Spellbook | 📋 Planned | new collection(s), TBD | **The planned HD→CW bridge source.** Two distinct data shapes in one API: (1) combo pieces/steps/results — structured, objective, HD-like (a combo either works or it doesn't); (2) "run in X% of decks with commander Y" usage-frequency stats per card — aggregated community behavior, CW-like, and the same shape EDHREC's synergy data will eventually provide. Calls for a **shared usage-frequency library** (card × commander → play-rate/inclusion-% records) that both Spellbook and the future EDHREC ingestion populate, rather than building this twice. HD side scoped below; CW/usage side still open. |

### Commander Spellbook — HD side (combo data) scoping

API confirmed live at `backend.commanderspellbook.com` (Django REST, no auth found). One example variant (`GET /variants/?limit=1`):

```json
{
  "id": "513-5034--46",
  "of": [{"id": 26516}],
  "uses": [
    {"card": {"id": 513, "name": "Hullbreaker Horror", "oracleId": "d4a84e78-...", "typeLine": "Creature — Kraken Horror"}, "quantity": 1, "zoneLocations": ["B"], "mustBeCommander": false},
    {"card": {"id": 5034, "name": "Sol Ring", "oracleId": "6ad8011d-...", "typeLine": "Artifact"}, "quantity": 1, "zoneLocations": ["B"], "mustBeCommander": false}
  ],
  "requires": [{"quantity": 1, "template": {"id": 46, "name": "Permanent that can be cast using {C}"}}],
  "produces": [{"feature": {"id": 11, "name": "Infinite colorless mana"}, "quantity": 1}],
  "description": "Activate Sol Ring by tapping it, adding {C} {C}. Cast the permanent...",
  "identity": "U",
  "legalities": {"commander": true, "vintage": true, "...": "..."},
  "popularity": 326736
}
```

Key facts that shape ingestion:

- **A "variant" is a specific card-for-card combo instance.** `requires` holds generic template slots (e.g. "any permanent castable for {C}") rather than concrete cards — a real decklist check needs to resolve which of *its own* cards satisfy each template, not just match on `uses`.
- **`popularity` is literally EDHREC deck-inclusion counts** (confirmed via syntax guide's `popularity`/`pop`/`deck`/`decks` operator description) — this is combo-level popularity, not the per-card "X% of decks with commander Y" granularity from the original ask, but it's adjacent enough to feed the shared usage-frequency library later.
- **`prices` (TCGPlayer/Cardmarket/Card Kingdom)** is market data — out of scope for this project (no financial/collection angle), recommend dropping on ingestion.
- Related discovery: `commanderspellbook.com/find-my-combos/` is their own "paste a decklist, see which combos you already have" feature — validates that this cross-referencing use case is exactly what our future `find_combos_in_deck()` tool should do. `commanderspellbook.com/syntax-guide/` documents the full query grammar (`card:`, `coloridentity:`, `template:`, `results:`, `is:tag`, etc.) which is worth keeping as a reference for later filtering/search features, even though it's not used for ingestion (see below).

**Ingestion mechanics — bulk file, not paginated REST crawl.** Commander Spellbook publishes a full bulk export at `https://json.commanderspellbook.com/variants.json` (S3/CloudFront-hosted, confirmed 546MB as of 2026-07-05), structured exactly like a Scryfall bulk file:

```json
{"timestamp": "2026-07-05T13:25:23...", "version": "5.4.10", "variants": [ ... ]}
```

This is a better fit than the paginated `/variants/` REST endpoint (which is all-formats and would need thousands of paginated requests) — download once, filter to `legalities.commander == true` locally, upsert. Staleness check mirrors `refresh_scryfall_bulk.py`'s `--if-stale` pattern, but checks the **remote** file instead of local data age: a cheap `HEAD` request (or tiny ranged `GET` of the first ~200 bytes) reads the `Last-Modified`/`ETag` headers or the embedded `timestamp`/`version` fields; skip the full download/re-upsert if unchanged since last sync. There's no per-variant `updated_at`, so on a change day the whole file is re-upserted (same as how Scryfall bulk refresh already works here — Mongo upserts make unchanged variants a no-op).

**Cadence: daily `--if-stale`**, same cron slot pattern as the other `refresh_*.py --if-stale` jobs, since new combos only appear alongside new card releases (matching Scryfall's own daily cadence) — unlike the 8-week gate on the official WotC sources, which move far slower.

**Scope decision: ingest all `legalities.commander == true` variants**, not narrowed to John's current decks' color identities. The bulk download cost is fixed regardless of how much gets filtered in, and storing the full commander-legal corpus means it's already there for any future deck/commander without re-ingestion.

**Template decision: store `requires` template slots as-is (`template_id`/`template_name`, verbatim from the API), resolve later.** The "which of my actual cards satisfies this generic template" logic is deferred to when `find_combos_in_deck()` gets built — ingestion just needs to preserve the raw template reference now.

**Proposed schema** — new collection `commander_combos`, one document per variant:

```json
{
  "variant_id": "513-5034--46",
  "combo_group_id": [26516],
  "identity": "U",
  "uses": [{"oracle_id": "...", "name": "...", "quantity": 1, "zone_locations": ["B"], "must_be_commander": false}],
  "requires": [{"template_id": 46, "template_name": "...", "quantity": 1}],
  "produces": [{"feature_id": 11, "feature_name": "...", "quantity": 1}],
  "description": "...",
  "legalities": {"commander": true, "...": "..."},
  "popularity": 326736,
  "last_synced": "..."
}
```

Indexes: unique on `variant_id`; multikey on `uses.oracle_id` (to answer "what combos use card X" and, eventually, "which combos are fully covered by deck Y's card list").
| Personal preference/playstyle corpus | 📋 Planned | new collection (TBD, likely `content_chunks`-style w/ its own category) | Redefined from the original Phase 3 idea: not just stats derived from `game_history`, but a slowly-accumulated RAG collection of things John states in chat about his own views, playstyle, and preferences — evidence gathered conversationally over time, same pattern as the article-ingestion pipeline |
| Other people's decklists (community meta/trends) | 📋 Planned | TBD | Reclassified from HD — this is a soft look at what the community is building, not ground truth about John's decks |
| EDHREC recommendations/synergy data | 📋 Planned | TBD | Unofficial API exists; no ingestion code yet. Would likely be structured (per-card recs) rather than prose-chunked |
| Embedding-based semantic search | 📋 Planned | `content_chunks.embedding` (additive field) | Referenced in `CLAUDE.md` as the planned upgrade once the CW article corpus is large enough to need it — MongoDB Community edition doesn't support `$vectorSearch` (Atlas-only), so current search is `$text` keyword search throughout |

### CW text sources — two top-level content types

All CW prose ends up chunked small for RAG regardless of origin, but the top-level `category`/`content_type` view should still distinguish **why** a piece of text is short or long, since that context matters for interpretation (a one-line Discord comment carries far less authority/context than a structured article):

**Long-form (`content_type: long_form`)** — organized, coherent, written with a 10,000-foot view:

| Source | Status | Collection(s) | Notes |
|---|---|---|---|
| Commander's Herald articles | 📋 Planned | `content_chunks` (`category: commanders_herald`) | No fetch/parse client yet; uses the existing `article` chunking tier (`chunk_text()`) unchanged |
| Future primers | 📋 Planned | `content_chunks` (new `category`) | Long-form deck primers, same `article` chunking tier |
| Well-organized/effortful Reddit posts | 📋 Planned | `content_chunks` (new `category`) | Distinguished from Reddit *comments* below by length/structure, not just source — a long deck-tech post belongs here, not in the short-form bucket |

**Short-form (`content_type: short_form`)** — low-context, low word count, no inherent structure:

| Source | Status | Collection(s) | Notes |
|---|---|---|---|
| John's personal game recaps | ✅ Live (as data) / 📋 Planned (as CW text) | `game_history.notes` today; candidate for `content_chunks` later | Already the CW half of the Dual HD+CW `game_history` row above — usually a short paragraph, listed here to keep the short-form taxonomy complete |
| Reddit comments (r/EDH etc.) | 📋 Planned | `content_chunks` (new `category`) | No fetch/parse client yet; likely doesn't need `chunk_text()`'s paragraph-merge logic at all given how short these are — may just need light dedup/threading, not real chunking |
| Discord messages | 📋 Planned | `content_chunks` (new `category`) | Mentioned as a future prose source in `chunking.py` docstring; no client; same short-form handling question as Reddit comments |

## Open questions for the next planning pass

- **Long-form vs short-form as a schema concept**: does this become a literal `content_type` field on `content_chunks` (orthogonal to `category`), or is it purely a documentation-level grouping? If it's a real field, the existing `chunk_text()` tier (`article`) maps to `long_form`; short-form sources may not need `chunk_text()`'s min/max-char merge logic at all (a single Discord message or game recap is already "one chunk") — possibly a 4th chunking tier that's mostly a pass-through with light concatenation by thread/session.

- **Usage-frequency shared library**: what's the common schema for "card X run in Y% of decks with commander Z" records so Commander Spellbook and (later) EDHREC both write into it instead of duplicating the concept? Likely shape: `{card, commander, inclusion_pct, sample_size, source, last_synced}`. Needs a home — new collection (e.g. `card_usage_stats`) rather than `content_chunks`, since it's structured, not prose.
- Does Commander Spellbook's combo-piece data (HD half) get its own collection, or fold into an existing one (`content_chunks` doesn't fit — it's structured, not prose)?
- How to actually capture the "personal preference corpus" — does this need a lightweight in-session flagging mechanism (agent notices a stated preference and writes it), or a periodic pass over chat history?
- Where's the line between "EDHREC synergy data" and "other people's decklists" when EDHREC recs are themselves derived from aggregated decklists? (Commander Spellbook's usage stats sharpen this question rather than resolve it.)
- Priority order for the planned CW sources (Commander Spellbook / personal preference corpus / EDHREC / other decklists / Commander's Herald / Reddit / Discord) — which unblocks the most useful agent behavior first?
- Whether Reddit/Discord ingestion is even in scope given their discussion-thread (not article) shape — may need a 4th chunking tier.
