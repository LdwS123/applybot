// ApplyBot content script — "les mains".
// Lit la page, décide via le serveur local ("cerveau"), remplit. CV exclu (sécurité).
(async () => {
  if (window.__applybot_running) { return; }
  window.__applybot_running = true;

  const api = (path, body, method = "POST") =>
    new Promise((res) =>
      chrome.runtime.sendMessage({ type: "api", method, path, body }, (r) =>
        res(r && r.ok ? r.data : { error: (r && r.error) || "serveur injoignable" })
      )
    );
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const norm = (s) => (s || "").toLowerCase().replace(/\s+/g, " ").trim();

  // ---------- Panneau flottant ----------
  const panel = document.createElement("div");
  panel.style.cssText =
    "position:fixed;bottom:16px;right:16px;width:300px;max-height:70vh;overflow:auto;z-index:2147483647;" +
    "background:#0f1115;color:#e7e9ee;font:13px -apple-system,sans-serif;border:1px solid #2a2e37;" +
    "border-radius:12px;padding:12px;box-shadow:0 8px 30px rgba(0,0,0,.5)";
  panel.innerHTML = '<b>🤖 ApplyBot</b><div id="ab-log" style="margin-top:8px"></div>';
  document.body.appendChild(panel);
  const logEl = panel.querySelector("#ab-log");
  const log = (t, color) => {
    const d = document.createElement("div");
    d.style.cssText = "margin:3px 0;color:" + (color || "#9aa0ad");
    d.textContent = t;
    logEl.appendChild(d);
    logEl.scrollTop = logEl.scrollHeight;
  };

  // ---------- Détection de label (géométrique, multilingue) ----------
  function nearbyText(el) {
    const r = el.getBoundingClientRect();
    if (!r.width && !r.height) return "";
    let best = "", bestDist = 1e9;
    document.querySelectorAll("label,span,div,p,legend,strong,b,h1,h2,h3,h4,h5").forEach((t) => {
      if (t.querySelector("input,textarea,select")) return;
      const txt = (t.innerText || "").trim();
      if (!txt || txt.length > 70) return;
      const tr = t.getBoundingClientRect();
      if (!tr.width || !tr.height) return;
      const above = tr.bottom <= r.top + 6 && r.top - tr.bottom < 70 && Math.abs(tr.left - r.left) < 260;
      const left = tr.right <= r.left + 6 && r.left - tr.right < 260 && Math.abs(tr.top - r.top) < 28;
      if (above || left) {
        const dist = Math.hypot(tr.left - r.left, tr.top - r.top);
        if (dist < bestDist) { bestDist = dist; best = txt; }
      }
    });
    return best;
  }
  function labelOf(el) {
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l && l.innerText.trim()) return l.innerText.trim(); }
    const w = el.closest("label"); if (w && w.innerText.trim()) return w.innerText.trim();
    const a = el.getAttribute("aria-label"); if (a) return a;
    const g = el.closest('.field,[class*="field"],div'); if (g) { const l = g.querySelector("label,legend,.label"); if (l && l.innerText.trim()) return l.innerText.trim(); }
    return el.getAttribute("placeholder") || el.name || nearbyText(el);
  }

  // ---------- Remplissage compatible React ----------
  function reactFill(el, value) {
    try {
      el.focus();
      const proto = el.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
      setter.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      el.blur();
      return el.value === value;
    } catch (e) { return false; }
  }

  // ---------- Contexte de l'offre ----------
  function extractJob() {
    const meta = (n) => (document.querySelector('meta[property="' + n + '"],meta[name="' + n + '"]') || {}).content || "";
    const locEl = document.querySelector('.location,[class*="location"],[class*="Location"]');
    return {
      title: ((document.querySelector("h1") || {}).innerText || document.title || "").trim(),
      company: meta("og:site_name") || "",
      location: locEl ? (locEl.innerText || "").trim().slice(0, 80) : "",
      description: (document.body ? document.body.innerText : "").slice(0, 2000),
      url: location.href,
    };
  }

  const job = extractJob();
  log("Offre : " + (job.title || "?").slice(0, 40), "#7cd");
  if (document.querySelector('input[type="file"]')) log("📎 CV : à joindre à la main (sécurité navigateur)", "#f2cc60");

  // ---------- 1) Champs texte / textarea via /api/plan ----------
  let idx = 0;
  const textFields = [];
  document.querySelectorAll("input,textarea").forEach((el) => {
    const t = (el.type || el.tagName).toLowerCase();
    if (["hidden", "submit", "button", "file", "password", "checkbox", "radio"].includes(t)) return;
    if (el.offsetParent === null) return; // invisible
    el._abid = idx;
    textFields.push({ el, idx, label: labelOf(el).slice(0, 80), tag: el.tagName.toLowerCase(), type: t });
    idx++;
  });
  let filled = 0;
  log("Analyse de " + textFields.length + " champs…");
  const planResp = await api("/api/plan", { job, fields: textFields.map((f) => ({ idx: f.idx, label: f.label, tag: f.tag, type: f.type })) });
  if (planResp.error) { log("⚠️ " + planResp.error, "#f2cc60"); }
  const plan = (planResp && planResp.plan) || {};
  for (const f of textFields) {
    const d = plan[f.idx] || plan[String(f.idx)];
    if (!d || d.action === "skip" || !d.value) continue;
    if (reactFill(f.el, d.value)) { filled++; }
  }
  log("✍️ " + filled + " champs remplis");

  // ---------- 2) Cases à cocher : consentement / certification ----------
  const CONSENT = ["consent", "agree", "i certify", "certify", "acknowledge", "understand", "true and correct", "terms", "privacy", "gdpr", "rgpd", "consentement", "j'accepte"];
  document.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
    if (cb.checked) return;
    const l = norm(labelOf(cb));
    if (CONSENT.some((k) => l.includes(k))) { cb.click(); filled++; }
  });

  // ---------- 3) <select> natifs ----------
  for (const sel of document.querySelectorAll("select")) {
    if (sel.selectedIndex > 0 && sel.value) continue;
    const options = [...sel.options].map((o) => o.text.trim()).filter(Boolean);
    if (!options.length) continue;
    const r = await api("/api/select", { job, label: labelOf(sel).slice(0, 80), options });
    if (r.value) {
      const o = [...sel.options].find((x) => x.text.trim() === r.value);
      if (o) { sel.value = o.value; sel.dispatchEvent(new Event("change", { bubbles: true })); filled++; }
    }
  }

  // ---------- 4) react-select ----------
  for (const ctrl of document.querySelectorAll(".select__control")) {
    const cur = norm(ctrl.innerText);
    if (cur && !cur.includes("select")) continue; // déjà rempli
    const g = ctrl.closest('.field,[class*="field"],div');
    const label = (g && g.querySelector("label,legend,.label")) ? g.querySelector("label,legend,.label").innerText.trim() : "";
    ctrl.click(); await sleep(500);
    let opts = [...document.querySelectorAll(".select__option")];
    if (!opts.length) { const inp = ctrl.querySelector("input"); if (inp) { inp.click(); await sleep(400); opts = [...document.querySelectorAll(".select__option")]; } }
    const texts = opts.map((o) => o.innerText.trim());
    if (!texts.length) { document.body.click(); continue; }
    const r = await api("/api/select", { job, label: label.slice(0, 80), options: texts });
    const o = r.value ? opts.find((x) => x.innerText.trim() === r.value) : null;
    if (o) { o.click(); filled++; await sleep(150); } else { document.body.click(); }
  }

  // ---------- 5) Lettre de motivation ("Enter manually") ----------
  const wantedBtn = ["enter manually", "write cover letter", "rédiger", "saisir manuellement", "écrire"];
  const revealBtn = [...document.querySelectorAll("button,a,[role=button],div,span,label")]
    .find((e) => wantedBtn.includes((e.innerText || "").trim().toLowerCase()));
  if (revealBtn) { revealBtn.click(); await sleep(700); }
  const coverTa = [...document.querySelectorAll("textarea")].find((t) => {
    if (norm((t.id || "") + " " + (t.name || "")).includes("cover")) return true;
    const box = t.closest('.field,[class*="field"],div');
    const ctx = norm((box ? box.innerText : "") + " " + (t.getAttribute("aria-label") || "") + " " + (t.placeholder || ""));
    return ["cover letter", "lettre de motivation", "motivation letter"].some((k) => ctx.includes(k));
  });
  if (coverTa && !coverTa.value.trim()) {
    log("✒️ Rédaction de la lettre…");
    const r = await api("/api/cover", { job });
    if (r.value && reactFill(coverTa, r.value)) { filled++; log("✅ Lettre rédigée"); }
  }

  // ---------- 6) Vérification GPT-4o ----------
  log("🔎 Vérification GPT-4o…");
  const state = [];
  document.querySelectorAll("input,textarea").forEach((el) => {
    const t = (el.type || "").toLowerCase();
    if (["hidden", "submit", "button", "file"].includes(t)) return;
    const lab = labelOf(el);
    state.push({ label: lab.slice(0, 80), value: (el.value || "").slice(0, 200), required: el.required || el.getAttribute("aria-required") === "true" || /\*/.test(lab) });
  });
  document.querySelectorAll(".select__control").forEach((c) => {
    const g = c.closest('.field,[class*="field"],div'); const l = g && g.querySelector("label,legend,.label");
    const lab = (l ? l.innerText : "").trim(); const txt = c.innerText.trim();
    state.push({ label: lab.slice(0, 80), value: norm(txt).includes("select...") ? "" : txt, required: /\*/.test(lab) });
  });
  const verdict = await api("/api/verify", { job, fields_state: state });

  // ---------- Résultat ----------
  const head = document.createElement("div");
  head.style.cssText = "margin-top:10px;padding-top:8px;border-top:1px solid #2a2e37;font-weight:700";
  if (verdict.ready) {
    head.style.color = "#7ee787";
    head.textContent = "✅ Prêt à envoyer (" + filled + " champs). Joins ton CV, relis, clique Submit.";
  } else {
    head.style.color = "#f2cc60";
    head.textContent = "⚠️ À compléter avant d'envoyer :";
  }
  logEl.appendChild(head);
  (verdict.issues || []).slice(0, 8).forEach((i) => log("• " + i, "#f2cc60"));
  if (verdict.error) log("Serveur: " + verdict.error, "#f2cc60");

  window.__applybot_running = false;
})();
