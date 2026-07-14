// Auto-captures DeckCheck.co AI analysis whenever content_script.js detects a
// deckview page load — no popup interaction needed. Confirms success/failure
// via the toolbar badge only (see setBadge below), matching the plan's
// "zero-click, lightweight confirmation" design.

const DEFAULT_SERVER = "http://YOUR_SERVER_IP:8765";
const DEFAULT_LOCAL = "http://localhost:8765";
const DECKCHECK_API = "https://web-production-ec9b0.up.railway.app";

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

async function fetchJson(url) {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${url} returned ${res.status}`);
  return res.json();
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

async function handleDeckviewDetected(deckviewId) {
  try {
    const [deckSummary, attributeRatings] = await Promise.all([
      fetchJson(`${DECKCHECK_API}/api/dc3/deck-summary/${deckviewId}`),
      fetchJson(`${DECKCHECK_API}/api/dc3/deck-stats/${deckviewId}?stats=attribute_ratings`),
    ]);

    const payload = { deckview_id: deckviewId, deck_summary: deckSummary, attribute_ratings: attributeRatings };

    const settings = await getSettings();
    const targets = [settings.serverUrl];
    if (settings.localUrl && settings.localUrl !== settings.serverUrl) {
      targets.push(settings.localUrl);
    }

    const results = await Promise.allSettled(targets.map(url => postToServer(url, payload)));
    const anyOk = results.some(r => r.status === "fulfilled" && !r.value.error);
    const allOk = results.every(r => r.status === "fulfilled" && !r.value.error);

    setBadge("✓", allOk ? "#16a34a" : anyOk ? "#eab308" : "#dc2626");
  } catch (err) {
    console.error("DeckCheck analysis sync failed:", err);
    setBadge("!", "#dc2626");
  }
}

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "deckcheck-analysis-detected" && message.deckviewId) {
    handleDeckviewDetected(message.deckviewId);
  }
});
