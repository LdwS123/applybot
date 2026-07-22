"""Classement des offres : niveau de séniorité (depuis le titre) et
localisation normalisée (ville / pays / remote depuis le champ location).

Tout est du parsing best-effort : les sources écrivent la localisation de
mille façons ("San Francisco, CA", "Remote - US", "Paris Office", "EMEA"…),
on fait de notre mieux et on tag `unknown` quand on ne sait pas.
"""
from __future__ import annotations

import re

# --- Niveau de séniorité -----------------------------------------------------
# 8 niveaux, du plus junior au plus senior. On teste dans l'ordre du plus
# SPÉCIFIQUE au moins spécifique : un "Senior Engineering Manager" doit sortir
# en `manager` (management), pas en `senior`. Donc management/exec sont testés
# AVANT senior. Défaut si rien ne matche : `mid`.
#
# \b = frontière de mot, pour éviter que "vp" matche "developvp" ou que
# "director" matche un mot plus long. Édite librement les listes.
_LEVEL_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("intern", re.compile(
        r"\b(intern|internship|stagiaire|stage|co-?op|working student|"
        r"alternance|apprenti|apprentice|trainee)\b", re.I)),
    ("exec", re.compile(
        r"\b(chief|ceo|cto|cfo|coo|cmo|cro|cpo|cxo|vp|svp|evp|"
        r"vice[- ]president|president|head of|director|managing director|"
        r"partner|general manager)\b", re.I)),
    ("manager", re.compile(
        r"\b(manager|mgr|team lead|tech lead|squad lead|people lead|"
        r"engineering lead|lead engineer|group lead)\b", re.I)),
    ("staff", re.compile(
        r"\b(staff|principal|distinguished|fellow|architect)\b", re.I)),
    ("senior", re.compile(r"\b(senior|sr\.?|snr)\b", re.I)),
    ("junior", re.compile(r"\b(junior|jr\.?|associate)\b", re.I)),
    # NB: `entry` doit matcher UNIQUEMENT des marqueurs de séniorité explicites,
    # jamais le mot "entry" isolé (sinon "Data Entry Clerk" -> faux positif).
    ("entry", re.compile(
        r"\b(entry[- ]level|early career|new ?grad|graduate|campus hire)\b", re.I)),
]

# Ordre d'affichage / de tri (0 = plus junior)
LEVEL_ORDER = ["intern", "entry", "junior", "mid", "senior", "staff", "manager", "exec"]


def classify_level(title: str) -> str:
    """Déduit le niveau de séniorité depuis l'intitulé du poste."""
    t = title or ""
    for level, pat in _LEVEL_PATTERNS:
        if pat.search(t):
            return level
    return "mid"


# --- Rôle / métier + filtre anti-bruit ---------------------------------------
# Konstantine cherche du growth / product / business-dev / marketing / ops.
# On tague chaque offre par rôle, et on EXCLUT le bruit (chauffeur, infirmier,
# caissier, ouvrier…) que les agrégateurs généralistes (Adzuna) ramènent.

# Denylist : métiers clairement hors-cible. Testé AVANT tout le reste.
_GARBAGE_RE = re.compile(
    r"\b(driver|uber|lyft|courier|chauffeur|delivery (driver|associate)|cdl|"
    r"truck|warehouse|forklift|picker|packer|loader|laborer|labourer|"
    r"nurse|nursing|rn|lpn|cna|caregiver|caretaker|therapist|physician|"
    r"dentist|dental|pharmacist|phlebotom|medical assistant|"
    r"cashier|barista|waiter|waitress|busser|line cook|dishwasher|"
    r"janitor|custodian|housekeep|security guard|"
    r"electrician|plumber|welder|hvac|machinist|assembler|machine operator|"
    r"landscap|farmworker|substitute teacher|tutor|babysit|nanny|"
    r"hairstylist|barber|esthetician|veterinar|groomer|"
    r"retail sales|sales associate|sales floor|stocker|"
    r"maintenance technician|field technician|service technician|"
    r"roofer|carpenter|painter|valet|caregiving)\b", re.I)

# Rôles ciblés (ordre = spécifique d'abord). Défaut : "other".
_ROLE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("product", re.compile(r"\b(product manager|product owner|product lead|"
                           r"product management|technical product|\bpm\b|group product)\b", re.I)),
    ("growth", re.compile(r"\b(growth|user acquisition|retention|lifecycle|"
                          r"demand gen(eration)?)\b", re.I)),
    ("bizdev", re.compile(r"\b(business development|partnerships?|alliances?|"
                          r"go-?to-?market|gtm|strategic partner)\b", re.I)),
    ("sales", re.compile(r"\b(sales|bdr|sdr|account executive|account manager|"
                         r"revenue|quota|solutions consultant)\b", re.I)),
    ("marketing", re.compile(r"\b(marketing|brand|content|seo|social media|"
                             r"communications|community|pr manager)\b", re.I)),
    ("operations", re.compile(r"\b(operations|\bops\b|program manager|project manager|"
                              r"chief of staff|strateg(y|ic)|bizops|revops)\b", re.I)),
    ("data", re.compile(r"\b(data analyst|data scientist|analytics|"
                        r"business intelligence|data engineer)\b", re.I)),
    ("engineering", re.compile(r"\b(engineer|developer|software|backend|frontend|"
                               r"full.?stack|devops|sre|programmer)\b", re.I)),
    ("design", re.compile(r"\b(designer|\bux\b|\bui\b|user experience|product design)\b", re.I)),
    ("finance", re.compile(r"\b(finance|financial|accountant|accounting|controller|fp&a)\b", re.I)),
    ("people", re.compile(r"\b(recruiter|recruiting|talent|people ops|human resources|\bhr\b)\b", re.I)),
]

# Les rôles qui correspondent à SON profil (pour le toggle "🎯 Mes rôles").
TARGET_ROLES = {"product", "growth", "bizdev", "sales", "marketing", "operations"}


def classify_role(title: str) -> str:
    """Rôle métier depuis le titre, ou 'excluded' si hors-cible (bruit)."""
    t = title or ""
    if _GARBAGE_RE.search(t):
        return "excluded"
    for role, pat in _ROLE_PATTERNS:
        if pat.search(t):
            return role
    return "other"


# --- Localisation : ville / pays / remote ------------------------------------

_REMOTE_RE = re.compile(
    r"\b(remote|anywhere|distributed|work from home|wfh|télétravail|teletravail|"
    r"fully remote|home[- ]based|world ?wide|global)\b", re.I)

# Segments qui ne sont PAS une ville mais un synonyme de "remote/partout"
_REMOTE_ONLY = {"remote", "anywhere", "worldwide", "world wide", "global",
                "distributed", "fully remote", "wfh", "emea", "americas", "apac"}

# Codes d'états US -> pour déduire "United States"
_US_STATES = {
    "al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il","in","ia",
    "ks","ky","la","me","md","ma","mi","mn","ms","mo","mt","ne","nv","nh","nj",
    "nm","ny","nc","nd","oh","ok","or","pa","ri","sc","sd","tn","tx","ut","vt",
    "va","wa","wv","wi","wy","dc",
}

# Alias de villes fréquents -> (ville canonique, pays)
_CITY_ALIASES = {
    "sf": ("San Francisco", "United States"),
    "san francisco": ("San Francisco", "United States"),
    "bay area": ("San Francisco", "United States"),
    "sf bay area": ("San Francisco", "United States"),
    "nyc": ("New York", "United States"),
    "new york city": ("New York", "United States"),
    "new york": ("New York", "United States"),
    "london": ("London", "United Kingdom"),
    "paris": ("Paris", "France"),
    "berlin": ("Berlin", "Germany"),
    "munich": ("Munich", "Germany"),
    "amsterdam": ("Amsterdam", "Netherlands"),
    "dublin": ("Dublin", "Ireland"),
    "toronto": ("Toronto", "Canada"),
    "bengaluru": ("Bangalore", "India"),
    "bangalore": ("Bangalore", "India"),
}

# Mots-pays qu'on peut lire directement dans la chaîne
_COUNTRY_WORDS = {
    "united states": "United States", "usa": "United States", "u.s.": "United States",
    "us": "United States", "u.s.a.": "United States", "remote us": "United States",
    "united kingdom": "United Kingdom", "uk": "United Kingdom", "england": "United Kingdom",
    "france": "France", "germany": "Germany", "deutschland": "Germany",
    "netherlands": "Netherlands", "ireland": "Ireland", "canada": "Canada",
    "spain": "Spain", "italy": "Italy", "india": "India", "australia": "Australia",
    "poland": "Poland", "portugal": "Portugal", "sweden": "Sweden",
}

_NOISE = re.compile(r"\b(office|hq|headquarters|based|onsite|on-site|hybrid|or remote)\b", re.I)


def normalize_location(location: str) -> tuple[str, str, bool]:
    """(ville, pays, remote?) à partir d'un champ localisation libre."""
    raw = (location or "").strip()
    remote = bool(_REMOTE_RE.search(raw))
    if not raw:
        return ("Unknown", "Unknown", remote)

    low = raw.lower()

    # Pays explicite si présent
    country = "Unknown"
    for word, canon in _COUNTRY_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            country = canon
            break

    # Premier segment avant une virgule / tiret = candidat "ville"
    first = re.split(r"[,/;·|]| - | – ", raw)[0]
    first = _NOISE.sub("", first).strip()
    key = first.lower().strip()

    if key in _CITY_ALIASES:
        city, alias_country = _CITY_ALIASES[key]
        if country == "Unknown":
            country = alias_country
        return (city, country, remote)

    # Code d'état US (ex "Austin, TX") -> pays US
    tokens = [t.strip().lower() for t in re.split(r"[,/]", raw)]
    if country == "Unknown" and any(t in _US_STATES for t in tokens):
        country = "United States"

    # Segment "remote-only" (worldwide, anywhere, EMEA…) -> pas une vraie ville
    if key in _REMOTE_ONLY or (remote and not first):
        return ("Remote", country, True)

    city = first.title() if first else ("Remote" if remote else "Unknown")
    return (city, country, remote)


def classify(job: dict) -> dict:
    """Enrichit une offre normalisée avec role / level / city / country / remote."""
    city, country, remote = normalize_location(job.get("location", ""))
    job["role"] = classify_role(job.get("title", ""))
    job["level"] = classify_level(job.get("title", ""))
    job["city"] = city
    job["country"] = country
    job["remote"] = "yes" if remote else "no"
    return job
