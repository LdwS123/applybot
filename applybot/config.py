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

    def resume_path(self) -> Path | None:
        raw = self.documents.get("resume_path")
        if not raw:
            return None
        p = (ROOT / raw).resolve() if not os.path.isabs(raw) else Path(raw)
        return p if p.exists() else None

    def get(self, *keys, default=""):
        """Cherche une valeur dans identity/links/answers par clé, dans l'ordre."""
        for section in (self.identity, self.links, self.answers):
            for k in keys:
                if k in section and section[k] not in (None, ""):
                    return section[k]
        return default


# --- Environnement -----------------------------------------------------------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
HEADED = os.getenv("HEADED", "true").strip().lower() in ("1", "true", "yes")

RUNS_DIR = ROOT / "runs"
RUNS_DIR.mkdir(exist_ok=True)
