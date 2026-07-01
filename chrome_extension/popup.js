const DEFAULT_SERVER = "http://YOUR_SERVER_IP:8765";
const DEFAULT_LOCAL  = "http://localhost:8765";

const statusEl   = document.getElementById("status");
const syncBtn    = document.getElementById("syncBtn");
const serverInput = document.getElementById("serverUrl");
const localInput  = document.getElementById("localUrl");

function setStatus(msg, type = "") {
  statusEl.textContent = msg;
  statusEl.className = type;
}

// Moxfield deck URLs: https://www.moxfield.com/decks/<publicId>[-optional-title]
function extractDeckSlug(url) {
  const match = url.match(/moxfield\.com\/decks\/([A-Za-z0-9_-]+)/);
  if (!match) return null;
  return match[1];
}

async function getSettings() {
  return new Promise(resolve => {
    chrome.storage.local.get(
      { serverUrl: DEFAULT_SERVER, localUrl: DEFAULT_LOCAL },
      resolve
    );
  });
}

async function init() {
  const settings = await getSettings();
  serverInput.value = settings.serverUrl;
  localInput.value  = settings.localUrl;

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const slug = tab?.url ? extractDeckSlug(tab.url) : null;

  if (!slug) {
    setStatus("Open a Moxfield deck page to sync it.");
    return;
  }

  setStatus("Ready to sync deck.");
  syncBtn.disabled = false;
  syncBtn.addEventListener("click", () => syncDeck(slug));
}

async function postToServer(url, moxfieldId, deckData) {
  const res = await fetch(`${url}/sync-deck`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ moxfield_id: moxfieldId, deck_data: deckData }),
  });
  const result = await res.json();
  if (!res.ok) throw new Error(result.error || String(res.status));
  return result;
}

async function syncDeck(slug) {
  syncBtn.disabled = true;
  setStatus("Fetching deck from Moxfield...");

  const settings = await getSettings();
  const prodUrl  = settings.serverUrl.replace(/\/$/, "");
  const localUrl = settings.localUrl.replace(/\/$/, "");

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

  const moxfieldId = deckData.publicId || slug;

  // Determine which servers to send to
  const targets = [{ label: "Prod", url: prodUrl }];
  if (localUrl && localUrl !== prodUrl) {
    targets.push({ label: "Local", url: localUrl });
  }

  setStatus(`Syncing to ${targets.map(t => t.label).join(" & ")}...`);

  const results = await Promise.allSettled(
    targets.map(t => postToServer(t.url, moxfieldId, deckData).then(r => ({ ...r, _label: t.label })))
  );

  const lines = [];
  let successCount = 0;

  for (const [i, outcome] of results.entries()) {
    const label = targets[i].label;
    if (outcome.status === "fulfilled") {
      const r = outcome.value;
      const name  = r.name || r.synced || r.skipped || "?";
      const title = r.title ? ` — ${r.title}` : "";
      const suffix = r.skipped ? " (already up to date)" : ` (${r.card_count ?? "?"} cards)`;
      lines.push(`${label}: ${name}${title}${suffix}`);
      successCount++;
    } else {
      lines.push(`${label}: ${outcome.reason?.message ?? "failed"}`);
    }
  }

  const allOk    = successCount === targets.length;
  const noneOk   = successCount === 0;
  const statusType = allOk ? "success" : noneOk ? "error" : "partial";
  setStatus(lines.join("\n"), statusType);

  syncBtn.disabled = false;
}

serverInput.addEventListener("change", () => {
  chrome.storage.local.set({ serverUrl: serverInput.value });
});
localInput.addEventListener("change", () => {
  chrome.storage.local.set({ localUrl: localInput.value });
});

init();
