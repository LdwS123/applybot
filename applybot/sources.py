"""Toutes les sources d'offres. Deux familles :

1. ATS par-entreprise  (il faut un slug par boîte, lu depuis companies.txt) :
   greenhouse, lever, ashby, smartrecruiters, workable, recruitee
2. Agrégateurs         (aucun slug, ramènent des milliers d'offres d'un coup) :
   remotive, arbeitnow, jobicy, hackernews  (gratuits, sans clé)
   adzuna, themuse                          (clé API gratuite requise)

Chaque fonction renvoie une liste de dicts NORMALISÉS :
    {title, company, location, url, source}
Le reste du pipeline (classify, dédup, stockage) ignore d'où vient l'offre.
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

# Charge les clés API (.env) dès l'import — la chaîne `discover` ne passe pas
# par config.py, donc on garantit ici que ADZUNA_* / THEMUSE_* sont dispo.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

UA = {"User-Agent": "Mozilla/5.0 applybot"}


def _get_json(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get_text(url: str, timeout: int = 7, cap: int = 500_000) -> str:
    """Récupère du HTML (borné à `cap` octets pour éviter les pages géantes)."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(cap).decode("utf-8", "ignore")


def _row(title, company, location, url, source) -> dict:
    return {
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "location": (location or "").strip(),
        "url": (url or "").strip(),
        "source": source,
    }


# ============================================================================
#  ATS PAR-ENTREPRISE  (slug requis)
# ============================================================================

def greenhouse(slug: str) -> list[dict]:
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    return [
        _row(j.get("title"), slug, (j.get("location") or {}).get("name", ""),
             j.get("absolute_url"), "greenhouse")
        for j in data.get("jobs", [])
    ]


def lever(slug: str) -> list[dict]:
    data = _get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    return [
        _row(j.get("text"), slug, (j.get("categories") or {}).get("location", ""),
             j.get("hostedUrl"), "lever")
        for j in data
    ]


def ashby(slug: str) -> list[dict]:
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    return [
        _row(j.get("title"), slug, j.get("location", ""),
             j.get("jobUrl") or j.get("applyUrl"), "ashby")
        for j in data.get("jobs", [])
    ]


def smartrecruiters(slug: str) -> list[dict]:
    data = _get_json(
        f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100")
    out = []
    for j in data.get("content", []):
        loc = j.get("location", {}) or {}
        city = ", ".join(x for x in (loc.get("city"), loc.get("country")) if x)
        out.append(_row(
            j.get("name"), slug, city,
            f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}", "smartrecruiters"))
    return out


def workable(slug: str) -> list[dict]:
    data = _get_json(
        f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
    out = []
    for j in data.get("jobs", []):
        loc = ", ".join(x for x in (j.get("city"), j.get("country")) if x)
        url = j.get("url") or j.get("application_url") \
            or f"https://apply.workable.com/{slug}/j/{j.get('shortcode', '')}/"
        out.append(_row(j.get("title"), slug, loc, url, "workable"))
    return out


def recruitee(slug: str) -> list[dict]:
    data = _get_json(f"https://{slug}.recruitee.com/api/offers/")
    return [
        _row(j.get("title"), slug, j.get("location", ""),
             j.get("careers_url") or j.get("careers_apply_url"), "recruitee")
        for j in data.get("offers", [])
    ]


def bamboohr(slug: str) -> list[dict]:
    data = _get_json(f"https://{slug}.bamboohr.com/careers/list")
    out = []
    for j in data.get("result", []):
        loc = j.get("atsLocation") or {}
        location = ", ".join(x for x in (loc.get("city"), loc.get("country")) if x) \
            or ("Remote" if j.get("isRemote") else "")
        out.append(_row(j.get("jobOpeningName"), slug, location,
                        f"https://{slug}.bamboohr.com/careers/{j.get('id')}", "bamboohr"))
    return out


def breezy(slug: str) -> list[dict]:
    data = _get_json(f"https://{slug}.breezy.hr/json")
    out = []
    for j in data:
        loc = j.get("location") or {}
        country = loc.get("country")
        country = country.get("name") if isinstance(country, dict) else country
        location = ", ".join(x for x in (loc.get("city"), country) if x)
        out.append(_row(j.get("name"), slug, location, j.get("url"), "breezy"))
    return out


# Table de dispatch : préfixe dans companies.txt -> fonction
ATS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "smartrecruiters": smartrecruiters,
    "workable": workable,
    "recruitee": recruitee,
    "bamboohr": bamboohr,
    "breezy": breezy,
}


# ============================================================================
#  AGRÉGATEURS SANS CLÉ
# ============================================================================

def remotive() -> list[dict]:
    data = _get_json("https://remotive.com/api/remote-jobs")
    return [
        _row(j.get("title"), j.get("company_name"),
             j.get("candidate_required_location") or "Remote",
             j.get("url"), "remotive")
        for j in data.get("jobs", [])
    ]


def arbeitnow() -> list[dict]:
    data = _get_json("https://www.arbeitnow.com/api/job-board-api")
    out = []
    for j in data.get("data", []):
        loc = j.get("location") or ("Remote" if j.get("remote") else "")
        out.append(_row(j.get("title"), j.get("company_name"), loc,
                        j.get("url"), "arbeitnow"))
    return out


def jobicy() -> list[dict]:
    data = _get_json("https://jobicy.com/api/v2/remote-jobs?count=100")
    return [
        _row(j.get("jobTitle"), j.get("companyName"),
             j.get("jobGeo") or "Remote", j.get("url"), "jobicy")
        for j in data.get("jobs", [])
    ]


_HN_URL_RE = re.compile(r"https?://[^\s\"'<>)]+")
_HN_TAG_RE = re.compile(r"<[^>]+>")


def hackernews() -> list[dict]:
    """Dernier fil mensuel "Ask HN: Who is hiring?" (posté par le compte-bot
    `whoishiring`, ~500 offres startup). Les commentaires racine suivent la
    convention pipe-délimitée : COMPANY | ROLE | LOCATION | REMOTE | ... URL."""
    # tri par DATE + auteur whoishiring -> on tombe sur le fil du mois courant
    # (et pas sur un "Ask HN: Who is dating?" qui matcherait les mots-clés).
    search = _get_json(
        "https://hn.algolia.com/api/v1/search_by_date?"
        "tags=story,author_whoishiring&hitsPerPage=15")
    hiring = [h for h in search.get("hits", [])
              if "who is hiring" in (h.get("title") or "").lower()]
    if not hiring:
        return []
    story = _get_json(f"https://hn.algolia.com/api/v1/items/{hiring[0]['objectID']}")
    out = []
    for c in story.get("children", []):
        text = c.get("text") or ""
        if not text:
            continue
        url_m = _HN_URL_RE.search(text)
        clean = html.unescape(_HN_TAG_RE.sub(" ", text))
        parts = [p.strip() for p in clean.split("|")]
        if len(parts) < 2:
            continue
        company, title = parts[0][:80], parts[1][:120]
        location = parts[2] if len(parts) > 2 else ""
        url = url_m.group(0) if url_m else f"https://news.ycombinator.com/item?id={c.get('id')}"
        out.append(_row(title, company, location, url, "hackernews"))
    return out


def remoteok() -> list[dict]:
    """RemoteOK : jobs remote tech/startup. Le 1er élément est une mention
    légale (pas d'offre) -> filtré via la présence de `position`."""
    data = _get_json("https://remoteok.com/api")
    out = []
    for j in data:
        if not isinstance(j, dict) or not j.get("position"):
            continue
        out.append(_row(j.get("position"), j.get("company"),
                        j.get("location") or "Remote",
                        j.get("url") or j.get("apply_url"), "remoteok"))
    return out


def himalayas() -> list[dict]:
    """Himalayas : jobs remote, beaucoup de startups. locationRestrictions
    est une liste de pays autorisés."""
    data = _get_json("https://himalayas.app/jobs/api?limit=100")
    out = []
    for j in data.get("jobs", []):
        loc = ", ".join(j.get("locationRestrictions") or []) or "Remote"
        out.append(_row(j.get("title"), j.get("companyName"), loc,
                        j.get("applicationLink"), "himalayas"))
    return out


AGGREGATORS_FREE = {
    "remotive": remotive,
    "arbeitnow": arbeitnow,
    "jobicy": jobicy,
    "remoteok": remoteok,
    "himalayas": himalayas,
    "hackernews": hackernews,
}


# ============================================================================
#  AGRÉGATEURS AVEC CLÉ API  (gratuite)
# ============================================================================

def adzuna(query: str = "",
           countries=("us", "gb", "fr", "de", "ca", "nl", "in", "es", "sg"),
           pages: int = 3) -> list[dict]:
    """Indexe la quasi-totalité des employeurs, filtrable par pays/ville.
    Clés gratuites sur developer.adzuna.com -> ADZUNA_APP_ID / ADZUNA_APP_KEY."""
    app_id = os.getenv("ADZUNA_APP_ID", "").strip()
    app_key = os.getenv("ADZUNA_APP_KEY", "").strip()
    if not (app_id and app_key):
        return []
    out = []
    for country in countries:
        for page in range(1, pages + 1):
            params = urllib.parse.urlencode({
                "app_id": app_id, "app_key": app_key,
                "results_per_page": 50, "what": query, "content-type": "application/json",
            })
            try:
                data = _get_json(
                    f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}?{params}")
            except Exception:  # noqa: BLE001 — page/pays vide ou quota
                break
            results = data.get("results", [])
            if not results:
                break
            for j in results:
                out.append(_row(
                    j.get("title"), (j.get("company") or {}).get("display_name"),
                    (j.get("location") or {}).get("display_name"),
                    j.get("redirect_url"), "adzuna"))
    return out


def themuse(pages: int = 20) -> list[dict]:
    """The Muse : jobs tech/startup. Clé optionnelle (THEMUSE_API_KEY) pour
    lever la limite de débit."""
    key = os.getenv("THEMUSE_API_KEY", "").strip()
    out = []
    for page in range(pages):
        params = urllib.parse.urlencode({"page": page, **({"api_key": key} if key else {})})
        try:
            data = _get_json(f"https://www.themuse.com/api/public/jobs?{params}")
        except Exception:  # noqa: BLE001
            break
        for j in data.get("results", []):
            locs = ", ".join(l.get("name", "") for l in j.get("locations", []))
            out.append(_row(
                j.get("name"), (j.get("company") or {}).get("name"),
                locs, (j.get("refs") or {}).get("landing_page"), "themuse"))
    return out


AGGREGATORS_KEY = {
    "adzuna": adzuna,
    "themuse": themuse,
}


# ============================================================================
#  Y COMBINATOR : découverte AUTOMATIQUE de startups (même les inconnues)
# ============================================================================
# L'annuaire YC (yc-oss) liste ~6000 startups avec un flag isHiring. Pour
# chaque startup qui recrute, on TENTE de deviner son board carrière en
# essayant le slug tel quel sur greenhouse -> ashby -> lever. ~40% résolvent
# (le slug YC = souvent le slug du board). Ça découvre des centaines de
# startups qu'on n'aurait jamais listées à la main.

YC_DIRECTORY = "https://yc-oss.github.io/api/companies/all.json"


# Détecte le vrai board carrière dans le HTML d'un site (slug custom, embed…).
# Ordre des groupes capturants = greenhouse(embed for=), greenhouse(boards/slug),
# lever, ashby, workable.
_BOARD_RE = re.compile(
    r"greenhouse\.io/embed/job_board\?for=([a-z0-9_-]+)"
    r"|(?:boards|job-boards)\.greenhouse\.io/(?!embed)([a-z0-9_-]+)"
    r"|jobs\.lever\.co/([a-z0-9_-]+)"
    r"|jobs\.ashbyhq\.com/([a-z0-9._-]+)"
    r"|apply\.workable\.com/([a-z0-9_-]+)"
    r"|(?!www\.)([a-z0-9-]+)\.bamboohr\.com"
    r"|(?!www\.)([a-z0-9-]+)\.breezy\.hr", re.I)

_BOARD_ATS = ["greenhouse", "greenhouse", "lever", "ashby", "workable",
              "bamboohr", "breezy"]


def _detect_board(website: str | None) -> tuple[str, str] | None:
    """Suit le site de la boîte et détecte (ats, slug) depuis les liens carrière."""
    if not website:
        return None
    base = website.rstrip("/")
    for path in ("", "/careers", "/jobs"):
        try:
            html = _get_text(base + path)
        except Exception:  # noqa: BLE001 — site down/timeout/redirect
            continue
        m = _BOARD_RE.search(html)
        if m:
            for i, g in enumerate(m.groups()):
                if g:
                    return (_BOARD_ATS[i], g)
    return None


def _yc_probe(company: dict) -> list[dict]:
    """1) slug direct sur greenhouse/ashby/lever ; 2) sinon, détection via le
    site web (rattrape les slugs custom type 'apollo-graphql'). 1ᵉʳ hit gagne."""
    slug = company["slug"]
    for fn in (greenhouse, ashby, lever):
        try:
            jobs = fn(slug)
        except Exception:  # noqa: BLE001
            continue
        if jobs:
            for j in jobs:
                j["source"] = "yc"
            return jobs
    # fallback : détection du board dans le site web
    board = _detect_board(company.get("website"))
    if board:
        fn = ATS.get(board[0])
        if fn:
            try:
                jobs = fn(board[1])
            except Exception:  # noqa: BLE001
                jobs = []
            if jobs:
                for j in jobs:
                    j["source"] = "yc"
                return jobs
    return []


def ycombinator(limit: int | None = None, workers: int = 24) -> list[dict]:
    """Toutes les startups YC en train de recruter, board carrière résolu
    (slug direct + détection web pour les slugs custom)."""
    data = _get_json(YC_DIRECTORY, timeout=40)
    companies = [c for c in data if c.get("isHiring") and c.get("slug")]
    if limit:
        companies = companies[:limit]
    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for jobs in ex.map(_yc_probe, companies):
            out.extend(jobs)
    return out
