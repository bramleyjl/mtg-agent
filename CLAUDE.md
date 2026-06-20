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
- Custom MCP server (planned) — exposes knowledge base tools to Claude

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
