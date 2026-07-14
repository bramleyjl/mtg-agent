// Fires whenever the page lands on deckcheck.co/app/deckview/<id> — both on a
// real page load AND on an in-app SPA route change (DeckCheck is a single-page
// app, so navigating from the builder to a deckview page after "Analyze" is
// usually a pushState transition, not a full page load, which a plain
// document-load content script would silently miss).

(function () {
  let lastSentId = null;

  function checkAndSend() {
    const match = window.location.pathname.match(/\/app\/deckview\/([A-Za-z0-9]+)/);
    const deckviewId = match ? match[1] : null;
    if (!deckviewId || deckviewId === lastSentId) return;

    lastSentId = deckviewId;
    chrome.runtime.sendMessage({ type: "deckcheck-analysis-detected", deckviewId });
  }

  const originalPushState = history.pushState;
  history.pushState = function (...args) {
    originalPushState.apply(this, args);
    checkAndSend();
  };

  const originalReplaceState = history.replaceState;
  history.replaceState = function (...args) {
    originalReplaceState.apply(this, args);
    checkAndSend();
  };

  window.addEventListener("popstate", checkAndSend);

  checkAndSend();
})();
