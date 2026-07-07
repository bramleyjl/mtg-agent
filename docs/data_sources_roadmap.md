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
| Match/game history | ✅ Live / 🔧 template review planned | `game_history` | Wins/losses, structured outcome fields — feeds win-rate/enemy-commander stats | Free-text `notes` per game are a soft, subjective indicator of what happened/how it felt — candidate for the `content_chunks` semantic layer later per `CLAUDE.md`'s partial-exception note |

**Match history template — improvements planned (2026-07-07).** John intends to revisit the Notion match-history entry template itself (not just the sync code) to capture more per-game structure. First concrete addition: **turn the game ended on**. Bracket guidelines state a *minimum* expected game length, not a cap (confirmed via `get_commander_brackets`: B1 ≥9 turns, B2 ≥8, B3 ≥6, B4 ≥4, B5 unbounded) — the risk case is a game ending suspiciously fast for its bracket, not a slow one. John's own decks skew slower/controlling and comfortably clear these floors, so this is a metric to have on hand rather than one he expects to trip currently. Mostly derived from goldfishing rounds today. Treat as an open architecture review of the whole match-history template when picked up, not a single-field patch — other fields may get added in the same pass.

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
| Per-deck working notes / analysis journal | ✅ Built 2026-07-07 | Notion page body (per-deck), synced into `deck.working_notes` in Mongo | Deck-specific counterpart to the personal preference corpus above (that one is player-level; this one is per-deck). A single evolving markdown document per deck, maintained across sessions, not a chunked/searched log. Deliberately skips the `content_chunks` RAG pipeline: this is meant to be read as one coherent narrative each time, not semantically searched in fragments, closer to how `CLAUDE.md` itself works (a living doc read in full and edited) than to the article-ingestion model. **Storage:** lives in each deck's existing Notion page body (the long-form markdown area Notion pages have by default, previously barely used — its only prior content was links to similar decklists by other players for the same commander, folded in as its own template section below). Synced into Mongo as `working_notes` for fast reads. **Template sections:** Theme/strategy; Strengths; Weaknesses/vulnerabilities; **Restraints** (self-imposed play-pattern limits that hold power level down — most relevant at B2 and below, where what John *deliberately avoids doing* defines the bracket as much as what the deck can do); Current focus/improvement areas; Recurring in-game patterns; **Turns to win** (rough/soft metric, mostly from goldfishing — see the match-history template note above on why this isn't a hard constraint for John's typically slower decks); Similar decklists by other players. **Write path (built):** `update_deck_working_notes(slug, notes)` MCP tool (`tools/decks.py`, registered in `server.py`) — writes the markdown to the deck's Notion page body via the new `notion_update_page_body` notion-mcp tool, then `$set`s the identical content plus a `working_notes_synced_at` timestamp into Mongo in the same call, so Notion and Mongo never drift on agent-driven updates. `get_deck_full()` returns `working_notes` for reads. Update model: I write proactively at the end of substantive deck-focused sessions, always called out explicitly — never a silent edit. **Manual-edit reconciliation (built):** `scripts/refresh_deck_working_notes.py`, 5am daily cron (`--if-stale`), also registered in `tools/data_sources.py`'s `_SOURCES` for `refresh_all_data_sources()`. Compares each deck's Notion `last_edited_time` (via `notion_get_page`) against its stored `working_notes_synced_at`; a page edited more recently gets its body re-pulled verbatim via the new `notion_get_page_body` notion-mcp tool. Currently a **blind overwrite** of `working_notes` on any detected manual edit — no LLM-assisted merge — since the two write paths never touch the same content in practice (manual edits only happen when the agent isn't in the room). Revisit if that assumption stops holding. **notion-mcp dependency — resolved 2026-07-07:** `notion_get_page_body`/`notion_update_page_body` added and deployed to the notion-mcp service on pangolin; `notion_get_page` already returns `last_edited_time`, so no separate lookup was needed for that. |
| Other people's decklists (community meta/trends) | 📋 Planned | TBD | Reclassified from HD — this is a soft look at what the community is building, not ground truth about John's decks |
| EDHREC recommendations/synergy data | ✅ Built 2026-07-07 | `card_usage_stats`, `edhrec_commander_meta` | Unofficial JSON API, no auth. Structured (per-card recs), not prose-chunked. `scripts/refresh_edhrec.py`, weekly cron w/ `--if-stale` (per-commander 7-day gate). MCP tools: `compare_deck_to_edhrec(slug, scope)`, `get_edhrec_tag_data(slug, tag)`.

**Scope decision:** ingest only for commanders of John's own decks (13 today) — unlike Commander Spellbook's bulk file, this is a per-commander API call with no fixed-cost argument for going broader, so ingesting irrelevant commanders would be pure waste. Re-derive the commander list from the `decks` collection each run rather than hardcoding it. B1/B5 explicitly excluded — not brackets John plays.

**Confirmed API shape (2026-07-07):** `GET json.edhrec.com/pages/commanders/<slug>.json`. Slug rule: lowercase, strip commas/apostrophes/periods, spaces→hyphens — verified against 5 real commanders including hyphenated names (Niv-Mizzet Reborn, Atemsis, All-Seeing). Response has 13 disjoint card-list categories (`newcards`, `highsynergycards`, `topcards`, `gamechangers`, `creatures`, `instants`, `sorceries`, `utilityartifacts`, `enchantments`, `planeswalkers`, `utilitylands`, `manaartifacts`, `lands`) — confirmed zero card overlap across categories (checked all 300 unique cards on Breya's page), so each card gets exactly one category tag, no merge logic needed. Per-card fields: `name`, `synergy`, `num_decks`, `potential_decks` (= total decks in that scope's population). EDHREC's own `id` is confirmed **not** a Scryfall UUID (checked against Sai, Master Thopterist's real oracle_id — no match) — cards must resolve by name against `scryfall_oracle`, same pattern as `mongodb.resolve_commander_name()`.

**Bracket-specific sub-pages — confirmed real, mapped to WotC's own bracket titles, and each fully self-contained (2026-07-07):** EDHREC publishes a separate JSON page per bracket, using WotC's own terminology, not "bracket-N":

| Bracket | WotC title (`commander_brackets`) | EDHREC slug |
|---|---|---|
| 1 | Exhibition | `exhibition` |
| 2 | Core | `core` |
| 3 | Upgraded | `upgraded` |
| 4 | Optimized | `optimized` |
| 5 | cEDH | `cedh` |

`GET json.edhrec.com/pages/commanders/<slug>/<bracket-slug>.json`. Verified each bracket page **recomputes its own denominator and rankings from scratch**, not a filtered slice of the default page's numbers — e.g. Breya's top card at default/B3 is Swords to Plowshares, but B4's top card is Etherium Sculptor; `potential_decks` differs per scope (default 21,507 / B3 1,815 / B4 1,704 / B2 1,140). **Scope decision:** ingest `default` + `bracket_2`/`bracket_3`/`bracket_4` only (4 calls/commander) — B1/B5 skipped since John doesn't play them. This is the one genuinely useful filter axis EDHREC exposes for a project this bracket-focused, and gives real signal: e.g. Swords to Plowshares sits at ~51% inclusion in B4 Breya decks vs. ~39% in B2 (and its synergy score flips from negative at B2/B3 to positive at B4) — directly relevant context for the "add Swords" item already in Breya's Current Focus notes.

**Theme/tag sub-pages — confirmed real, and NOT proactively ingested.** `GET json.edhrec.com/pages/commanders/<slug>/<tag-slug>.json` (tested `artifacts`, `combo`, `tokens`, `budget`, `expensive` for Breya — all distinct real payloads, a separate mechanism from the bracket pages above). Pre-selecting "the right tags per commander" is a judgment call about what actually defines a deck's identity, not something to guess at from raw tag-popularity counts — so tags are **on-demand only**, via a new MCP tool (`get_edhrec_tag_data(slug, tag)`) that fetches live when actually asked about (e.g. "what does the Artifacts crowd play with Breya"), not proactively for every tag `tag_counts` happens to list. Once fetched, the resulting `scope: "tag:<slug>"` rows simply exist in the DB going forward — **the weekly cron refreshes whatever scopes already exist per commander** (`default`/`bracket_2`/`bracket_3`/`bracket_4` plus any previously-requested `tag:*` scopes), rather than a hardcoded scope list. So a tag graduates into the recurring refresh automatically the first time it's asked about, with no separate "tracked tags" bookkeeping.

**Ad-hoc "with card X" / min-max type-count filter — confirmed NOT accessible.** EDHREC's interactive "Deck Filters" UI (e.g. filter to decks running Ashnod's Altar + Krark-Clan Ironworks + artifacts ≥ 30) builds a `?f=in=<card>;a:gt=<n>` query string client-side, but passing that same query string to the JSON API is silently ignored — verified byte-identical response with and without the filter param. This filter is powered by a different, non-public backend; not replicable through this data source.

**The `/combos/<slug>` page is NOT new data — confirmed to be Commander Spellbook's own combo database, re-served.** Cross-checked the first entry on Breya's combos page (Nim Deathmantle + Ashnod's Altar) against our own `commander_combos`: identical `variant_id` ("2034-5003--73") *and* identical `popularity` (28561) to what Spellbook ingestion already stored. EDHREC's per-commander combos view is Spellbook's data filtered to combos compatible with that commander's color identity, using Spellbook's own global (not commander-conditioned) popularity — nothing to gain by ingesting this separately; `find_combos_in_deck()` already covers this ground. This also further confirms the earlier "Commander Spellbook vs. EDHREC" resolution (no per-commander popularity bridge exists in Spellbook's own data) rather than reopening it.

**Schema — `card_usage_stats`, one row per (commander, card, scope):**
```json
{
  "commander_oracle_id": "...", "commander_name": "...",
  "oracle_id": "...", "card_name": "...",
  "scope": "default | bracket_2 | bracket_3 | bracket_4 | tag:<slug>",
  "category": "topcards | creatures | manaartifacts | ...",
  "synergy": 0.27, "num_decks": 2342, "potential_decks": 4457,
  "inclusion_pct": 52.55,
  "last_synced": "..."
}
```
Unique index: `(commander_oracle_id, oracle_id, scope)` — the same card carries independently meaningful stats per scope (confirmed above: Swords to Plowshares' synergy sign flips between B2/B3 and B4), so scope must be part of the key, not a separate lookup layer.

**Schema — `edhrec_commander_meta`, one row per (commander, scope):**
```json
{
  "commander_oracle_id": "...", "commander_name": "...",
  "scope": "default | bracket_2 | bracket_3 | bracket_4 | tag:<slug>",
  "total_decks": 21507,
  "bracket_counts": {"1": 70, "2": 1140, "3": 1815, "4": 1704, "5": 331},
  "tag_counts": {"Artifacts": 4457, "Combo": 957, "Tokens": 913, "...": "..."},
  "last_synced": "..."
}
```
`bracket_counts` only stored on `default`/`tag:*` scopes — on a `bracket_2`/`bracket_3`/`bracket_4` row it's tautological (100% of that population is definitionally that bracket, confirmed: the B3 page's own `bracket_counts` is just `{"3": 1815}`). `tag_counts` **is** kept on every scope, verified non-redundant: relative tag rank shifts meaningfully by bracket (Combo ranks #3 among Breya's tags at B2, but #2 at B4 — i.e. combo-focus becomes relatively more central to how the commander is built as bracket rises, a real signal not noise). `budget_counts` considered and **dropped** — it buckets decks into `budget`/`middle`/`expensive` tiers, but the actual dollar thresholds aren't exposed by the API, and John doesn't track budget as a real design axis for these decks, so the field wasn't earning its storage cost.

**Cadence:** weekly staleness gate (community data, not card-release-driven) — much less urgent than Scryfall's daily cadence. New `scripts/refresh_edhrec.py`, registered in the usual cron/`_SOURCES` pattern.

**MCP tools (built):**
- `compare_deck_to_edhrec(slug, scope="default")` — gap-analysis tool mirroring `find_almost_combos()`: which of the deck's own cards are/aren't EDHREC staples for that commander+scope, and which popular cards it's missing. `scope` param lets a query target the aggregate or a specific bracket.
- `get_edhrec_tag_data(slug, tag)` — the on-demand tag-scope fetch described above.

**Build note (2026-07-07): double-faced/split card name resolution.** Live-tested against all 13 real commanders — EDHREC lists DFCs/split cards by front-face name only (e.g. `"Birgi, God of Storytelling"`), while `scryfall_oracle` stores the combined `"Front // Back"` name. This caused 5-30 unresolved cards per commander+scope on the first pass. Fixed with a fallback: any name that doesn't resolve by exact match gets a `"^Front\s*//"` prefix-match query against `scryfall_oracle`. This closed nearly every gap (verified zero unresolved cards across all 13 commanders x 4 scopes after the fix) — the one confirmed remaining miss is `"Tony Stark"` on one commander's page, a Universes Beyond card not present in `scryfall_oracle` at all (not a resolution bug). |
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
