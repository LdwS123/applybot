#!/usr/bin/env python
"""Point d'entrée du bot de candidature (semi-auto, basé sur Rustwright).

Usage :
  python run.py check                      # vérifie config, clé OpenAI, CV
  python run.py discover "growth,product"  # trouve des offres -> jobs.csv
  python run.py apply                      # postule aux offres de jobs.csv
  python run.py apply --limit 5            # limite le nombre d'offres
  python run.py apply --file mesoffres.csv # autre fichier d'offres
"""
from __future__ import annotations

import argparse
import sys


def cmd_check(args):
    from applybot.config import Profile, OPENAI_MODEL, HEADED
    from applybot import ai

    prof = Profile.load()
    print("Profil     :", prof.identity.get("full_name"), "|", prof.identity.get("email"))
    resume = prof.resume_path()
    print("CV         :", resume or "❌ introuvable (voir documents.resume_path)")
    print("Navigateur :", "visible (semi-auto)" if HEADED else "headless")
    ok, msg = ai.ping()
    print("OpenAI     :", ("✅ " if ok else "❌ ") + msg)


def cmd_discover(args):
    from applybot.discovery import discover

    keywords = [k for k in (args.keywords or "").split(",") if k.strip()]
    print(f"Découverte via {args.companies} + agrégateurs (mots-clés: {keywords or 'tous'})")
    discover(args.companies, keywords,
             use_key_sources=not args.no_keys, include_yc=not args.no_yc)


def cmd_apply(args):
    from applybot.runner import run

    run(args.file, limit=args.limit)


def main():
    p = argparse.ArgumentParser(description="Bot de candidature semi-auto (Rustwright)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="Vérifie la config").set_defaults(func=cmd_check)

    d = sub.add_parser("discover", help="Scrape multi-sources (ATS + agrégateurs), classe par ville/niveau")
    d.add_argument("keywords", nargs="?", default="", help='ex: "growth,product,business" (vide = TOUT)')
    d.add_argument("--companies", default="companies.txt")
    d.add_argument("--no-keys", action="store_true", help="ignore Adzuna/The Muse (sources à clé API)")
    d.add_argument("--no-yc", action="store_true", help="saute la découverte startups YC (~1-2 min de moins)")
    d.set_defaults(func=cmd_discover)

    a = sub.add_parser("apply", help="Postule aux offres de jobs.csv (semi-auto)")
    a.add_argument("--file", default="jobs.csv")
    a.add_argument("--limit", type=int, default=None)
    a.set_defaults(func=cmd_apply)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
