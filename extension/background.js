// Service worker : fait les appels au serveur local "cerveau".
// Passer par ici évite les blocages CORS / mixed-content depuis la page.
const BASE = "http://127.0.0.1:8000";

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type !== "api") return;
  const opts = { method: msg.method || "POST", headers: { "Content-Type": "application/json" } };
  if (opts.method === "POST") opts.body = JSON.stringify(msg.body || {});
  fetch(BASE + msg.path, opts)
    .then((r) => r.json())
    .then((data) => sendResponse({ ok: true, data }))
    .catch((e) => sendResponse({ ok: false, error: String(e) }));
  return true; // réponse asynchrone
});
