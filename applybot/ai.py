"""Génération de texte (lettres + réponses ouvertes) via OpenAI.

Contraintes imposées par l'utilisateur :
- modèle le moins cher
- AUCUNE exagération ni invention : tout doit correspondre au CV (profile.yaml)
- ton motivé, sincère, humain (pas de baratin, pas de superlatifs creux)
"""
from __future__ import annotations

import json
import textwrap

from .config import OPENAI_API_KEY, OPENAI_MODEL, Profile

_client = None


def _client_or_none():
    global _client
    if not OPENAI_API_KEY:
        return None
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


SYSTEM_PROMPT = textwrap.dedent(
    """
    You write job-application text for one real candidate.

    ABSOLUTE RULES (non-negotiable):
    - Use ONLY facts present in the CANDIDATE FACTS block below. Never invent
      companies, job titles, dates, metrics, degrees, or skills.
    - No exaggeration, no inflated superlatives, no buzzword-stuffing, no
      "passionate about leveraging synergies" clichés. Plain, confident, human.
    - If the candidate lacks something the job asks for, do NOT fake it. Lean on
      adjacent real experience or genuine motivation to learn instead.
    - First person ("I"). Sound like a motivated real person, not a template.
    - Be concise. Short sentences. No filler.

    The candidate genuinely is motivated and has shipped real things — let that
    show through concrete facts, not adjectives.
    """
).strip()


def _facts_block(profile: Profile) -> str:
    n = profile.narrative
    lines = [
        f"Name: {profile.identity.get('full_name')}",
        f"Headline: {n.get('headline')}",
        f"Seeking: {n.get('seeking')}",
        f"Pitch: {n.get('pitch')}",
        "Achievements:",
        *[f"  - {a}" for a in n.get("key_achievements", [])],
        "Skills:",
        *[f"  - {s}" for s in n.get("skills", [])],
        f"Languages: {n.get('languages')}",
    ]
    return "\n".join(str(x) for x in lines)


def _chat(messages, max_tokens=350):
    client = _client_or_none()
    if client is None:
        return None
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=0.4,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


def cover_letter(profile: Profile, job: dict) -> str | None:
    """Lettre courte (150-200 mots) taillée pour l'offre, 100% factuelle."""
    user = textwrap.dedent(
        f"""
        CANDIDATE FACTS:
        {_facts_block(profile)}

        JOB:
        Company: {job.get('company', 'the company')}
        Title: {job.get('title', 'this role')}
        Description (may be partial):
        {(job.get('description') or '')[:1500]}

        Write a 150-200 word cover letter for THIS specific job. Tie 2-3 real
        achievements to what the role needs. End with genuine, specific motivation
        for this company. No greeting line placeholders like [Company] — use the
        real name if given, otherwise write naturally without brackets.
        """
    ).strip()
    return _chat(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
        max_tokens=400,
    )


def answer_question(profile: Profile, job: dict, question: str, max_words: int = 120) -> str | None:
    """Réponse à une question ouverte custom d'un formulaire ATS."""
    user = textwrap.dedent(
        f"""
        CANDIDATE FACTS:
        {_facts_block(profile)}

        JOB: {job.get('title', '')} at {job.get('company', '')}

        Application question:
        "{question}"

        Answer truthfully in first person, max {max_words} words, grounded only in
        the candidate facts. If the question asks about something not in the facts,
        answer honestly (e.g. willingness to learn) without inventing experience.
        """
    ).strip()
    return _chat(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
        max_tokens=260,
    )


def choose_option(profile: Profile, job: dict, question: str, options: list[str]) -> str | None:
    """Choisit LA meilleure option parmi `options` pour une question fermée.

    Retourne le texte exact d'une option (ou None). Reste factuel : ne choisit
    jamais une réponse qui contredirait le CV ; pour les questions démographiques,
    préfère 'decline / prefer not to say' si présent.
    """
    if not options:
        return None
    numbered = "\n".join(f"{i+1}. {o}" for i, o in enumerate(options))
    user = textwrap.dedent(
        f"""
        CANDIDATE FACTS:
        {_facts_block(profile)}

        JOB: {job.get('title', '')} at {job.get('company', '')}

        Question: "{question}"
        Options:
        {numbered}

        Pick the single best option for this candidate, truthfully.
        - If it's a yes/no fit or willingness question, choose what's true and
          favourable given the facts (e.g. open to relocation/in-person = yes).
        - For demographic/EEO questions (gender, race, veteran, disability),
          choose a 'decline' / 'prefer not to say' option if one exists.
        - Never pick an option that contradicts the candidate facts.

        Reply with the option text EXACTLY as written above, and nothing else.
        """
    ).strip()
    out = _chat(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
        max_tokens=40,
    )
    return out.strip().lstrip("0123456789. ").strip() if out else None


def ping() -> tuple[bool, str]:
    """Vérifie que la clé/modèle fonctionnent. Utilisé par `run.py check`."""
    client = _client_or_none()
    if client is None:
        return False, "Pas de OPENAI_API_KEY dans .env"
    try:
        out = _chat([{"role": "user", "content": "Reply with the single word: ok"}], max_tokens=5)
        return True, f"OpenAI OK (modèle {OPENAI_MODEL}) -> {out!r}"
    except Exception as e:  # noqa: BLE001
        return False, f"Erreur OpenAI: {e}"
