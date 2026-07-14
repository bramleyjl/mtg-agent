# Deck Working Notes — Template

This is the **single authoritative structure** for every deck's `working_notes`
document (Notion page body, mirrored into MongoDB's `decks.working_notes`).
There is no code-level constant enforcing this — `update_deck_working_notes(slug, notes)`
(`tools/decks.py`) accepts free-text `notes` and writes it verbatim — so this file,
not any `.py`/`.yaml` constant, is the thing to check and edit when the structure
itself needs to change. See `docs/data_sources_roadmap.md`'s "Per-deck working
notes / analysis journal" entry for the full design rationale.

Every section except **Combos** is written/edited through conversation with John,
never inferred from the decklist alone. Copy the block below verbatim as the
starting point for any deck that doesn't have a working_notes doc yet.

```markdown
# Theme / Strategy

_Not yet filled in — to be added through conversation, not inferred._

# Strengths

_Not yet filled in — to be added through conversation, not inferred._

# Weaknesses / Vulnerabilities

_Not yet filled in — to be added through conversation, not inferred._

# Restraints

_Not yet filled in — to be added through conversation, not inferred._

# Current Focus / Improvement Areas

_Not yet filled in — to be added through conversation, not inferred._

# Recurring In-Game Patterns

_Not yet filled in — to be added through conversation, not inferred._

# Turns to Win

_Not yet filled in — to be added through conversation, not inferred._

# Combos

_Not yet computed — run resync_deck_combos(slug) or sync_deck(slug)._

# Similar Decklists by Other Players

_Not yet filled in — to be added through conversation, not inferred._
```

## Section notes

- **Restraints** — self-imposed play-pattern limits that hold power level down.
  Most relevant at Bracket 2 and below, where what John *deliberately avoids
  doing* defines the bracket as much as what the deck can do.
- **Turns to Win** — rough/soft metric, mostly from goldfishing. Not a hard
  constraint, especially for John's typically slower decks.
- **Combos** — the one machine-maintained section. Regenerated automatically
  from Commander Spellbook data by `decks.resync_deck_combos(slug)` (also
  exposed as the `resync_deck_combos` MCP tool), which is called automatically
  by `sync_deck()` whenever a deck's card list actually changes. Rendered by
  `combos.render_combos_section()` as a markdown table (cards / produces /
  popularity percentile / identity percentile). Popularity is Commander
  Spellbook's own score — an EDHREC-derived inclusion count — not Commander's
  Herald data. Popularity %ile ranks that score against every commander-legal
  combo in the format; Identity %ile (added 2026-07-13) ranks it only against
  combos whose color identity fits within this deck's own colors — a fairer
  "how good is this given what I could ever assemble" read, since the unscoped
  percentile just rewards combos needing fewer colors. Never hand-edit this
  section; a manual edit here will just get overwritten on the next sync.
  **Resolved 2026-07-13:** `notion-mcp` initially had no markdown table support,
  so writes through the normal `mtg-agent` → `notion-mcp` path failed/degraded —
  Kykar's Combos section was written by hand through the official Notion
  connector as a temporary workaround. `notion-mcp` has since been updated with
  proper table support; all populated templates now write correctly through the
  normal path.
- **Similar Decklists by Other Players** — plain links, no summary text needed.
