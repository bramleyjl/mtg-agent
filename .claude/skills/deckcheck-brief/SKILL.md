---
name: deckcheck-brief
description: Condense one of John's decks' working_notes into a short paste-ready brief for DeckCheck.co's "Know this deck?" AI-guidance box. Invoke when John wants a DeckCheck context blurb for a deck (e.g. "give me a DeckCheck brief for Atemsis", "summarize this deck for DeckCheck", "/deckcheck-brief").
---

# DeckCheck Brief

Turns a deck's recorded `working_notes` into a short blurb sized for DeckCheck.co's
"Know this deck? Use this to guide the AI" free-text box (see the confirm-action
dialog: a single small textarea, not a document upload). The box exists to correct
DeckCheck's CRISPI heuristics where they'd otherwise misread the deck — see
`CLAUDE.md`'s "DeckCheck / CRISPI Caveats" section, especially the Rem Karolus
example where DeckCheck couldn't see a play-pattern-based strategy from the card
list alone. This skill's whole point is feeding CRISPI exactly the context it's
blind to, in the space it's given.

## Step 1 — Pull working_notes

Call `get_deck_notes(slug)` (resolve slug via `list_decks`/`get_deck` if John
names the deck informally). Pull from these sections only:

- **Theme / Strategy** — the core gameplan. This is the backbone of the brief.
- **Combos** — only combo lines worth flagging explicitly: ones that are
  non-obvious from the card list, or that CRISPI is likely to either miss or
  overrate in isolation (e.g. a combo that looks stronger/weaker out of context
  than it plays in practice given the deck's actual pacing).

Do not pull Weaknesses, Restraints, Current Focus, Recurring Patterns, or Turns
to Win into the brief — those are useful for `deck-analyst`-style internal review
but out of scope for what DeckCheck's box is for (guiding its read of the
strategy, not a full deck audit) and there isn't room for them anyway.

## Step 2 — Draft the brief

Write 2-4 sentences, plain prose, no markdown formatting (the box is plain text):

1. One sentence naming the actual win condition / gameplan in concrete terms —
   prefer the language of "how games actually play out" over abstract archetype
   labels, since that's precisely the read CRISPI tends to miss.
2. If there's a load-bearing combo or interaction the card list alone
   undersells or oversells, name it and say what it actually does in-game.
3. Optionally, one sentence on anything else that would make CRISPI misjudge a
   card's role (e.g. a piece that looks like an isolated value engine but is
   actually the payoff, or a card whose printed text reads as symmetric but is
   asymmetric in practice at John's tables).

Keep it tight — this is a guidance hint, not a full explainer. If working_notes'
Theme/Strategy section is still unfilled in (`_Not yet filled in..._`), say so
and ask John to describe the strategy conversationally instead of guessing.

## Step 3 — Present and confirm

Show the drafted brief plainly (as the literal text to paste, not wrapped in
extra commentary) and ask if John wants wording changes before he pastes it in.
This skill does not write anywhere — output is just the paste-ready text.
