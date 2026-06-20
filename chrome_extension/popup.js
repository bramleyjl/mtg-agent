const DEFAULT_SERVER = "http://192.168.0.102:8765";

const statusEl = document.getElementById("status");
const syncBtn = document.getElementById("syncBtn");
const serverInput = document.getElementById("serverUrl");

function setStatus(msg, type = "") {
  statusEl.textContent = msg;
  statusEl.className = type;
}

// Moxfield deck URLs: https://www.moxfield.com/decks/<publicId>[-optional-title]
// The publicId is a 22-char base64url string before any hyphen that follows it.
function extractDeckSlug(url) {
  const match = url.match(/moxfield\.com\/decks\/([A-Za-z0-9_-]+)/);
  if (!match) return null;
  // The full slug (including any title suffix) works with the Moxfield API
  return match[1];
}

async function getServerUrl() {
  return new Promise(resolve => {
    chrome.storage.local.get({ serverUrl: DEFAULT_SERVER }, data => {
      resolve(data.serverUrl.replace(/\/$/, ""));
    });
  });
}

async function init() {
  const { serverUrl } = await new Promise(resolve =>
    chrome.storage.local.get({ serverUrl: DEFAULT_SERVER }, resolve)
  );
  serverInput.value = serverUrl;

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const slug = tab?.url ? extractDeckSlug(tab.url) : null;

  if (!slug) {
    setStatus("Open a Moxfield deck page to sync it.");
    return;
  }

  setStatus(`Ready to sync deck.`);
  syncBtn.disabled = false;
  syncBtn.addEventListener("click", () => syncDeck(slug));
}

async function syncDeck(slug) {
  syncBtn.disabled = true;
  setStatus("Fetching deck from Moxfield...");

  const serverUrl = await getServerUrl();

  let deckData;
  try {
    const res = await fetch(`https://api2.moxfield.com/v3/decks/all/${slug}`, {
      credentials: "include",
    });
    if (!res.ok) {
      if (res.status === 401 || res.status === 403) {
        setStatus("Not logged in to Moxfield. Open moxfield.com and log in first.", "error");
      } else {
        setStatus(`Moxfield returned ${res.status}. Is the deck public?`, "error");
      }
      syncBtn.disabled = false;
      return;
    }
    deckData = await res.json();
  } catch (err) {
    setStatus(`Failed to reach Moxfield: ${err.message}`, "error");
    syncBtn.disabled = false;
    return;
  }

  // Use the canonical publicId from the API response as the moxfield_id
  const moxfieldId = deckData.publicId || slug;
  setStatus("Sending to Pangolin...");

  try {
    const res = await fetch(`${serverUrl}/sync-deck`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ moxfield_id: moxfieldId, deck_data: deckData }),
    });
    const result = await res.json();
    if (!res.ok) {
      setStatus(`Server error: ${result.error || res.status}`, "error");
    } else {
      const name = result.name || result.synced;
      const title = result.title ? ` — ${result.title}` : "";
      setStatus(`Synced: ${name}${title}\n${result.card_count} cards, ${result.enriched} enriched.`, "success");
    }
  } catch (err) {
    setStatus(`Could not reach Pangolin (${serverUrl}). Is it on the same network?`, "error");
  }

  syncBtn.disabled = false;
}

serverInput.addEventListener("change", () => {
  chrome.storage.local.set({ serverUrl: serverInput.value });
});

init();
