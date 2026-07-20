"""Découverte d'offres via les API PUBLIQUES et gratuites de Greenhouse & Lever.

Entrée : companies.txt, une entreprise par ligne au format
    greenhouse:stripe
    lever:netlify
(le slug est celui de l'URL du board carrière de la boîte)

Sortie : jobs.csv (URLs postulables), filtrées par mots-clés.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 applybot"}


def _get_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def greenhouse_jobs(slug: str) -> list[dict]:
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    out = []
    for j in data.get("jobs", []):
        out.append({
            "title": j.get("title", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "url": j.get("absolute_url", ""),
        })
    return out


def lever_jobs(slug: str) -> list[dict]:
    data = _get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    out = []
    for j in data:
        out.append({
            "title": j.get("text", ""),
            "location": (j.get("categories") or {}).get("location", ""),
            "url": j.get("hostedUrl", ""),
        })
    return out


def discover(companies_file: str, keywords: list[str], out_file: str = "jobs.csv") -> int:
    kws = [k.lower().strip() for k in keywords if k.strip()]
    rows: list[dict] = []
    for line in Path(companies_file).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        source, slug = line.split(":", 1)
        source, slug = source.strip().lower(), slug.strip()
        try:
            jobs = greenhouse_jobs(slug) if source == "greenhouse" else \
                   lever_jobs(slug) if source == "lever" else []
        except Exception as e:  # noqa: BLE001
            print(f"   ⚠️  {source}:{slug} -> {e}")
            continue
        matched = [
            j for j in jobs
            if not kws or any(k in j["title"].lower() for k in kws)
        ]
        print(f"   {source}:{slug} -> {len(matched)}/{len(jobs)} offres retenues")
        rows.extend(matched)

    with open(out_file, "w", encoding="utf-8") as f:
        f.write("# url, title, location  (généré par discovery)\n")
        for r in rows:
            if r["url"]:
                f.write(f'{r["url"]}, {r["title"]}, {r["location"]}\n')
    print(f"\n{len(rows)} offres écrites dans {out_file}")
    return len(rows)
