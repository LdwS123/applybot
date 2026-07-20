#!/usr/bin/env python
"""Serveur local "cerveau" pour l'extension Chrome.

L'extension (dans ton navigateur) fait les MAINS : elle lit et remplit la page.
Ce serveur fait le CERVEAU : il garde ta clé OpenAI + ton profil et décide quoi
mettre dans chaque champ (réutilise tout le code de applybot/).

    python apiserver.py        ->  http://127.0.0.1:8000

La clé OpenAI reste ici (dans .env), jamais dans le navigateur.
"""
from __future__ import annotations

from flask import Flask, request, jsonify

from applybot.config import Profile
from applybot import ai
from applybot.ats.base import classify, _resolve_value, _looks_like_cover

app = Flask(__name__)
PROFILE = Profile.load()


@app.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
    return resp


@app.route("/api/plan", methods=["POST", "OPTIONS"])
def plan():
    """Décide quoi mettre dans chaque input/textarea (hors menus déroulants).

    Entrée : {job:{title,company,location,url}, fields:[{idx,label,tag,type}]}
    Sortie : {plan:{idx:{action,value}}}  action in fill|cover|essay|skip
    """
    if request.method == "OPTIONS":
        return ("", 204)
    body = request.get_json(force=True)
    job = body.get("job", {})
    fields = body.get("fields", [])
    result = {}
    unknown = []
    for f in fields:
        idx, label = f["idx"], f.get("label", "")
        tag, typ = f.get("tag", "input"), f.get("type", "text")
        kind = classify(label)
        if kind == "skip" or typ in ("file", "password"):
            result[idx] = {"action": "skip"}
        elif kind.startswith("value:"):
            val = _resolve_value(PROFILE, job, kind.split(":", 1)[1])
            result[idx] = {"action": "fill", "value": val} if val else {"action": "skip"}
        elif kind == "essay" or tag == "textarea":
            if _looks_like_cover(label):
                result[idx] = {"action": "cover", "value": ai.cover_letter(PROFILE, job) or ""}
            else:
                result[idx] = {"action": "essay", "value": ai.answer_question(PROFILE, job, label) or ""}
        else:
            unknown.append(f)
    # champs non reconnus -> classifieur IA multilingue (un seul appel)
    if unknown:
        payload = [{"idx": u["idx"], "context": u.get("label", ""),
                    "tag": u.get("tag"), "type": u.get("type")} for u in unknown]
        decisions = ai.classify_fields(PROFILE, job, payload)
        for u in unknown:
            dec = decisions.get(str(u["idx"])) or decisions.get(u["idx"])
            if not dec or dec == "SKIP":
                result[u["idx"]] = {"action": "skip"}
            elif dec == "ESSAY":
                result[u["idx"]] = {"action": "essay",
                                    "value": ai.answer_question(PROFILE, job, u.get("label", "")) or ""}
            else:
                result[u["idx"]] = {"action": "fill", "value": _resolve_value(PROFILE, job, dec)}
    return jsonify({"plan": result})


@app.route("/api/select", methods=["POST", "OPTIONS"])
def select():
    """Choisit l'option d'un menu (le contenu script lit les options en direct).

    Entrée : {job, label, options:[...]}  Sortie : {value: option|null}
    """
    if request.method == "OPTIONS":
        return ("", 204)
    body = request.get_json(force=True)
    job, label, options = body.get("job", {}), body.get("label", ""), body.get("options", [])
    kind = classify(label)
    value = _resolve_value(PROFILE, job, kind.split(":", 1)[1]) if kind.startswith("value:") else ""
    from applybot.ats.base import _pick_option
    choice = _pick_option(value, options) if value else None
    if not choice:
        ai_choice = ai.choose_option(PROFILE, job, label, options)
        choice = _pick_option(ai_choice, options) if ai_choice else None
    return jsonify({"value": choice})


@app.route("/api/cover", methods=["POST", "OPTIONS"])
def cover():
    if request.method == "OPTIONS":
        return ("", 204)
    job = request.get_json(force=True).get("job", {})
    return jsonify({"value": ai.cover_letter(PROFILE, job) or ""})


@app.route("/api/verify", methods=["POST", "OPTIONS"])
def verify():
    """Vérif GPT-4o : la candidature est-elle prête (champs requis + cohérence) ?"""
    if request.method == "OPTIONS":
        return ("", 204)
    body = request.get_json(force=True)
    return jsonify(ai.verify_application(PROFILE, body.get("job", {}), body.get("fields_state", [])))


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "name": PROFILE.identity.get("full_name")})


if __name__ == "__main__":
    print("\n  Cerveau (API extension)  ->  http://127.0.0.1:8000\n")
    app.run(host="127.0.0.1", port=8000, threaded=True, debug=False)
