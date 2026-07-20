"""Session navigateur Rustwright (drop-in Playwright), contexte persistant.

Rustwright réimplémente l'API Playwright en Rust : on change juste l'import.
Le reste du code est identique à du Playwright classique — donc si Rustwright
te pose souci un jour, remplacer `rustwright.sync_api` par `playwright.sync_api`
suffit.
"""
from __future__ import annotations

from pathlib import Path

from rustwright.sync_api import sync_playwright

from .config import ROOT, HEADED

USER_DATA_DIR = ROOT / ".browser_profile"


class Session:
    """Gère un contexte navigateur persistant (cookies/logins gardés)."""

    def __init__(self, headed: bool | None = None):
        self.headed = HEADED if headed is None else headed
        self._pw = None
        self.context = None

    def __enter__(self) -> "Session":
        USER_DATA_DIR.mkdir(exist_ok=True)
        self._pw = sync_playwright().start()
        self.context = self._pw.chromium.launch_persistent_context(
            str(USER_DATA_DIR),
            headless=not self.headed,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        return self

    def new_page(self):
        # Réutilise un onglet existant si dispo (contexte persistant en ouvre un).
        pages = self.context.pages
        return pages[0] if pages else self.context.new_page()

    def __exit__(self, *exc):
        try:
            if self.context:
                self.context.close()
        finally:
            if self._pw:
                self._pw.stop()


def confirm_login(page, service: str) -> None:
    """Pause manuelle : laisse l'utilisateur se connecter à un service protégé."""
    print(f"\n>>> Connecte-toi à {service} dans la fenêtre du navigateur si besoin.")
    input(">>> Appuie sur ENTRÉE une fois connecté pour continuer... ")


def review_pause(page, job_label: str) -> str:
    """Cœur du mode semi-auto : le bot a rempli, l'humain relit puis décide.

    Retour :
      "submitted" -> tu as cliqué Submit toi-même, on note comme envoyée
      "skip"      -> passer sans envoyer
      "quit"      -> arrêter le bot
    """
    print("\n" + "=" * 70)
    print(f"  FORMULAIRE PRÉ-REMPLI : {job_label}")
    print("  Relis dans le navigateur, corrige si besoin, puis clique 'Submit'.")
    print("-" * 70)
    print("  [ENTRÉE] = j'ai soumis, offre suivante")
    print("  s + ENTRÉE = passer cette offre (skip)")
    print("  q + ENTRÉE = arrêter le bot")
    print("=" * 70)
    choice = input("  > ").strip().lower()
    if choice == "q":
        return "quit"
    if choice == "s":
        return "skip"
    return "submitted"
