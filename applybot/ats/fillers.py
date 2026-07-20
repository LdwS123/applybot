"""Étapes spécifiques par ATS pour *révéler* le formulaire, puis délégation
au remplisseur générique (base.fill_form).

Greenhouse / Lever / Ashby sont des formulaires HTML standard -> le générique
suffit une fois le formulaire affiché. Workday / LinkedIn sont multi-étapes et
protégés : on prépare le terrain mais on s'appuie surtout sur ta validation
manuelle (semi-auto).
"""
from __future__ import annotations

from .base import fill_form, FillReport

def dive_into_iframe(page) -> bool:
    """Si le formulaire est dans un iframe ATS (Greenhouse/Lever/Ashby embed sur
    un site carrière type careers.datadoghq.com), navigue directement dessus pour
    l'avoir en top-level. Retourne True si on a plongé dans l'iframe."""
    try:
        src = page.evaluate(
            "() => { const f=[...document.querySelectorAll('iframe')]"
            ".find(f => /greenhouse|lever|ashby|myworkdayjobs/.test(f.src||''));"
            " return f ? f.src : null; }"
        )
    except Exception:  # noqa: BLE001
        return False
    if not src:
        return False
    try:
        page.goto(src, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)
        return True
    except Exception:  # noqa: BLE001
        return False


_APPLY_TEXTS = [
    "Apply for this job", "Apply Now", "Apply", "Submit application",
    "I'm interested", "Postuler",
]


def _click_apply_if_needed(page) -> None:
    """Si aucun champ de saisie n'est visible, tente de cliquer un bouton Apply."""
    try:
        has_fields = page.evaluate(
            "() => !!document.querySelector('input:not([type=hidden]), textarea')"
        )
    except Exception:  # noqa: BLE001
        has_fields = False
    if has_fields:
        return
    for text in _APPLY_TEXTS:
        try:
            btn = page.query_selector(f'button:has-text("{text}"), a:has-text("{text}")')
            if btn:
                btn.click()
                page.wait_for_timeout(1500)
                return
        except Exception:  # noqa: BLE001
            continue


def apply(page, ats: str, profile, job: dict) -> FillReport:
    """Point d'entrée unique. Prépare selon l'ATS puis remplit."""
    if ats in ("greenhouse", "lever", "ashby", "smartrecruiters", "workable", "generic"):
        _click_apply_if_needed(page)
        return fill_form(page, profile, job, use_ai=True)

    if ats in ("workday", "linkedin"):
        # Multi-étapes / login requis : on remplit ce qu'on peut sur l'écran
        # courant ; toi tu gères la navigation + submit (semi-auto strict).
        _click_apply_if_needed(page)
        report = fill_form(page, profile, job, use_ai=True)
        report.unknown.append(
            f"[{ats}] formulaire multi-étapes — vérifie chaque page à la main"
        )
        return report

    return fill_form(page, profile, job, use_ai=True)
