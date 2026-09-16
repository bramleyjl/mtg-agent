// Auto-captures DeckCheck.co AI analysis whenever content_script.js relays a
// deck-data fetch caught by page_fetch_hook.js — no popup interaction
// involved. Confirms success/failure via the toolbar badge only (see setBadge
// below), matching the plan's "zero-click, lightweight confirmation" design.
//
// As of 2026-09-16 the deck-data payload is captured directly from the page's
// own fetch (see page_fetch_hook.js) rather than fetched here a second time —
// DeckCheck's builder view now shows analysis as an in-page modal instead of
// navigating to a separate deckview page, so there's no stable deckview id to
// re-fetch by; the builder id in the page URL is what the payload is keyed on.

const DEFAULT_SERVER = "http://YOUR_SERVER_IP:8765";
const DEFAULT_LOCAL = "http://localhost:8765";

async function getSettings() {
  return new Promise(resolve => {
    chrome.storage.local.get(
      { serverUrl: DEFAULT_SERVER, localUrl: DEFAULT_LOCAL },
      resolve
    );
  });
}

function setBadge(text, color) {
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color });
  if (text) {
    setTimeout(() => chrome.action.setBadgeText({ text: "" }), 5000);
  }
}

async function postToServer(serverUrl, payload) {
  const res = await fetch(`${serverUrl.replace(/\/$/, "")}/sync-deckcheck-analysis`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await res.json();
  if (!res.ok) throw new Error(result.error || String(res.status));
  return result;
}

async function handleDeckDataDetected(deckId, deckData) {
  try {
    const payload = { deck_id: deckId, deck_data: deckData };

    const settings = await getSettings();
    const targets = [settings.serverUrl];
    if (settings.localUrl && settings.localUrl !== settings.serverUrl) {
      targets.push(settings.localUrl);
    }

    const results = await Promise.allSettled(targets.map(url => postToServer(url, payload)));
    const anyOk = results.some(r => r.status === "fulfilled" && !r.value.error);
    const allOk = results.every(r => r.status === "fulfilled" && !r.value.error);

    setBadge("OK", allOk ? "#16a34a" : anyOk ? "#eab308" : "#dc2626");
  } catch (err) {
    console.error("DeckCheck analysis sync failed:", err);
    setBadge("!", "#dc2626");
  }
}

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "deckcheck-analysis-detected" && message.deckId && message.deckData) {
    handleDeckDataDetected(message.deckId, message.deckData);
  }
});
