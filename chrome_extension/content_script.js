// Auto-fires on every deckcheck.co/app/deckview/<id> page load. No user action
// required — John already navigates here to read the analysis himself.

(function () {
  const match = window.location.pathname.match(/\/app\/deckview\/([A-Za-z0-9]+)/);
  const deckviewId = match ? match[1] : null;
  if (!deckviewId) return;

  chrome.runtime.sendMessage({ type: "deckcheck-analysis-detected", deckviewId });
})();
