---
name: log-game
description: Conduct a post-session conversation about Commander games John just played and write the resulting game record(s) to the Notion "EDH Game Records" database, synced into MongoDB. Invoke when John wants to log/record a game or session (e.g. "let's log tonight's games", "I want to record a game", "/log-game").
---

# Log Game

Turns a conversational recap of one or more Commander games into structured records in Notion's "EDH Game Records" database (data source `0a966574-64e4-4036-93b3-a3f8461ef9d0`), synced into MongoDB's `game_history` collection. Built 2026-07-23 after doing this end-to-end for the first time; refine in place as gaps show up rather than working around it silently.

**Core rule: draft before writing, every time.** Never write directly to Notion mid-conversation. Elicit details, produce a draft (properties + recap body) per game, let John review/edit it, and only write after he confirms. This applies to corrections of my own drafts too, not just first-pass content.

## Step 1 — Elicit game details

For each game played, get:
- Which deck John played (slug via `list_decks`/`get_deck` if unsure).
- Opponents' commanders — **get exact full names, don't guess.** Named legends can have multiple distinct unique cards sharing a first name (e.g. "Zimone, Infinite Analyst" vs "Zimone, Mystery Unraveler" are different real cards) — if a name isn't already a known Enemy Commanders option and there's any ambiguity, confirm the exact card rather than matching to the nearest existing multi-select value.
  - **Partner/paired commanders** are one option using both full names joined by ` // ` (commas stripped), e.g. `Kraum Ludevic's Opus // Rebbec Architect of Ascension`. Older options use inconsistent short forms (`Rograkh/Akroma`, `Tana/Reyhan`) — leave those as-is, but use the full-name form for any new pair.
- Outcome (who won).
- Notable plays/cards/turning points, for the free-text recap.
- **Seat Order** (1-4, which seat John was in) and **Turn Ended** (approximate is fine — John is often guessing, e.g. "like 11-12") — ask for these explicitly as part of the schema, don't wait for them to be volunteered. Both are optional/nullable if John doesn't know or doesn't want to log them for a given game.

Don't ask about `Opponents` (human player names) — John has declined syncing that property; it's Notion-only bookkeeping he may or may not fill in himself.

## Step 2 — Draft

For each game, present:
- **Title**: `"YYYY-MM-DD G#"` — G# counts across all decks/pods that calendar date (not per-deck), so check how many games are already being logged today in this session.
- **Date**: the date the game was played (not necessarily today — backlogged games from earlier in the week are common).
- **Deck**: the relation target (deck's `notion_id`, from `get_deck`).
- **Winner**: full canonical commander name.
- **Enemy Commanders**: full canonical names.
- **Seat Order** / **Turn Ended**: from Step 1, if given.
- **Recap body**: a few paragraphs of prose covering the game's arc and standout plays — this is the free-text record John reads back later, so make it complete enough to jog his memory, not a terse log line.

Show this draft plainly and wait for edits/confirmation before writing anything.

## Step 3 — Check for new Enemy Commanders options

`Enemy Commanders` and `Winner` are closed-option Notion `select`/`multi_select` fields — an unrecognized value is rejected by `notion-create-pages`/`notion-update-page`, not silently added. Before writing:

1. Fetch the current schema: `notion-fetch` on `0a966574-64e4-4036-93b3-a3f8461ef9d0` (large result — expect it to spill to a file; grep/slice rather than reading inline, or delegate to a subagent).
2. Extract the full current `Enemy Commanders` and `Winner` option lists (name/color pairs) from the schema dump — they're JSON inside escaped text; unescape `\"` and parse the `"options":[...]` array under each property rather than regex-matching names. **Option names have commas stripped** (Notion disallows commas in options): "Korlessa, Scale Singer" is stored as `Korlessa Scale Singer`, so match on that form and write values that way too.
3. **`Enemy Commanders` is over Notion's 100-option API cap** (237+ options), so step 4 below will always be rejected for it — skip straight to giving John a manual-add list for the new names, and hold any game whose opponents include them until he confirms they're added (write the unaffected games right away). `Winner` is still under the cap (~80), so the full-list update is possible there — but many existing option names contain apostrophes (e.g. `Caesar Legion's Emperor`) and quote-escaping in the DDL string is untested; a mis-escape would rename options existing games use. Until that's verified, prefer adding new `Winner` options to John's manual-add list too, batched with any Enemy Commanders additions.
4. If any confirmed opponent commander isn't already an option, call `notion-update-data-source` with `ALTER COLUMN "Enemy Commanders" SET MULTI_SELECT(...)` passing the **entire existing option list plus the new entries** — omitting existing options silently drops them from the schema. Pick any valid Notion multi-select color for new entries (`default, gray, brown, orange, yellow, green, blue, purple, pink, red`).
5. Same check applies to `Winner` (a `select`, not `multi_select`, but the same closed-option constraint). It holds both John's commanders and opponents' commanders who won, so any loss to a first-time winner needs a new option.

## Step 4 — Write

- `notion-create-pages` (parent: `data_source_id: "0a966574-64e4-4036-93b3-a3f8461ef9d0"`) for each new game. The title property is `Title` (not `Name`). Properties use the expanded date key `date:Date:start` (a bare `Date` value is rejected), and `Deck` takes an array with the deck page's notion_id.
- For post-write corrections (e.g. John catches an error in what I already wrote), use `notion-update-page` — `update_properties` for property fixes, `update_content` with `content_updates` (old_str/new_str) for targeted body text fixes.

## Step 5 — Sync to MongoDB

Call `sync_game_history(slug)` for every deck touched. If any property was corrected via `update_page` **after** an initial sync already ran for that game_id, re-run with `force=True` — incremental sync skips already-known game IDs entirely, so a plain sync won't pick up the correction.

## Step 6 — Confirm

Summarize what was written (deck, opponents, outcome) and note anything mechanical that happened along the way (e.g. new Enemy Commanders options added), same as a normal end-of-session recap.
