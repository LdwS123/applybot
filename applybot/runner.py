"""Boucle principale : pour chaque offre -> ouvrir, détecter l'ATS, remplir,
PAUSE validation (tu relis + Submit), logguer le résultat.
"""
from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from .config import Profile, RUNS_DIR
from .browser import Session, review_pause
from .ats import detect as detectmod
from .ats import fillers

LOG = RUNS_DIR / "applications_log.csv"


def _log(row: dict) -> None:
    new = not LOG.exists()
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "url", "ats", "status", "notes"])
        if new:
            w.writeheader()
        w.writerow(row)


def _job_context(page, url: str) -> dict:
    """Extrait titre / entreprise / description pour nourrir l'IA."""
    try:
        ctx = page.evaluate(
            r"""() => {
              const meta = n => (document.querySelector(`meta[property="${n}"], meta[name="${n}"]`)||{}).content || '';
              const title = (document.querySelector('h1')||{}).innerText || document.title || '';
              const company = meta('og:site_name') || '';
              const body = (document.body ? document.body.innerText : '').slice(0, 2500);
              return { title: title.trim(), company: company.trim(), description: body };
            }"""
        )
    except Exception:  # noqa: BLE001
        ctx = {}
    ctx["url"] = url
    if not ctx.get("company"):
        # fallback : slug d'entreprise depuis l'URL (lever/greenhouse)
        parts = [p for p in url.split("/") if p]
        ctx["company"] = parts[3] if len(parts) > 3 else ""
    return ctx


def load_jobs(path: Path | str) -> list[str]:
    urls: list[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            u = line.strip().split(",")[0].strip()
            if u and u.startswith("http") and not u.startswith("#"):
                urls.append(u)
    return urls


def run(jobs_file: str, limit: int | None = None) -> None:
    profile = Profile.load()
    urls = load_jobs(jobs_file)
    if limit:
        urls = urls[:limit]

    if not profile.resume_path():
        print("⚠️  Aucun CV trouvé au chemin de profile.yaml -> l'upload sera sauté.")

    print(f"\n{len(urls)} offre(s) à traiter. Mode SEMI-AUTO : tu valides chaque envoi.\n")

    with Session() as sess:
        page = sess.new_page()
        print(">>> Si tu dois te connecter (LinkedIn/Workday), fais-le maintenant.")
        input(">>> ENTRÉE pour démarrer... ")

        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{len(urls)}] {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(1200)
            except Exception as e:  # noqa: BLE001
                print(f"   ❌ Navigation échouée: {e}")
                _log(_row(url, "?", "nav_error", str(e)))
                continue

            fillers.dive_into_iframe(page)  # formulaire dans un iframe ATS ?
            ats = detectmod.detect(url, page)
            job = _job_context(page, url)
            print(f"   ATS détecté : {ats}  |  {job.get('title','?')[:60]}")

            try:
                report = fillers.apply(page, ats, profile, job)
                print("   " + report.summary())
                if report.unknown:
                    print("   ⚠️  À vérifier: " + "; ".join(report.unknown[:6]))
            except Exception as e:  # noqa: BLE001
                print(f"   ❌ Remplissage échoué: {e}")
                _log(_row(url, ats, "fill_error", str(e)))
                # on laisse quand même la main pour finir à la main
            decision = review_pause(page, job.get("title", url))
            if decision == "quit":
                _log(_row(url, ats, "stopped", "arrêt utilisateur"))
                print("\nArrêt demandé. À bientôt.")
                break
            _log(_row(url, ats, decision, job.get("title", "")))

    print(f"\nJournal des candidatures : {LOG}")


def _row(url, ats, status, notes=""):
    return {
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "url": url,
        "ats": ats,
        "status": status,
        "notes": notes[:200],
    }
