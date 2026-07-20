"""Détecte quel ATS gère une offre, à partir de l'URL (et du DOM en secours)."""
from __future__ import annotations

from urllib.parse import urlparse

# host substring -> nom d'ATS
_HOST_MAP = {
    "greenhouse.io": "greenhouse",
    "grnh.se": "greenhouse",
    "lever.co": "lever",
    "ashbyhq.com": "ashby",
    "gem.com": "gem",
    "myworkdayjobs.com": "workday",
    "workday.com": "workday",
    "linkedin.com": "linkedin",
    "smartrecruiters.com": "smartrecruiters",
    "workable.com": "workable",
}


def detect_from_url(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    for needle, name in _HOST_MAP.items():
        if needle in host:
            return name
    return None


def detect_from_dom(page) -> str | None:
    """Certaines offres embarquent Greenhouse/Lever dans un iframe sur le site
    carrière de l'entreprise. On sonde le HTML pour repérer la signature."""
    try:
        html = page.content().lower()
    except Exception:  # noqa: BLE001
        return None
    for needle, name in (
        ("greenhouse", "greenhouse"),
        ("boards.greenhouse.io", "greenhouse"),
        ("jobs.lever.co", "lever"),
        ("ashby", "ashby"),
        ("myworkdayjobs", "workday"),
    ):
        if needle in html:
            return name
    return None


def detect(url: str, page=None) -> str:
    return detect_from_url(url) or (detect_from_dom(page) if page else None) or "generic"
