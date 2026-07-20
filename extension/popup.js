document.getElementById("fill").addEventListener("click", async () => {
  const status = document.getElementById("status");
  status.textContent = "Vérification du serveur local…";
  // le serveur "cerveau" tourne-t-il ?
  const health = await new Promise((res) =>
    chrome.runtime.sendMessage({ type: "api", method: "GET", path: "/api/health" }, res)
  );
  if (!health || !health.ok) {
    status.textContent = "⚠️ Serveur local injoignable. Lance : python apiserver.py";
    return;
  }
  status.textContent = "Remplissage en cours… (regarde la page)";
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
    status.textContent = "✅ Lancé. Le panneau sur la page montre le résultat.";
  } catch (e) {
    status.textContent = "Erreur : " + e.message;
  }
});
