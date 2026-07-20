"""Démo visible : ouvre un vrai navigateur, remplit une offre, screenshot.
Pas de pause clavier — juste pour VOIR le bot travailler.
    python demo.py
"""
import os
os.environ["HEADED"] = "true"

from applybot import browser
browser.HEADED = True
from applybot.browser import Session
from applybot.runner import load_jobs, _job_context
from applybot.ats import detect as d, fillers
from applybot.config import Profile, RUNS_DIR

url = load_jobs("jobs.csv")[0]
prof = Profile.load()
print(f"\nDÉMO — j'ouvre le navigateur et je remplis :\n{url}\n")

with Session(headed=True) as sess:
    page = sess.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1500)
    ats = d.detect(url, page)
    job = _job_context(page, url)
    print(f"ATS détecté : {ats} | Poste : {job.get('title','')[:60]}")
    report = fillers.apply(page, ats, prof, job)
    print("Résultat :", report.summary())
    shot = RUNS_DIR / "demo_filled.png"
    page.screenshot(path=str(shot), full_page=True)
    print(f"\nScreenshot : {shot}")
    print("Fenêtre ouverte 30 s — regarde le formulaire rempli, puis ferme.")
    page.wait_for_timeout(30000)
print("\nDémo terminée.")
