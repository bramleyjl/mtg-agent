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
| Scryfall Tagger oracle tags | ✅ Live (ingestion, search, deck-sync integration) / 📋 Planned (filter curation session) | `scryfall_oracle_tags` | Ingestion done. `search_tags()`/`get_cards_by_tag()` MCP tools added 2026-07-06 for keyword discovery + exact-tag card lookup. `sync_deck` now attaches each card's filtered tags as `scryfall_tags` on its deck entry. Filtering is via `tag_filters.py`'s `is_gameplay_tag()` — a denylist (prefix rules for `cycle-`/`supercycle-`/`type-errata`, plus ~30 curated trivia/flavor slugs) built from a single-deck spot check (Titania), **not a full review of the ~4,500 tags in the collection**. **Planned: a session dedicated to curating this filter list** — review a wider sample of tags/decks, tighten the denylist, and decide whether any excluded tags should come back (or vice versa) before treating the filter as stable. Moxfield tags turned out to still be in active use on some of John's older decks (confirmed via Titania) despite showing empty on newer syncs — worth understanding why before deciding whether to migrate off Moxfield tags entirely. |
| Personal decklists (Moxfield sync) | ✅ Live | `decks` | `clients/moxfield.py` fetch + `compute_deck_stats`; synced via Notion page + `session_sync.py`. **Bracket split 2026-07-06:** `bracket` (John's own nuanced read, e.g. "2.9"/"3.9") is sourced from Notion's "Bracket" property (synced in by `sync_game_history`, falls back to `decks.yaml` if unset); `bracket_official` is WotC's strict 1-5 rating straight from Moxfield with no override, pushed to Notion's new "Bracket Official" property by `sync_deck`. `description` (renamed from `notes`) now treats Moxfield's own description as source of truth, falling back to `decks.yaml` only if Moxfield has none, and is pushed to Notion's "Description" property (renamed from "Notes") on every sync. |
| Comprehensive Rules | ✅ Live | `rules_numbered`, `rules_glossary` | `refresh_comprehensive_rules.py`, daily cron, 8-week staleness gate |
| Commander banned list | ✅ Live | `commander_banned_list` | `refresh_commander_banlist.py`, daily cron, 8-week gate |
| Draw-probability / hypergeometric calculators | ✅ Live | n/a (pure compute) | `tools/probability.py` — not a data source, but a derived-data tool over `decks`. All 4 standard calculator types now implemented: basic single-category, multivariate (multiple simultaneous category minimums), mulligan-adjusted (London mulligan sequence), and sources-needed (Frank Karsten-style inverse solve for color-source count) |

## Dual HD + CW

| Source | Status | Collection(s) | HD part | CW part |
|---|---|---|---|---|
| Match/game history | ✅ Live | `game_history` | Wins/losses, structured outcome fields — feeds win-rate/enemy-commander stats | Free-text `notes` per game are a soft, subjective indicator of what happened/how it felt — candidate for the `content_chunks` semantic layer later per `CLAUDE.md`'s partial-exception note |

**Past-commander gap — ✅ resolved 2026-07-06.** Added a "Previous Commanders" multi-select property to the Notion EDH database (populated for Atemsis, Ephara, Glarb, Rem Karolus so far). `sync_game_history` in `tools/decks.py` now pulls it into each deck's Mongo record as `past_commanders`, matches a game's winner against `john_commanders ∪ past_commanders` (bidirectional name-containment check, since past-commander entries are short informal names while `winner` stores full canonical Scryfall names), and **self-heals every existing `game_history` record for that deck on each sync** — so editing "Previous Commanders" in Notion, or a future commander swap, retroactively fixes historical win/loss classification without a manual backfill.

| Source | Status | Collection(s) | HD part | CW part |
|---|---|---|---|---|
| Commander Brackets + Game Changers | ✅ Live | `commander_brackets`, `commander_game_changers` | The Game Changers list itself is a discrete, checkable card list | The bracket *definitions* are qualitative prose meant to be interpreted per-deck, not mechanically applied |
| Commander Bracket announcements | ✅ Live | `commander_bracket_announcements` | Official WotC source, timestamped and authoritative | Content is WotC's qualitative reasoning/guidance, requires interpretation same as bracket text |
| Commander B&R announcements | ✅ Live | `commander_banr_announcements` | Official, dated ban/unban facts | Stated *reasoning* behind each decision is qualitative commentary on card classes/format direction |

These two announcement feeds are the **only** WotC announcement sources ingested — there is no separate "general WotC announcements" feed. Each is its own filtered WotC search (`?search=Commander%20Bracket` / `?search=Commander+Banned+and+Restricted` in `clients/wotc_news.py` + the two `refresh_commander_*_announcements.py` scripts), both landing in the shared `content_chunks` collection via `chunk_announcement()`, tagged with distinct `category` values (`commander_bracket` / `commander_banr`).

## Community Wisdom (CW)

| Source | Status | Collection(s) | Notes |
|---|---|---|---|
| Commander Spellbook | ✅ Live, complete | `commander_combos`, `commander_spellbook_templates` | Combo data (pieces/steps/results) plus per-combo popularity, now with `popularity_percentile` for context and `find_almost_combos()` for gap-analysis (see below). **Not a bridge to EDHREC's usage-frequency data** — see "Commander Spellbook vs. EDHREC" note below. |

### Commander Spellbook — HD side (combo data) — ✅ MVP-complete 2026-07-06

`refresh_commander_spellbook.py`, daily cron (9am slot), two independent staleness clocks:
- **Combos** (`commander_combos`) — gated on the **remote** bulk file's `Last-Modified` header (not local data age — see `CLAUDE.md` step 9). 95,430+ commander-legal variants, one document per variant, schema as scoped below.
- **Templates** (`commander_spellbook_templates`) — some combo pieces are "variable" rather than a specific card (e.g. "any creature with Persist or Undying," an "Impact Tremors"-type damage-on-cast effect). All 167 of Commander Spellbook's generic template categories are resolved to the concrete set of commander-legal oracle_ids that satisfy each one, via Scryfall (each template ships its own ready-made `scryfallApi` search URL). Gated on a 7-day local window, but **incrementally**: a template already resolved only re-queries Scryfall for cards released since its last resolve (plus a 3-day overlap buffer) and unions the result into what's stored — not a full re-query of its entire matching card pool. Only a brand-new template, or one whose query text changed upstream, gets a full resolve. This is what makes weekly cron runs take seconds instead of the ~15 minutes the initial full resolve of all 167 templates took.

**`find_combos_in_deck(slug)`** — live MCP tool (`tools/combos.py`) cross-referencing a deck's current cards against both `uses` (exact oracle_id matches) and `requires` (satisfied if the deck owns any card in the matching template's resolved oracle_ids) — the "one or more variable pieces" resolution originally deferred is now built. Validated against real decks: Breya (dedicated combo deck) returns 23 combos; all three bracket-4 decks (Ruric Thar, Kykar, Karlov) confirmed to have at least one infinite. Flags `commander_zone_violations` when a `must_be_commander` piece is present in the deck but not actually the commander (surfaced, not excluded — see the tool's docstring).

**Popularity interpretation layer — ✅ done 2026-07-06.** Raw `popularity` counts had no context on their own (e.g. "326736" — impressive or unremarkable, out of ~95k combos?). `refresh_commander_spellbook.py`'s `refresh()` now computes `popularity_percentile` (0-100) for every combo against the full ingested distribution at ingestion time (cheap — the full popularity list is already in memory before the upsert batching loop starts, so no second pass needed), and `find_combos_in_deck()` surfaces it alongside the raw count. Separately, **`find_almost_combos(slug, max_missing=1)`** is a new MCP tool — the gap-analysis companion to `find_combos_in_deck()`: finds combos the deck has *some but not all* pieces for (gated by color identity, same `requires`-satisfaction rule), flags `commander_change_required` on any missing piece that must be the commander (a bigger ask than adding a card to the 99), and sorts by fewest-missing-then-most-popular so suggestions prioritize "best bang for buck."

**Commander Spellbook vs. EDHREC — no real overlap, confirmed 2026-07-06.** The original framing of Commander Spellbook as an "HD→CW bridge" assumed its `popularity` field could feed a shared per-commander usage-frequency schema alongside EDHREC. Checked the actual data: `popularity` is combo-level only, and combos aren't commander-scoped at all (only gated by a color-identity string, e.g. `"UB"`) — there's no per-commander granularity to give. The "shared usage-frequency library" idea from the Open Questions section below doesn't apply to Commander Spellbook; it's resolved as EDHREC-only, whenever that gets built (own dedicated planning session, not bundled with Spellbook work). Groundwork already done for that future session: EDHREC's JSON shape is `container.json_dict.cardlists[].cardviews[]` at `json.edhrec.com/pages/commanders/<slug>.json`, each card entry has `name`/`synergy`/`num_decks`/`potential_decks` (its own `id` field is NOT a Scryfall UUID — cards must be resolved by name), and the commander→slug derivation is lowercase + strip commas/apostrophes/periods + spaces→hyphens (confirmed working, e.g. "Kykar, Wind's Fury" → `kykar-winds-fury`) though it needs a verification pass across all of John's commanders before relying on it, given potential double-faced/split-name edge cases.

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
- Related discovery: `commanderspellbook.com/find-my-combos/` is their own "paste a decklist, see which combos you already have" feature — validated that this cross-referencing use case is exactly what `find_combos_in_deck()` now does. `commanderspellbook.com/syntax-guide/` documents the full query grammar (`card:`, `coloridentity:`, `template:`, `results:`, `is:tag`, etc.) which is worth keeping as a reference for later filtering/search features, even though it's not used for ingestion (see below).

**Ingestion mechanics — bulk file, not paginated REST crawl.** Commander Spellbook publishes a full bulk export at `https://json.commanderspellbook.com/variants.json` (S3/CloudFront-hosted, confirmed 546MB as of 2026-07-05), structured exactly like a Scryfall bulk file:

```json
{"timestamp": "2026-07-05T13:25:23...", "version": "5.4.10", "variants": [ ... ]}
```

This is a better fit than the paginated `/variants/` REST endpoint (which is all-formats and would need thousands of paginated requests) — download once, filter to `legalities.commander == true` locally, upsert. Staleness check mirrors `refresh_scryfall_bulk.py`'s `--if-stale` pattern, but checks the **remote** file instead of local data age: a cheap `HEAD` request (or tiny ranged `GET` of the first ~200 bytes) reads the `Last-Modified`/`ETag` headers or the embedded `timestamp`/`version` fields; skip the full download/re-upsert if unchanged since last sync. There's no per-variant `updated_at`, so on a change day the whole file is re-upserted (same as how Scryfall bulk refresh already works here — Mongo upserts make unchanged variants a no-op).

**Cadence: daily `--if-stale`**, same cron slot pattern as the other `refresh_*.py --if-stale` jobs, since new combos only appear alongside new card releases (matching Scryfall's own daily cadence) — unlike the 8-week gate on the official WotC sources, which move far slower.

**Scope decision: ingest all `legalities.commander == true` variants**, not narrowed to John's current decks' color identities. The bulk download cost is fixed regardless of how much gets filtered in, and storing the full commander-legal corpus means it's already there for any future deck/commander without re-ingestion.

**Template decision: store `requires` template slots as-is (`template_id`/`template_name`, verbatim from the API), resolve separately.** ~~The "which of my actual cards satisfies this generic template" logic is deferred to when `find_combos_in_deck()` gets built~~ — done. See the "MVP-complete" section above: templates resolve to concrete oracle_ids in their own `commander_spellbook_templates` collection, and `find_combos_in_deck()` is a live tool.

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
  "popularity_percentile": 99.8,
  "last_synced": "..."
}
```

Indexes: unique on `variant_id`; multikey on `uses.oracle_id` (to answer "what combos use card X" and, eventually, "which combos are fully covered by deck Y's card list").
| Personal preference/playstyle corpus | 📋 Planned | new collection (TBD, likely `content_chunks`-style w/ its own category) | Redefined from the original Phase 3 idea: not just stats derived from `game_history`, but a slowly-accumulated RAG collection of things John states in chat about his own views, playstyle, and preferences — evidence gathered conversationally over time, same pattern as the article-ingestion pipeline |
| Per-deck working notes / analysis journal | 📋 Scoped 2026-07-06, not yet built | Notion page body (per-deck), synced into `deck.working_notes` in Mongo | Deck-specific counterpart to the personal preference corpus above (that one is player-level; this one is per-deck). A single evolving markdown document per deck — theme, strengths/weaknesses, current focus/improvement areas, recurring in-game patterns — maintained across sessions, not a chunked/searched log. Deliberately skips the `content_chunks` RAG pipeline: this is meant to be read as one coherent narrative each time, not semantically searched in fragments, closer to how `CLAUDE.md` itself works (a living doc read in full and edited) than to the article-ingestion model. **Storage decision:** lives in each deck's existing Notion page body (the long-form markdown area Notion pages have by default, currently barely used — its only current use is holding links to similar decklists by other players for the same commander, which becomes its own section in the new template and will eventually be superseded by the "other people's decklists" CW source above). Synced into Mongo as `working_notes` for fast reads. **Update model:** I update it proactively at the end of substantive deck-focused sessions (not only when asked), but always call out what changed in the conversation when I do — never a silent edit. Still open: exact template section headers, and whether `working_notes` syncs bidirectionally (Notion edits flowing back into Mongo) or Mongo→Notion one-way. |
| Other people's decklists (community meta/trends) | 📋 Planned | TBD | Reclassified from HD — this is a soft look at what the community is building, not ground truth about John's decks |
| EDHREC recommendations/synergy data | 📋 Planned | TBD (likely new `card_usage_stats`) | Unofficial API exists; no ingestion code yet. Structured (per-card recs), not prose-chunked. Groundwork done 2026-07-06 — see "Commander Spellbook vs. EDHREC" note above for confirmed JSON shape and slug-derivation rule |
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

- **Usage-frequency library**: resolved 2026-07-06 as **EDHREC-only** — Commander Spellbook's `popularity` turned out to be combo-level, not commander-scoped, so it can't share a `{card, commander, inclusion_pct}` schema (see the Commander Spellbook section above). When EDHREC ingestion is planned, likely shape: `{oracle_id, commander_oracle_id, source: "edhrec", inclusion_pct, num_decks, potential_decks, synergy, last_synced}` in a new `card_usage_stats` collection (structured, not prose — doesn't belong in `content_chunks`).
- How to actually capture the "personal preference corpus" — does this need a lightweight in-session flagging mechanism (agent notices a stated preference and writes it), or a periodic pass over chat history?
- Where's the line between "EDHREC synergy data" and "other people's decklists" when EDHREC recs are themselves derived from aggregated decklists?
- Priority order for the planned CW sources (personal preference corpus / EDHREC / other decklists / Commander's Herald / Reddit / Discord) — which unblocks the most useful agent behavior first?
- Whether Reddit/Discord ingestion is even in scope given their discussion-thread (not article) shape — may need a 4th chunking tier.
