// Fires whenever the page lands on deckcheck.co/app/deckview/<id> — both on a
// real page load AND on an in-app SPA route change (DeckCheck is a single-page
// app, so navigating from the builder to a deckview page after "Analyze" is
// usually a pushState transition, not a full page load, which a plain
// document-load content script would silently miss).

(function () {
  console.log("[mtg-agent] content_script.js injected on", window.location.href);
  let lastSentId = null;

  function checkAndSend() {
    const match = window.location.pathname.match(/\/app\/deckview\/([A-Za-z0-9]+)/);
    const deckviewId = match ? match[1] : null;
    console.log("[mtg-agent] checkAndSend", { path: window.location.pathname, deckviewId, lastSentId });
    if (!deckviewId || deckviewId === lastSentId) return;

    lastSentId = deckviewId;
    console.log("[mtg-agent] sending deckcheck-analysis-detected for", deckviewId);
    chrome.runtime.sendMessage({ type: "deckcheck-analysis-detected", deckviewId }, (response) => {
      if (chrome.runtime.lastError) {
        console.error("[mtg-agent] sendMessage error:", chrome.runtime.lastError.message);
      }
    });
  }

  const originalPushState = history.pushState;
  history.pushState = function (...args) {
    originalPushState.apply(this, args);
    console.log("[mtg-agent] pushState ->", window.location.pathname);
    checkAndSend();
  };

  const originalReplaceState = history.replaceState;
  history.replaceState = function (...args) {
    originalReplaceState.apply(this, args);
    console.log("[mtg-agent] replaceState ->", window.location.pathname);
    checkAndSend();
  };

  window.addEventListener("popstate", () => {
    console.log("[mtg-agent] popstate ->", window.location.pathname);
    checkAndSend();
  });

  checkAndSend();
})();
