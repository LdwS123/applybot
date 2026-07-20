"""Contrôleur mono-navigateur pour le dashboard : garde une session Rustwright
ouverte entre les requêtes, prépare (remplit) et envoie une candidature.

⚠️ L'API sync de Rustwright/Playwright doit tourner dans UN SEUL thread.
Le dashboard Flask est donc lancé en mode non-threadé (threaded=False).
"""
from __future__ import annotations

import datetime as dt

from .config import Profile
from .browser import Session
from .ats import detect as detectmod
from .ats import fillers
from .runner import _job_context, _log, _row


class Controller:
    def __init__(self):
        self._sess: Session | None = None
        self.page = None
        self.profile = Profile.load()
        self.current_url = None
        self.current_job = None
        self.current_ats = None

    def _ensure(self, force_new: bool = False):
        if force_new:
            self.close()
        if self._sess is None:
            self._sess = Session(headed=True).__enter__()
            self.page = self._sess.new_page()

    def _alive(self) -> bool:
        """Vrai si l'onglet répond encore (sinon la fenêtre a été fermée)."""
        try:
            self.page.evaluate("() => 1")
            return True
        except Exception:  # noqa: BLE001
            return False

    def prepare(self, url: str) -> dict:
        """Ouvre l'offre, détecte l'ATS, remplit. Retourne un rapport JSON.

        Se reconnecte automatiquement si le navigateur a été fermé entre-temps.
        """
        self._ensure()
        if not self._alive():
            self._ensure(force_new=True)  # la fenêtre avait été fermée -> on relance
        self.current_url = url
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:  # noqa: BLE001
            if "Session" in str(e) or "closed" in str(e) or "Protocol" in str(e):
                self._ensure(force_new=True)  # relance et une seule nouvelle tentative
                self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
            else:
                raise
        self.page.wait_for_timeout(1200)
        ats = detectmod.detect(url, self.page)
        job = _job_context(self.page, url)
        self.current_ats, self.current_job = ats, job
        report = fillers.apply(self.page, ats, self.profile, job)
        return {
            "url": url,
            "ats": ats,
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "filled": report.filled,
            "essays": report.essays,
            "unknown": report.unknown,
            "summary": report.summary(),
        }

    def submit(self) -> dict:
        """Clique le bouton d'envoi de la page courante."""
        if not self.page:
            return {"ok": False, "message": "Aucune offre préparée."}
        for selector in (
            'button:has-text("Submit application")',
            'button:has-text("Submit")',
            'button:has-text("Envoyer")',
            'button[type="submit"]',
            'input[type="submit"]',
        ):
            try:
                btn = self.page.query_selector(selector)
                if btn:
                    btn.click()
                    self.page.wait_for_timeout(1500)
                    _log(_row(self.current_url, self.current_ats, "submitted",
                              (self.current_job or {}).get("title", "")))
                    return {"ok": True, "message": "Candidature envoyée ✅"}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "message": f"Erreur envoi: {e}"}
        return {"ok": False, "message": "Bouton d'envoi introuvable — clique-le dans le navigateur."}

    def skip(self) -> dict:
        _log(_row(self.current_url, self.current_ats, "skip",
                  (self.current_job or {}).get("title", "")))
        return {"ok": True, "message": "Offre passée."}

    def close(self):
        if self._sess:
            try:
                self._sess.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
            self._sess = None
            self.page = None


controller = Controller()
