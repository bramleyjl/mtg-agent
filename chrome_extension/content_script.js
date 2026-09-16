// Relays deck-data payloads captured by page_fetch_hook.js (running in the
// page's MAIN world) to background.js. Content scripts run in an isolated
// world — they share the DOM with the page but not JS globals, so they can't
// intercept the page's own fetch calls directly; page_fetch_hook.js does that
// and hands off via window.postMessage, which both worlds can see.

(function () {
  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const msg = event.data;
    if (msg?.source !== "mtg-agent-deckcheck-hook" || !msg.deckId || !msg.data) return;

    chrome.runtime.sendMessage({
      type: "deckcheck-analysis-detected",
      deckId: msg.deckId,
      deckData: msg.data,
    });
  });
})();
