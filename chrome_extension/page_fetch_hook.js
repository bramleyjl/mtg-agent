// Runs in the page's MAIN world (declared via manifest.json's "world": "MAIN"),
// not the content script's isolated world — content scripts can't see or patch
// the page's own window.fetch, since isolated/main worlds share the DOM but not
// JS globals. DeckCheck's builder page now shows the full AI analysis as an
// in-page modal ("Full Synopsis") rather than navigating to a separate
// /app/deckview/<id> page, so there's no URL change left to watch for — this
// intercepts the actual data fetch instead, which fires regardless of how the
// UI chooses to display it.
//
// Confirmed 2026-09-16: the modal's data comes from
// GET /api/dc3/deck-data/<builderId> — <builderId> is the same id already
// sitting in the page URL (e.g. deckcheck.co/app/builder/<builderId>), not a
// separate per-analysis "deckview id" that orphans on re-analysis like the old
// /app/deckview/<id> flow did. That resolves the "each re-analysis mints a new
// id" problem entirely (see docs/data_sources_roadmap.md's Deckcheck section).

(function () {
  const DECK_DATA_RE = /\/api\/dc3\/deck-data\/([A-Za-z0-9]+)/;
  const originalFetch = window.fetch;

  window.fetch = async function (...args) {
    const response = await originalFetch.apply(this, args);

    try {
      const url = typeof args[0] === "string" ? args[0] : args[0]?.url;
      const match = url && url.match(DECK_DATA_RE);
      if (match && response.ok) {
        const deckId = match[1];
        response
          .clone()
          .json()
          .then((data) => {
            window.postMessage({ source: "mtg-agent-deckcheck-hook", deckId, data }, "*");
          })
          .catch(() => {});
      }
    } catch {
      // Never let hook errors break the page's own fetch.
    }

    return response;
  };
})();
