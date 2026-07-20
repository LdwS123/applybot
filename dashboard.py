#!/usr/bin/env python
"""Dashboard local du bot de candidature.

    python dashboard.py     ->  ouvre http://127.0.0.1:8000

Tu colles un lien d'offre, le bot ouvre un navigateur et remplit le formulaire
devant toi, tu relis, puis tu cliques "Envoyer". Tout tourne EN LOCAL (le bot a
besoin de tes sessions connectées) — rien n'est envoyé à un serveur externe hormis
les appels OpenAI pour rédiger tes réponses.
"""
from __future__ import annotations

import csv
from flask import Flask, request, jsonify

from applybot.controller import controller
from applybot.runner import LOG

app = Flask(__name__)

PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ApplyBot — Dashboard</title>
<style>
  :root{color-scheme:light dark}
  *{box-sizing:border-box}
  body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:820px;margin:0 auto;padding:24px;
       background:#0f1115;color:#e7e9ee}
  h1{font-size:20px;margin:0 0 4px} .sub{color:#9aa0ad;font-size:13px;margin:0 0 20px}
  textarea,input{width:100%;padding:12px;border-radius:10px;border:1px solid #2a2e37;background:#171a21;color:#e7e9ee;font-size:14px}
  .row{display:flex;gap:10px;margin-top:12px;flex-wrap:wrap}
  button{padding:11px 18px;border:0;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer}
  .prep{background:#3b82f6;color:#fff} .send{background:#22c55e;color:#062611} .skip{background:#2a2e37;color:#e7e9ee}
  button:disabled{opacity:.5;cursor:default}
  .card{background:#171a21;border:1px solid #2a2e37;border-radius:12px;padding:16px;margin-top:18px}
  .tag{display:inline-block;background:#233;color:#7cd;padding:2px 8px;border-radius:6px;font-size:12px}
  ul{margin:6px 0 0;padding-left:18px} li{font-size:13px;margin:2px 0}
  .ok{color:#7ee787} .warn{color:#f2cc60} .muted{color:#9aa0ad}
  #status{margin-top:12px;font-size:14px}
</style></head><body>
<h1>🤖 ApplyBot</h1>
<p class="sub">Colle un lien d'offre → <b>Préparer</b> (le bot remplit dans le navigateur) → relis → <b>Envoyer</b>. Mode semi-auto.</p>
<textarea id="url" rows="2" placeholder="https://job-boards.greenhouse.io/.../jobs/123 (ou plusieurs, un par ligne)"></textarea>
<div class="row">
  <button class="prep" onclick="prepare()">1 · Préparer</button>
  <button class="send" id="sendBtn" onclick="send()" disabled>2 · Envoyer</button>
  <button class="skip" onclick="skip()">Passer</button>
  <button class="skip" onclick="loadQueue()">📋 Charger jobs.csv</button>
</div>
<div id="status" class="muted"></div>
<div id="report"></div>

<script>
const $ = id => document.getElementById(id);
function setStatus(t, cls){ $('status').className = cls||'muted'; $('status').textContent = t; }

async function prepare(){
  const urls = $('url').value.split('\\n').map(s=>s.trim()).filter(Boolean);
  if(!urls.length){ setStatus('Colle au moins un lien.', 'warn'); return; }
  const url = urls[0];
  setStatus('Ouverture du navigateur et remplissage… (ça prend ~15-30 s)', 'muted');
  $('sendBtn').disabled = true;
  try{
    const r = await fetch('/prepare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});
    const d = await r.json();
    if(d.error){ setStatus('Erreur: '+d.error,'warn'); return; }
    render(d);
    setStatus('✅ Formulaire rempli. Relis dans le navigateur puis clique Envoyer.', 'ok');
    $('sendBtn').disabled = false;
    // retire l'offre traitée de la file
    $('url').value = urls.slice(1).join('\\n');
  }catch(e){ setStatus('Erreur réseau: '+e,'warn'); }
}
async function send(){
  setStatus('Envoi…','muted');
  const r = await fetch('/submit',{method:'POST'}); const d = await r.json();
  setStatus(d.message, d.ok?'ok':'warn'); $('sendBtn').disabled = true;
}
async function skip(){
  const r = await fetch('/skip',{method:'POST'}); const d = await r.json();
  setStatus(d.message,'muted'); $('sendBtn').disabled = true;
}
async function loadQueue(){
  const r = await fetch('/queue'); const urls = await r.json();
  if(!urls.length){ setStatus('jobs.csv est vide — lance la découverte d\\'offres.','warn'); return; }
  $('url').value = urls.join('\\n');
  setStatus(`📋 ${urls.length} offres chargées. Clique "Préparer" pour la première.`, 'ok');
}
function render(d){
  const li = a => a.map(x=>`<li>${x}</li>`).join('');
  $('report').innerHTML = `<div class="card">
    <div><span class="tag">${d.ats}</span> <b>${d.title||''}</b> <span class="muted">${d.company||''}</span></div>
    <p class="muted">${d.summary}</p>
    <p class="ok">Rempli (${d.filled.length})</p><ul>${li(d.filled)}</ul>
    ${d.essays.length?`<p class="ok">Réponses IA</p><ul>${li(d.essays)}</ul>`:''}
    ${d.unknown.length?`<p class="warn">À vérifier à la main (${d.unknown.length})</p><ul class="muted">${li(d.unknown)}</ul>`:''}
  </div>`;
}
</script></body></html>"""


@app.get("/")
def index():
    return PAGE


@app.post("/prepare")
def prepare():
    url = (request.get_json(silent=True) or {}).get("url", "").strip()
    if not url.startswith("http"):
        return jsonify({"error": "URL invalide"}), 400
    try:
        return jsonify(controller.prepare(url))
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500


@app.post("/submit")
def submit():
    return jsonify(controller.submit())


@app.post("/skip")
def skip():
    return jsonify(controller.skip())


@app.get("/queue")
def queue():
    from applybot.runner import load_jobs
    try:
        return jsonify(load_jobs("jobs.csv"))
    except Exception:  # noqa: BLE001
        return jsonify([])


@app.get("/log")
def log():
    if not LOG.exists():
        return jsonify([])
    with open(LOG, encoding="utf-8") as f:
        return jsonify(list(csv.DictReader(f)))


if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", "8000"))
    print(f"\n  Dashboard  ->  http://127.0.0.1:{port}\n")
    # threaded=False : obligatoire pour l'API sync de Rustwright (un seul thread)
    app.run(host="127.0.0.1", port=port, threaded=False, debug=False)
