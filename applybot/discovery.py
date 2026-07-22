"""Découverte MASSIVE d'offres, multi-sources, avec classement.

Pipeline : fetch (toutes sources) -> normalise -> classe (niveau/ville/pays) ->
dédoublonne -> stocke (SQLite + CSV).

Sorties :
  offers.db   SQLite, source de vérité, requêtable ("senior + Paris + growth")
  offers.csv  CSV riche pour explorer / offers.html
  jobs.csv    URL en 1ʳᵉ colonne -> compatible avec `python run.py apply`

Entrée : companies.txt (une ligne `ats:slug` par entreprise pour les ATS).
Les agrégateurs (Remotive, Adzuna…) tournent sans slug.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import sqlite3
from collections import Counter
from pathlib import Path

from . import sources
from .classify import classify, LEVEL_ORDER, TARGET_ROLES

DB_FILE = "offers.db"
OFFERS_CSV = "offers.csv"
JOBS_CSV = "jobs.csv"
OFFERS_JSON = "docs/offers.json"  # pour le viewer web (GitHub Pages)

TODAY = dt.date.today().isoformat()

CSV_COLS = ["title", "company", "role", "city", "country", "level", "remote",
            "source", "location", "url"]


# --- lecture de companies.txt ------------------------------------------------

def _read_companies(path: str) -> list[tuple[str, str]]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        ats, slug = line.split(":", 1)
        out.append((ats.strip().lower(), slug.strip()))
    return out


# --- fetch de toutes les sources ---------------------------------------------

def _fetch_all(companies_file: str, query: str, use_key_sources: bool,
               include_yc: bool, yc_hiring_only: bool = False) -> list[dict]:
    rows: list[dict] = []

    # 1. ATS par entreprise
    for ats, slug in _read_companies(companies_file):
        fn = sources.ATS.get(ats)
        if not fn:
            print(f"   ⚠️  ATS inconnu: {ats}:{slug} (ignoré)")
            continue
        try:
            got = fn(slug)
            rows.extend(got)
            print(f"   {ats}:{slug} -> {len(got)} offres")
        except Exception as e:  # noqa: BLE001 — slug mort/404 -> on saute
            print(f"   ⚠️  {ats}:{slug} -> {type(e).__name__} (ignoré)")

    # 2. Agrégateurs gratuits (sans clé)
    for name, fn in sources.AGGREGATORS_FREE.items():
        try:
            got = fn()
            rows.extend(got)
            print(f"   [agrégateur] {name} -> {len(got)} offres")
        except Exception as e:  # noqa: BLE001
            print(f"   ⚠️  {name} -> {type(e).__name__} (ignoré)")

    # 3. Y Combinator : découverte automatique de startups (peut prendre ~10 min)
    if include_yc:
        try:
            scope = "1500 isHiring" if yc_hiring_only else "~6000 boîtes"
            print(f"   [YC] découverte des startups ({scope}, probe des boards)...")
            got = sources.ycombinator(hiring_only=yc_hiring_only)
            rows.extend(got)
            print(f"   [YC] -> {len(got)} offres de startups YC")
        except Exception as e:  # noqa: BLE001
            print(f"   ⚠️  yc -> {type(e).__name__} (ignoré)")

    # 4. Agrégateurs avec clé API (Adzuna / The Muse)
    if use_key_sources:
        for name, fn in sources.AGGREGATORS_KEY.items():
            try:
                got = fn(query) if name == "adzuna" else fn()
                rows.extend(got)
                tag = "" if got else " (clé absente ? voir .env)"
                print(f"   [agrégateur+clé] {name} -> {len(got)} offres{tag}")
            except Exception as e:  # noqa: BLE001
                print(f"   ⚠️  {name} -> {type(e).__name__} (ignoré)")

    return rows


# --- dédup + filtre ----------------------------------------------------------

def _dedupe(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for r in rows:
        key = r["url"].lower() or f'{r["title"].lower()}@{r["company"].lower()}'
        if key in seen or not (r["title"] and r["url"]):
            continue
        seen.add(key)
        out.append(r)
    return out


def _matches(row: dict, kws: list[str]) -> bool:
    if not kws:
        return True
    t = row["title"].lower()
    return any(k in t for k in kws)


# --- stockage ----------------------------------------------------------------

_ALL_COLS = CSV_COLS + ["first_seen", "last_seen"]


def _load_history() -> dict[str, dict]:
    """Offres déjà connues (runs précédents) -> {url: row} avec first_seen."""
    if not Path(DB_FILE).exists():
        return {}
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT * FROM jobs").fetchall()
    except sqlite3.OperationalError:
        return {}
    finally:
        con.close()
    out: dict[str, dict] = {}
    for r in rows:
        d = dict(r)
        # tolérance migration : ancien schéma sans first_seen/last_seen
        d.setdefault("first_seen", d.get("last_seen") or "2000-01-01")
        d.setdefault("last_seen", d.get("first_seen") or "2000-01-01")
        d.setdefault("role", "other")
        out[d["url"]] = d
    return out


def _merge_history(fresh: list[dict], history: dict[str, dict]) -> list[dict]:
    """Fusionne le scrape du jour avec l'historique.
    - offre déjà connue  -> on garde son first_seen, on met last_seen=aujourd'hui
    - offre nouvelle      -> first_seen = last_seen = aujourd'hui  (badge NEW)
    - offre de l'historique absente aujourd'hui -> conservée (last_seen inchangé)
    """
    merged: dict[str, dict] = dict(history)  # part de tout l'historique
    for r in fresh:
        url = r["url"]
        prev = history.get(url)
        r["first_seen"] = prev["first_seen"] if prev else TODAY
        r["last_seen"] = TODAY
        merged[url] = r
    return list(merged.values())


def _write_db(rows: list[dict]) -> None:
    con = sqlite3.connect(DB_FILE)
    con.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            url TEXT PRIMARY KEY, title TEXT, company TEXT, role TEXT, city TEXT,
            country TEXT, level TEXT, remote TEXT, source TEXT, location TEXT,
            first_seen TEXT, last_seen TEXT
        )""")
    con.execute("DELETE FROM jobs")  # on réécrit l'ensemble fusionné
    con.executemany(
        """INSERT OR REPLACE INTO jobs
           (url,title,company,role,city,country,level,remote,source,location,first_seen,last_seen)
           VALUES (:url,:title,:company,:role,:city,:country,:level,:remote,:source,:location,
                   :first_seen,:last_seen)""",
        rows)
    con.commit()
    con.close()


def _write_csvs(rows: list[dict]) -> None:
    with open(OFFERS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Titre", "Entreprise", "Rôle", "Ville", "Pays", "Niveau", "Remote",
                    "Source", "Localisation", "Lien", "Vue le", "Vue dernière"])
        for r in rows:
            w.writerow([r[c] for c in _ALL_COLS])
    # jobs.csv : flux pour la phase apply. On NE garde QUE les rôles ciblés
    # (product/growth/bizdev/sales/marketing/ops) et les offres encore ouvertes,
    # pour que l'agent ne postule jamais à un poste d'ingé/data/etc.
    with open(JOBS_CSV, "w", encoding="utf-8") as f:
        f.write("# url, title, company, role, level, city  (rôles ciblés uniquement)\n")
        for r in rows:
            if r["last_seen"] == TODAY and r.get("role") in TARGET_ROLES:
                f.write(f'{r["url"]}, {r["title"]}, {r["company"]}, '
                        f'{r["role"]}, {r["level"]}, {r["city"]}\n')


def _write_json(rows: list[dict]) -> None:
    """JSON compact pour le viewer web (docs/offers.json -> GitHub Pages)."""
    Path(OFFERS_JSON).parent.mkdir(exist_ok=True)
    slim = [{
        "t": r["title"], "co": r["company"], "ro": r.get("role", "other"),
        "ci": r["city"], "cy": r["country"], "lv": r["level"], "rm": r["remote"],
        "s": r["source"], "u": r["url"],
        "new": r["first_seen"] == TODAY, "open": r["last_seen"] == TODAY,
        "seen": r["first_seen"],
    } for r in rows]
    # nouvelles d'abord, puis par date
    slim.sort(key=lambda x: (not x["new"], x["seen"]), reverse=False)
    payload = {"updated": TODAY, "count": len(slim), "jobs": slim}
    with open(OFFERS_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))


# --- résumé ------------------------------------------------------------------

def _summary(rows: list[dict]) -> None:
    by_level = Counter(r["level"] for r in rows)
    by_source = Counter(r["source"] for r in rows)
    by_city = Counter(r["city"] for r in rows)
    by_role = Counter(r.get("role", "other") for r in rows)
    print(f"\n{'='*54}\n{len(rows)} offres uniques classées\n{'='*54}")
    print("Par rôle   :", "  ".join(f"{ro}={n}" for ro, n in by_role.most_common()))
    print("Par niveau :", "  ".join(
        f"{lv}={by_level[lv]}" for lv in LEVEL_ORDER if by_level[lv]))
    print("Par source :", "  ".join(f"{s}={n}" for s, n in by_source.most_common()))
    print("Top villes :", "  ".join(
        f"{c}={n}" for c, n in by_city.most_common(12) if c not in ("Unknown",)))


def discover(companies_file: str = "companies.txt", keywords: list[str] | None = None,
             use_key_sources: bool = True, include_yc: bool = True,
             yc_hiring_only: bool = False) -> int:
    """Scrape toutes les sources, classe, stocke. Renvoie le nb d'offres."""
    kws = [k.lower().strip() for k in (keywords or []) if k.strip()]
    query = " ".join(kws)

    print("Scraping multi-sources...\n")
    raw = _fetch_all(companies_file, query, use_key_sources, include_yc, yc_hiring_only)
    print(f"\n{len(raw)} offres brutes récupérées. Classement + dédup...")

    fresh = [classify(r) for r in _dedupe(raw)]
    # anti-bruit : on jette le garbage (chauffeur, infirmier, caissier…)
    before = len(fresh)
    fresh = [r for r in fresh if r["role"] != "excluded"]
    print(f"Filtre anti-bruit : {before - len(fresh)} offres hors-cible écartées")
    if kws:
        before = len(fresh)
        fresh = [r for r in fresh if _matches(r, kws)]
        print(f"Filtre mots-clés {kws}: {len(fresh)}/{before} retenues")

    history = _load_history()
    rows = _merge_history(fresh, history)
    rows = [r for r in rows if r.get("role") != "excluded"]  # purge l'historique aussi
    n_new = sum(1 for r in rows if r["first_seen"] == TODAY)
    n_open = sum(1 for r in rows if r["last_seen"] == TODAY)

    _write_db(rows)
    _write_csvs(rows)
    _write_json(rows)
    _summary(rows)
    print(f"\n🆕 {n_new} nouvelles aujourd'hui · {n_open} ouvertes · "
          f"{len(rows)} au total (historique inclus)")
    print(f"Écrit : {DB_FILE} · {OFFERS_CSV} · {JOBS_CSV} · {OFFERS_JSON}")
    return len(rows)
