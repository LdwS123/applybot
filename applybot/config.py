"""Chargement du profil (profile.yaml) et de l'environnement (.env)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")


class Profile:
    """Accès pratique aux données de profile.yaml."""

    def __init__(self, data: dict):
        self.data = data
        self.identity = data.get("identity", {})
        self.links = data.get("links", {})
        self.documents = data.get("documents", {})
        self.answers = data.get("standard_answers", {})
        self.narrative = data.get("narrative", {})

    @classmethod
    def load(cls, path: Path | str = ROOT / "profile.yaml") -> "Profile":
        with open(path, "r", encoding="utf-8") as f:
            return cls(yaml.safe_load(f))

    def _resolve_doc(self, raw: str | None) -> Path | None:
        if not raw:
            return None
        p = (ROOT / raw).resolve() if not os.path.isabs(raw) else Path(raw)
        return p if p.exists() else None

    # Mots-clés d'intitulé -> quel CV. Édite librement.
    _SALES_KW = ("sales", "bdr", "sdr", "business development", "account executive",
                 "account manager", "revenue", "partnership", "commercial")
    _PM_KW = ("product", "pm", "growth", "product manager", "produit")

    def resume_for(self, job_title: str | None) -> Path | None:
        """Choisit le CV selon l'intitulé du poste (fallback = resume_default)."""
        t = (job_title or "").lower()
        docs = self.documents
        if any(k in t for k in self._SALES_KW):
            key = "resume_sales"
        elif any(k in t for k in self._PM_KW):
            key = "resume_pm"
        else:
            key = "resume_default"
        return (self._resolve_doc(docs.get(key))
                or self._resolve_doc(docs.get("resume_default"))
                or self._resolve_doc(docs.get("resume_pm")))

    def resume_path(self) -> Path | None:
        """CV par défaut (utilisé par `run.py check`)."""
        return self.resume_for(None)

    def location_for(self, job: dict) -> dict:
        """Localisation à afficher selon la ville de l'offre.
        US -> ville US de l'offre ; sinon Paris (là où il vit)."""
        blob = " ".join(str(job.get(k, "")) for k in ("location", "title", "description")).lower()
        if any(k in blob for k in ("new york", "nyc", ", ny")):
            return {"city": "New York", "country": "United States", "location": "New York, NY"}
        if any(k in blob for k in ("san francisco", "bay area", ", ca", "sf,")):
            return {"city": "San Francisco", "country": "United States", "location": "San Francisco, CA"}
        if any(k in blob for k in ("london", "united kingdom", ", uk")):
            return {"city": "London", "country": "United Kingdom", "location": "London, UK"}
        if any(k in blob for k in ("berlin", "germany")):
            return {"city": "Berlin", "country": "Germany", "location": "Berlin, Germany"}
        if any(k in blob for k in ("paris", "france")):
            return {"city": "Paris", "country": "France", "location": "Paris, France"}
        # Défaut : là où il vit
        return {"city": "Paris", "country": "France", "location": "Paris, France"}

    def get(self, *keys, default=""):
        """Cherche une valeur dans identity/links/answers par clé, dans l'ordre."""
        for section in (self.identity, self.links, self.answers):
            for k in keys:
                if k in section and section[k] not in (None, ""):
                    return section[k]
        return default


# --- Environnement -----------------------------------------------------------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
# Modèle "rapide/pas cher" pour rédiger (remplissage).
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
# Modèle "fort" pour l'agent de vérification (juge la complétion/cohérence).
OPENAI_VERIFY_MODEL = os.getenv("OPENAI_VERIFY_MODEL", "gpt-4o").strip()
HEADED = os.getenv("HEADED", "true").strip().lower() in ("1", "true", "yes")

RUNS_DIR = ROOT / "runs"
RUNS_DIR.mkdir(exist_ok=True)
