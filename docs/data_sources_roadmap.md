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

**Match history template — expanded 2026-07-07.** Added two properties to the Notion "EDH Game Records" database (`ADD COLUMN` via `notion-update-data-source`, data source `0a966574-64e4-4036-93b3-a3f8461ef9d0`) and wired both into `sync_game_history` (`tools/decks.py`), stored as `turn_ended`/`turn_order` on `game_history`: **`Turn Ended`** (nullable number — John logs it when he remembers to count; bracket guidelines state a *minimum* expected game length, not a cap, per `get_commander_brackets`: B1 ≥9 turns, B2 ≥8, B3 ≥6, B4 ≥4, B5 unbounded — the risk case is a game ending suspiciously fast for its bracket, and John's own decks skew slower/controlling and comfortably clear these floors today, so this is a metric to have on hand rather than one he expects to trip; no automated bracket-floor check built yet, this is raw data collection only) and **`Seat Order`** (nullable number, 1-4 — which seat John was in that game, not just a "went first" boolean, since seat position in a 4-player pod is a spectrum rather than binary; named `Seat Order` in Notion, not `Turn Order`, to avoid confusion with `Turn Ended`, but still stored as `turn_order` on `game_history` for consistency with the rest of that record's naming). `_parse_notion_prop()` gained `number`/`checkbox` type handling to support this (checkbox added for the parser's general completeness, though no property currently uses it). Scoped down from a broader review: John declined syncing the existing `Opponents` property (human player names, still Notion-only) and adding finish-position/elimination-order tracking in this pass — revisit if that need resurfaces.

**`force` resync param — 2026-07-07.** John manually updated all ~110 pre-existing "EDH Game Records" pages after the property/title-body changes above landed (backfilling `Seat Order`, confirming body-recap content). Incremental sync alone never re-touches an already-known `notion_id`, so those edits wouldn't have reached MongoDB. `sync_game_history` (`tools/decks.py`, `server.py`) gained a `force: bool = False` param — when `True`, every game_id for the deck is re-fetched (not just new ones), not just the `new/enemy_commanders/won` self-heal that already existed. This is the general reconciliation path for any future Notion template change to existing pages, not a one-off script.

**Title/body split — same review, 2026-07-07.** The database's title property used to double as the free-text game recap field (originally named "Notes", `type: title`) — meaning the Notion table view showed the full recap text as every row's title, and the recap wasn't a real "unique identifier" anyway since Notion's title property was never enforcing uniqueness (the `ID` unique_id property already does that job independently). Renamed the title property to **`Title`** (`RENAME COLUMN` via `notion-update-data-source`) and changed its purpose: it now holds a short manually-typed label in the format `"YYYY-MM-DD G#"` (G# = the Nth game logged that calendar date, counted across all decks/pods, not per-deck — e.g. Karlov then Atemsis same day are G1/G2). The actual free-text recap moved into each page's **body**, mirroring the existing per-deck working-notes pattern (`fetch_page_body`/`update_page_body` in `clients/notion_mcp.py`). John opted to change his capture habit going forward (type notes into the body when logging a new game, title stays terse from creation) rather than have sync auto-detect and migrate new entries. All ~110 pre-existing records were bulk-migrated in the same pass (old title text moved to body, title replaced with the generated `date G#` label) via a one-off agent-driven Notion API pass — not a repo script, since this was a one-time cleanup, not a recurring job. `sync_game_history` (`tools/decks.py`) now reads `notes` from `fetch_page_body()` instead of the `Notes`/`Title` property.

**Game history now wired into the extension sync path — 2026-07-07.** `/sync-deck` (`server.py`'s `http_sync_deck`, the browser-extension HTTP endpoint) previously only refreshed Moxfield card data via `decks.sync_deck()` — it never touched `game_history`, so logging new games in Notion required a separate manual `sync_game_history` call or a full `session_sync.py` run. Now, for John's own decks (not reference decklists), `http_sync_deck` also calls `decks.sync_game_history(slug, config)` right after `sync_deck()` succeeds and folds the result into the response under `game_history`. So triggering the extension on a deck (e.g. Ephara) now checks the "EDH Game Records" database for any new entries with that deck's relation and syncs them in the same call, no separate step needed.

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
| Personal preference/playstyle corpus | ✅ Built 2026-07-07 | `player_preferences` | Redefined from the original Phase 3 idea: not just stats derived from `game_history`, but a slowly-accumulated collection of things John states in chat about his own views, playstyle, and preferences — evidence gathered conversationally over time. **Design decisions (2026-07-07):** in-session flagging chosen over periodic look-behind — no chat-transcript persistence exists in this codebase to scan periodically (every other CW source scrapes something external that already exists; this doesn't), and in-session capture preserves the conversational *why* that a later scan would lose. Always called out explicitly when saved (John wants visibility into what's being recorded; may revisit if it gets spammy). Triggered by *organic* statements only — a formal instruction to edit a specific deck's document (e.g. "update Kokusho's notes to say X") goes to `update_deck_working_notes` instead, even when the organic statement is about a specific deck (scoped via optional `deck_slug`, not routed to that deck's own doc). Explicitly out of scope: feedback about *how the agent should work* (communication style, tool-use corrections) — that already lives in Claude Code's own cross-project memory system, not this project's data layer. **Schema:** own dedicated collection, not folded into `content_chunks` — entries are atomic (no `chunk_text()` splitting needed, unlike the article/long-form tier) and need a `deck_slug` scoping field and `stated_at` timestamp that `content_chunks` doesn't have. Fields: `text` (the statement, 1-2 paragraphs, self-contained — no separate "context" field, any why-it-came-up detail is folded directly into `text`), `deck_slug` (optional), `topic_tags` (optional, free-form), `session_context` (optional, brief provenance note), `stated_at`. **Append-only, no dedup/reconciliation at write time** — evolving or contradicting a past statement just adds a new row; recency is used as a read-time tiebreaker, not enforced as a single source of truth at write time. A consolidation/reconciliation pass (analogous to `refresh_deck_working_notes.py`'s role for working notes) is a plausible post-MVP enhancement, not needed for MVP. **Search:** `$text` relevance-ranked primary, `stated_at` descending as secondary sort. **Tools:** `record_player_preference(text, deck_slug, topic_tags, session_context)` (write), `search_player_preferences(query, deck_slug)` (read) — both in `tools/preferences.py`, registered in `server.py`. No refresh script/cron — this source is agent-written during conversation, not scraped, so it's not registered in `tools/data_sources.py`'s `_SOURCES` list. |
| Per-deck working notes / analysis journal | ✅ Built 2026-07-07 | Notion page body (per-deck), synced into `deck.working_notes` in Mongo | Deck-specific counterpart to the personal preference corpus above (that one is player-level; this one is per-deck). A single evolving markdown document per deck, maintained across sessions, not a chunked/searched log. Deliberately skips the `content_chunks` RAG pipeline: this is meant to be read as one coherent narrative each time, not semantically searched in fragments, closer to how `CLAUDE.md` itself works (a living doc read in full and edited) than to the article-ingestion model. **Storage:** lives in each deck's existing Notion page body (the long-form markdown area Notion pages have by default, previously barely used — its only prior content was links to similar decklists by other players for the same commander, folded in as its own template section below). Synced into Mongo as `working_notes` for fast reads. **Template sections:** Theme/strategy; Strengths; Weaknesses/vulnerabilities; **Restraints** (self-imposed play-pattern limits that hold power level down — most relevant at B2 and below, where what John *deliberately avoids doing* defines the bracket as much as what the deck can do); Current focus/improvement areas; Recurring in-game patterns; **Turns to win** (rough/soft metric, mostly from goldfishing — see the match-history template note above on why this isn't a hard constraint for John's typically slower decks); Similar decklists by other players. **Write path (built):** `update_deck_working_notes(slug, notes)` MCP tool (`tools/decks.py`, registered in `server.py`) — writes the markdown to the deck's Notion page body via the new `notion_update_page_body` notion-mcp tool, then `$set`s the identical content plus a `working_notes_synced_at` timestamp into Mongo in the same call, so Notion and Mongo never drift on agent-driven updates. `get_deck_full()` returns `working_notes` for reads. Update model: I write proactively at the end of substantive deck-focused sessions, always called out explicitly — never a silent edit. **Manual-edit reconciliation (built):** `scripts/refresh_deck_working_notes.py`, 5am daily cron (`--if-stale`), also registered in `tools/data_sources.py`'s `_SOURCES` for `refresh_all_data_sources()`. Compares each deck's Notion `last_edited_time` (via `notion_get_page`) against its stored `working_notes_synced_at`; a page edited more recently gets its body re-pulled verbatim via the new `notion_get_page_body` notion-mcp tool. Currently a **blind overwrite** of `working_notes` on any detected manual edit — no LLM-assisted merge — since the two write paths never touch the same content in practice (manual edits only happen when the agent isn't in the room). Revisit if that assumption stops holding. **notion-mcp dependency — resolved 2026-07-07:** `notion_get_page_body`/`notion_update_page_body` added and deployed to the notion-mcp service on pangolin; `notion_get_page` already returns `last_edited_time`, so no separate lookup was needed for that. |
| Reference decklists (other people's decks, e.g. linked from strategy articles) | ✅ Built and validated end-to-end 2026-07-07 | `reference_decklists` | Renamed from "Other people's decklists" — see dedicated section below |
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

**`content_type` (long-form vs. short-form) — resolved 2026-07-07: documentation-level grouping only, not a stored field.** `category` already uniquely identifies the source, and the full set of `category` values (current + planned, long-form only — see deferral below) is short enough to hang a static lookup off of instead of carrying redundant data on every chunk:

```python
# chunking.py — derived, not persisted; no consumer needs it as a queryable field yet
CATEGORY_CONTENT_TYPE = {
    "commander_bracket": "long_form",   # live
    "commander_banr": "long_form",      # live
    "strategy_article": "long_form",    # planned
    "primer": "long_form",              # planned
    "reddit_post": "long_form",         # planned, well-organized/effortful posts only
    "player_theory": "long_form",       # planned
}
```

Add this dict alongside `chunk_text()` only once something actually needs to filter/weight by content_type at read time (nothing does today — `search_content_chunks(query, category=...)` already covers current needs). Short-form categories (Reddit comments, Discord messages, `game_history.notes`) are deliberately left off this table — see deferral note below.

**Social-media / short-form ingestion (Reddit comments, Discord) — explicitly deferred, 2026-07-07.** Sequencing decision: standard long-form primers/articles (Commander's Herald, future primers, effortful Reddit posts, `player_theory`) get built first, since that work also naturally involves extracting/linking the decklists those articles typically reference (the existing "similar decklists by other players" section in each deck's working notes is the concrete tie-in — see the working-notes template in the Dual HD+CW section above). The short-form/threaded-conversation architecture (4th chunking tier question, thread-grouping vs. `chunk_text()`'s paragraph-merge logic, whether Reddit/Discord are even in scope) is revisited only after that long-form work lands, not before.

**Long-form (organized, coherent, written with a 10,000-foot view):**

**`reddit_post` remains its own dedicated planning session — 2026-07-07.** Unlike `strategy_article`/`primer` (resolved together below), it still needs a Reddit API client plus a "well-organized vs. low-effort" curation judgment, and isn't picked up here.

### `strategy_article` / `primer` — built 2026-07-07, one MVP tool for both

**Scoping conversation collapsed the two categories into one problem, not two.** The original plan treated `strategy_article` (general technique, e.g. Commander's Herald) and `primer` (commander/archetype-specific, e.g. a deck-tech write-up) as separate build efforts, each blocked on its own gap (a per-site scraper + discovery mechanism for the former; a `deck_slug`-scoping fix for the latter). Working through the first real example — [airza.net's "Ursine Madness"](https://airza.net/2023/08/20/ursine-madness), a Wilson/Noble Heritage primer — dissolved both blockers at once:

- **No per-site scraper needed.** The agent already fetches arbitrary pages cleanly via its own WebFetch tool (this is how the two linked Moxfield decklists were found in the first place) — no bespoke httpx/regex parser per site, unlike `clients/wotc_news.py`'s WotC-specific scraper. Trade-off: ingestion is conversational (John asks the agent to ingest a specific article) rather than an unattended cron/discovery job — acceptable, since there's no realistic automated discovery mechanism for "the whole internet's worth of MTG blogs" anyway.
- **`deck_slug` was the wrong scoping model, and so was `commander_names` alone.** The concrete design problem: the Wilson primer's philosophy (race-math/lethal-threshold thinking over engine-building, treating multiplayer as 1v1v1v1 rather than 1v3) is exactly the kind of generalizable theory John wants captured — but it needs to surface in conversations about *mechanically unrelated* decks that share the philosophy (e.g. Rem Karolus, a non-Voltron deck built around "get to ~40 damage before the table's combined damage lowers your own margin," which shares the Wilson primer's race-to-threshold logic despite sharing zero cards or archetype). A `commander_names`/`deck_slug`-style filter would only ever surface this article inside a Wilson conversation, never a Rem Karolus one — actively wrong for the use case.

**Resolution: `commander_names` is citation-only metadata; `topic_tags` is the real retrieval axis.** `commander_names` (free-text card names, e.g. `["Wilson, Refined Grizzly", "Noble Heritage"]`) records which concrete decklist(s) demonstrate the article's ideas, but never gates search. `topic_tags` (free-form strings, e.g. `["damage-race-math", "multiplayer-threat-assessment", "punish-over-engine"]`) is the actual cross-archetype connective tissue — tag the *underlying theory*, not the commander, so a Rem Karolus conversation can surface a Wilson-primer chunk via shared tags even with no card overlap. **Tag vocabulary is free-form for now** (same as `player_preferences`' `topic_tags`) rather than a controlled/canonical list — accepted risk of synonym drift (e.g. "damage-race" vs. "race-math" meaning the same thing) in exchange for zero upfront design cost; revisit if that drift starts hurting retrieval as the corpus grows. `category` (`primer` vs. `strategy_article`) is bookkeeping only, same resolution as the `content_type` question above — it doesn't gate search either, since a single article (like this one) can legitimately be both a concrete primer and a source of general theory.

**Built:** `tools/articles.py::record_strategy_article(url, title, text, category, commander_names, topic_tags, published_date)` — same delete-then-reinsert-on-re-record semantics as `record_player_theory`/`chunk_announcement`, registered as an MCP tool in `server.py`. `search_strategy_articles(query, category, topic_tags)` wraps `search_content_chunks()`, which gained an optional `topic_tags` filter (`$in` match) and a new index on `content_chunks.topic_tags`.

**Ingestion mechanics — refined after the first real run, 2026-07-07:** WebFetch is fine for scouting (e.g. finding a linked decklist) but runs pages through a smaller model rather than returning literal text — good for summaries, not for what gets stored. **Standard practice (documented in `CLAUDE.md`): ask John for a PDF print or pasted raw text of the article for actual ingestion**, and read that directly instead. `title`/`commander_names`/`topic_tags` get worked out conversationally with John, not inferred solo.

**First real article ingested and verified live 2026-07-07:** airza.net's "Only One Bear Can Be King: Wilson/Noble Heritage in Commander" (John supplied a PDF print after WebFetch's paraphrase was judged insufficient) — 19 chunks, `category: primer`, `commander_names: ["Wilson, Refined Grizzly", "Noble Heritage"]`, `topic_tags: ["damage-race-math", "multiplayer-1v1v1v1-thinking", "reading-table-flow", "punish-passive-value", "table-politics-diplomacy"]`. The tag design was validated directly against the article's own stated thesis ("Magic shouldn't be a 3v1... Seeing the flow of the game on board") rather than John's paraphrase of it. Recorded via raw MCP JSON-RPC against the pangolin server (same validation method as `player_theory`, since the harness's own tool index doesn't refresh mid-session after a deploy/restart) and confirmed in Mongo. Joins against the two `reference_decklists` rows (both already carry the same `source_url`) — the "which decklists does this article link" query needs no schema change, both collections already carry `source_url`.

| Source | Status | Collection(s) | Notes |
|---|---|---|---|
| Web strategy articles + commander/archetype primers | ✅ Built and validated end-to-end 2026-07-07 (first real article ingested) | `content_chunks` (`category: strategy_article` \| `primer`) | See design writeup above. |
| Well-organized/effortful Reddit posts | 📋 Planned | `content_chunks` (`category: reddit_post`) | Distinguished from Reddit *comments* (deferred, short-form) by length/structure, not just source — a long deck-tech post belongs here. Own planning session, not resolved by the strategy_article/primer work above. |
| John's own long-form theory essays (e.g. bracket-system philosophy vs. local meta reality) | ✅ Built + verified live 2026-07-07 | `content_chunks` (`category: player_theory`) | Structurally the same as any other long-form source — reuses `chunk_text()` unchanged, just authored by John instead of scraped from a site. No fetch/parse client needed. **`record_player_theory(title, text)`** (`tools/theory.py`, registered in `server.py`) slugifies `title` into a synthetic stable key (e.g. `internal://player_theory/bracket-system-philosophy`) used with `replace_content_chunks()`, so re-recording under the same title cleanly replaces stale content instead of accumulating duplicates — same delete-then-reinsert semantics as a revised WotC announcement. `published_date` is set to the record-time timestamp (no natural publish date for an authored essay). **`search_player_theory(query)`** wraps `search_content_chunks(query, category="player_theory")`, no new search infra. Built through back-and-forth conversation with the agent, not John sitting down and authoring solo — mirrors the `player_preferences` in-session capture pattern. **First real entry recorded and end-to-end verified 2026-07-07:** "Bracket System Philosophy: My Approach vs. WotC Guidelines" — John's decimal-bracket system (`.9`/`.5` nuance vs. WotC's flat 1-5), where the official bracket text holds up (hard card-choice restrictions) vs. breaks down (subjective turns-to-win/pressure expectations, with common B2-in-name-only patterns like commander clones + effect doublers and stacked Blood Artist/Impact Tremors effects as concrete examples), built through the same conversational back-and-forth as `player_preferences`. Deployed to pangolin and round-tripped via raw MCP JSON-RPC (`record_player_theory` → `search_player_theory`) to confirm the write/chunk/index/search pipeline works end-to-end, since the harness's own tool index doesn't refresh mid-session after a server restart. |

**Short-form (low-context, low word count, no inherent structure) — deferred as a category, see above:**

| Source | Status | Collection(s) | Notes |
|---|---|---|---|
| John's personal game recaps | ✅ Live (as data) / 📋 Deferred (as CW text) | `game_history.notes` today; candidate for `content_chunks` later | Already the CW half of the Dual HD+CW `game_history` row above — folds into the short-form/social-media architecture pass, not scheduled separately |
| Reddit comments (r/EDH etc.) | 📋 Deferred | `content_chunks` (category TBD) | Blocked on the short-form/threading architecture decision, deliberately picked up after long-form primers/articles land |
| Discord messages | 📋 Deferred | `content_chunks` (category TBD) | Mentioned as a future prose source in `chunking.py` docstring; same deferral as Reddit comments |

### Reference decklists — built and validated end-to-end 2026-07-07

**First working example:** Wilson, Refined Grizzly // Noble Heritage, linked from [airza.net's "Ursine Madness"](https://airza.net/2023/08/20/ursine-madness) (two Moxfield decks: a budget build and an optimized build). Chosen as the concrete test case before shaping the `primer`/`strategy_article` CW category — decklist ingestion first, article text ingestion second (also now built, see below).

**Why this can't be a Scryfall-style direct fetch.** Confirmed 2026-07-07: Moxfield blocks both an unauthenticated WebFetch and a bare `curl` against `api2.moxfield.com` (403 in both cases) — only the browser extension's authenticated, credentialed `fetch()` from an active Moxfield session works. So this category is fundamentally extension-driven, same as John's own decks.

**The gap this closed:** before this build, the `/sync-deck` HTTP endpoint had no concept of "not John's deck" — any public Moxfield URL synced through the extension got auto-slugged and written into the `decks` collection as if it were one of John's own (`server.py`'s fallback slug-generation path). That's now a routing decision, not just a display one.

**Own vs. reference — decided by comparing owner username, not a manual toggle (2026-07-07).** `MOXFIELD_USERNAME` (new env var, see `CLAUDE.md`) holds John's own Moxfield username (`terrisare`). `moxfield.extract_owner_username(deck_data)` reads the authenticated deck payload's `createdByUser.userName` (falling back to `displayName`) — **confirmed working against real payloads same-day**: both airza.net decks resolved `owner_username: "airza"` correctly. `/sync-deck` treats a deck as John's own if it's already known (in `decks.yaml` or previously synced into `decks`) *regardless* of the username check — this is the safety fallback if `MOXFIELD_USERNAME` is unset or the field name turns out wrong, so existing own-deck syncing can't silently break. Only decks that are both unknown *and* owned by a different username route to `reference_decklists`.

**Storage — deliberately lighter than `decks`.** Reused `enrich_deck_cards()` (factored out of `sync_deck()` in `tools/decks.py`, shared by both paths — same Scryfall enrichment, Moxfield tags, and price lookups) but skipped everything `decks` carries that only makes sense for John's own decks: no `slug` (keyed by `moxfield_id` directly — these aren't referenced by name anywhere yet), no Notion push, no `decks.yaml` involvement, no `bracket`/`working_notes`. New `tools/reference_decks.py::sync_reference_deck()`, new `mongodb.upsert_reference_decklist()`/`get_reference_decklist()`.

**Schema — `reference_decklists`, one document per Moxfield deck:**
```json
{
  "moxfield_id": "iCYfrphZoE2nA2JLe8mDrQ",
  "owner_username": "...",
  "name": "Wilson, Refined Grizzly", "title": "...",
  "moxfield_updated_at": "...",
  "commanders": [...], "mainboard": [...], "maybeboard": [...],
  "stats": {...},
  "source_url": "https://airza.net/2023/08/20/ursine-madness",
  "last_synced": "..."
}
```
Unique index on `moxfield_id`; secondary index on `source_url` (so "all decklists this article linked" is a single query once article ingestion exists).

### Reference decklists Phase 1+2 — typed schema + auto-tags, built and verified live 2026-07-10

Extends the 2026-07-07 build above with a `type` field and conservative auto-generated `strategy_tags`, per the MVP plan's 3-type schema (`opponent_meta` / `design_exemplar` / `primer_reference`).

**Schema addition:**
```json
{
  ...,
  "type": "opponent_meta" | "design_exemplar" | "primer_reference" | null,
  "strategy_tags": ["..."]
}
```

**`generate_strategy_tags()` (`tools/reference_decks.py`)** — reuses existing Scryfall Tagger data already attached to each mainboard card (`entry["scryfall_tags"]`, from `mongodb.get_tags_for_oracle_ids()`) rather than reimplementing oracle-text pattern matching: counts tag frequency across the mainboard, keeps labels appearing on 5+ cards, returns top 5. Regenerated on every sync (no backfill/migration needed when the logic improves — just re-sync).

**Extension (`chrome_extension/popup.html`/`popup.js`)** gained a deck-type dropdown (blank = "don't change the stored type," not "unset it" — confirmed via a deliberate blank re-sync 2026-07-10) and now defaults `source_url` to the current Moxfield tab's URL instead of requiring manual entry (still overridable to point at an article). `owner_username` is *not* a manual field — it's already auto-derived server-side from `createdByUser`, confirmed correct against a real payload.

**Bug fixed 2026-07-10:** the "already up to date" skip path (when `moxfield_updated_at` is unchanged) used to return early before ever applying new `source_url`/`type`/`owner_username` values from a re-sync — a re-sync done purely to attach metadata silently did nothing. Fixed via `mongodb.update_reference_decklist_metadata()`, applied inside the skip branch without redoing card enrichment.

**Verified live 2026-07-10:** Cam's Myrkul B2 ("Eldritch Enchantment," `owner_username: cptkitsune`, moxfield_id `towXSZizDEe_N-G_lTa0rw`) synced as `opponent_meta` with `source_url` auto-populated and `strategy_tags` generated from real Scryfall Tagger data.

**Known gap, deliberately deferred:** the top-5-by-frequency tag selection currently surfaces overly generic mechanical tags (e.g. "activated ability," "triggered ability") over archetype-shaped ones (e.g. reanimation/graveyard-recursion), since broad tags trivially clear the 5-card threshold. Blocked on the general outstanding Scryfall-tag filtering/sorting work (an archetype-vs-mechanical-property distinction beyond `tag_filters.py`'s current gameplay-only filter) — not a reference-decklists-specific fix. Re-sync affected decks once that lands to regenerate tags.

**Not yet built (post-Phase 2, still open):**
- **Phase 3 — CLI tag refinement tool** (`tune_reference_deck_tags(moxfield_id)`): surface a deck's auto-tags to John for approve/modify/delete, then persist via `mongodb.update_reference_decklist_tags()` (already built, unused).
- **Phase 4 — comparison tools**: `compare_deck_to_reference(my_slug, ref_moxfield_id)` for `opponent_meta` power-level/effect-density comparisons; `compare_deck_to_reference_group(my_slug, commander_name, type="design_exemplar")` for card-inclusion-pattern analysis against multiple exemplars. `mongodb.get_reference_decklists_by_type()`/`get_reference_decklists_by_commander()` (already built, unused) are the query layer these would sit on.
- No MCP read tool over `reference_decklists` exists yet at all beyond raw Mongo lookups — same gap noted in the 2026-07-07 entry above, still open.

**Source-article linking — built and populated.** The extension's popup gained an optional "source URL / note" text field; whatever's typed there is sent as `source_url` in the `/sync-deck` POST body and stored verbatim (no automatic capture — the extension only sees the Moxfield tab, not whatever tab the article was read in — John pasted the article URL by hand for both decks). This is now the confirmed join key against the `strategy_article`/`primer` CW category (see below): both decks and the article chunk share `source_url: "https://www.airza.net/2023/08/20/ursine-madness"`.

**Not yet built:** any MCP read tool over `reference_decklists` (e.g. "what decks did this article link" or "how does my Breya list compare to this reference build") — the ingestion path itself is validated (real extension sync, both decks confirmed correctly routed and stored), but nothing queries this collection yet beyond raw Mongo lookups.

## Open questions for the next planning pass

- **Usage-frequency library**: resolved 2026-07-06 as **EDHREC-only** (Commander Spellbook's `popularity` is combo-level, not commander-scoped) and **built 2026-07-07** — see the EDHREC section above for the shipped `card_usage_stats`/`edhrec_commander_meta` schema.
- **Personal preference corpus capture mechanism**: resolved and **built 2026-07-07** — in-session flagging, see the `player_preferences` row above.
- **`content_type` as schema concept**: resolved 2026-07-07 — documentation-level grouping only (`CATEGORY_CONTENT_TYPE` lookup, not a stored field). See above.
- **Short-form/social-media chunking architecture (4th tier)**: deferred 2026-07-07 until after long-form primer/article ingestion lands. See deferral note above.
- Where's the line between "EDHREC synergy data" and "other people's decklists" when EDHREC recs are themselves derived from aggregated decklists?
- Priority order for the remaining planned CW sources (other decklists / Commander's Herald / future primers / player_theory) — which unblocks the most useful agent behavior first?
