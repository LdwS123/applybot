"""Remplisseur générique de formulaires : lit les champs + leurs labels,
les mappe vers le profil, remplit. Sert de base à tous les ATS.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from ..config import Profile
from .. import ai

# ---------------------------------------------------------------------------
# TABLE D'INTENTIONS  ->  édite librement les mots-clés à gauche.
# Chaque règle : (liste de mots-clés cherchés dans le label, clé de valeur).
# La clé "value:xxx" pointe vers profile.get('xxx'). "essay" = question ouverte
# routée vers l'IA. "skip" = on ne touche pas (ex: mot de passe).
# ---------------------------------------------------------------------------
INTENT_RULES: list[tuple[list[str], str]] = [
    (["first name", "given name", "prénom"], "value:first_name"),
    (["last name", "family name", "surname", "nom de famille"], "value:last_name"),
    (["full name", "your name", "candidate name", "nom complet"], "value:full_name"),
    (["email", "e-mail", "courriel"], "value:email"),
    (["phone", "mobile", "téléphone", "telephone"], "value:phone"),
    (["linkedin"], "value:linkedin"),
    (["github"], "value:github"),
    (["portfolio", "website", "personal site", "site web"], "value:portfolio"),
    (["city", "ville"], "value:city"),
    (["country", "pays"], "value:country"),
    (["location", "where are you", "localisation", "current location"], "value:location"),
    (["how did you hear", "referral source", "source"], "value:how_did_you_hear"),
    (["sponsor", "visa", "require sponsorship"], "value:require_sponsorship"),
    (["authorized to work", "legally authorized", "work authorization"], "value:work_authorization_us"),
    (["salary", "compensation expectation", "expected pay", "rémunération"], "value:salary_expectation"),
    (["notice period", "préavis"], "value:notice_period"),
    (["start date", "available", "disponibilité", "earliest start"], "value:earliest_start_date"),
    (["relocate", "relocation", "déménager"], "value:willing_to_relocate"),
    (["remote"], "value:remote_ok"),
    (["years of experience", "years experience"], "value:years_of_experience"),
    (["pronoun"], "value:pronouns"),
    (["gender"], "value:gender"),
    (["race", "ethnicity", "hispanic"], "value:race_ethnicity"),
    (["veteran"], "value:veteran_status"),
    (["disability"], "value:disability_status"),
    # Questions ouvertes -> IA
    (["why do you want", "why are you interested", "why this", "why us",
      "cover letter", "tell us about", "what interests you", "motivation",
      "describe why", "what makes you"], "essay"),
    # À ne jamais remplir automatiquement
    (["password", "mot de passe"], "skip"),
]

# JS injecté : tague chaque champ et renvoie [{id, tag, type, label, options}]
_EXTRACT_JS = r"""
() => {
  function labelFor(el) {
    if (el.id) {
      const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (l && l.innerText.trim()) return l.innerText.trim();
    }
    const wrap = el.closest('label');
    if (wrap && wrap.innerText.trim()) return wrap.innerText.trim();
    const aria = el.getAttribute('aria-label');
    if (aria) return aria.trim();
    const alb = el.getAttribute('aria-labelledby');
    if (alb) { const t = document.getElementById(alb); if (t) return t.innerText.trim(); }
    // conteneur "form group" fréquent chez Greenhouse/Ashby
    const grp = el.closest('.field, .application-field, div[class*="field"]');
    if (grp) {
      const lab = grp.querySelector('label, .label, legend');
      if (lab && lab.innerText.trim()) return lab.innerText.trim();
    }
    const ph = el.getAttribute('placeholder') || el.getAttribute('name');
    if (ph) return ph;
    // DERNIER RECOURS (multilingue) : le texte le plus proche au-dessus/à gauche
    return nearbyText(el);
  }
  // Trouve le libellé visible par proximité géométrique (aucun lien DOM requis).
  function nearbyText(el) {
    const r = el.getBoundingClientRect();
    if (!r.width && !r.height) return '';
    let best = '', bestDist = 1e9;
    document.querySelectorAll('label,span,div,p,legend,strong,b,h1,h2,h3,h4,h5').forEach(t => {
      if (t.querySelector('input,textarea,select')) return;      // pas un conteneur de champ
      const txt = (t.innerText || '').trim();
      if (!txt || txt.length > 70) return;
      const tr = t.getBoundingClientRect();
      if (!tr.width || !tr.height) return;
      const above = tr.bottom <= r.top + 6 && (r.top - tr.bottom) < 70 && Math.abs(tr.left - r.left) < 260;
      const left = tr.right <= r.left + 6 && (r.left - tr.right) < 260 && Math.abs(tr.top - r.top) < 28;
      if (above || left) {
        const dist = Math.hypot(tr.left - r.left, tr.top - r.top);
        if (dist < bestDist) { bestDist = dist; best = txt; }
      }
    });
    return best;
  }
  const out = [];
  let i = 0;
  const els = document.querySelectorAll('input, textarea, select');
  els.forEach(el => {
    const type = (el.type || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'reset'].includes(type)) return;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return;
    const bid = 'applybot-' + (i++);
    el.setAttribute('data-applybot-id', bid);
    let options = [];
    if (el.tagName.toLowerCase() === 'select') {
      options = Array.from(el.options).map(o => o.text.trim()).filter(Boolean);
    }
    out.push({ id: bid, tag: el.tagName.toLowerCase(), type, label: labelFor(el), options });
  });
  return out;
}
"""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def classify(label: str) -> str:
    """Renvoie 'value:key', 'essay' ou 'skip' ou '' (non reconnu)."""
    n = _norm(label)
    if not n:
        return ""
    # match direct par sous-chaîne d'abord (fiable), puis fuzzy en secours
    for keywords, target in INTENT_RULES:
        for kw in keywords:
            if kw in n:
                return target
    best_target, best_score = "", 0
    for keywords, target in INTENT_RULES:
        for kw in keywords:
            score = fuzz.partial_ratio(kw, n)
            if score > best_score:
                best_score, best_target = score, target
    return best_target if best_score >= 88 else ""


def _pick_option(value: str, options: list[str]) -> str | None:
    """Choisit l'option de <select> la plus proche de `value`."""
    if not options:
        return None
    v = _norm(value)
    best, score = None, 0
    for opt in options:
        s = fuzz.partial_ratio(v, _norm(opt))
        if s > score:
            score, best = s, opt
    return best if score >= 60 else None


class FillReport:
    def __init__(self):
        self.filled: list[str] = []
        self.essays: list[str] = []
        self.skipped: list[str] = []
        self.unknown: list[str] = []

    def summary(self) -> str:
        return (
            f"{len(self.filled)} champs remplis, {len(self.essays)} réponses IA, "
            f"{len(self.unknown)} non reconnus (à vérifier à la main)."
        )


def fill_form(page, profile: Profile, job: dict, use_ai: bool = True) -> FillReport:
    """Remplit tout ce qui est reconnu. Retourne un rapport."""
    report = FillReport()
    fields = page.evaluate(_EXTRACT_JS)
    pending: list[tuple] = []  # champs non reconnus -> classés par l'IA (multilingue)

    # 1) CV : upload sur le premier input file trouvé
    resume = profile.resume_path()
    if resume:
        try:
            fh = page.query_selector('input[type="file"]')
            if fh:
                fh.set_input_files(str(resume))
                report.filled.append("CV (upload)")
        except Exception:  # noqa: BLE001
            pass

    for f in fields:
        sel = f'[data-applybot-id="{f["id"]}"]'
        label = f["label"]
        kind = classify(label)

        if kind == "skip" or f["type"] in ("file", "password"):
            report.skipped.append(label)
            continue

        if kind.startswith("value:"):
            key = kind.split(":", 1)[1]
            value = str(profile.get(key, default="")).strip()
            if not value:
                report.unknown.append(label)
                continue
            _apply(page, sel, f, value, report, label,
                   ai_ctx=(profile, job) if use_ai else None)
            continue

        if kind == "essay":
            if not use_ai:
                report.unknown.append(label)
                continue
            answer = ai.answer_question(profile, job, label) if label else None
            if answer:
                _apply(page, sel, f, answer, report, label, is_essay=True)
            else:
                report.unknown.append(label)
            continue

        # Heuristique : un <textarea> non reconnu = question ouverte -> IA
        if f["tag"] == "textarea" and use_ai and label:
            answer = ai.answer_question(profile, job, label)
            if answer:
                _apply(page, sel, f, answer, report, label, is_essay=True)
                continue

        # Menu déroulant non reconnu -> l'IA choisit la meilleure option
        if f["tag"] == "select" and f["options"] and use_ai and label:
            choice = ai.choose_option(profile, job, label, f["options"])
            opt = _pick_option(choice, f["options"]) if choice else None
            if opt:
                try:
                    page.select_option(sel, label=opt)
                    report.filled.append(f"{label} -> {opt} (IA)")
                    continue
                except Exception:  # noqa: BLE001
                    pass

        # Non reconnu par mots-clés -> on tente l'IA multilingue en fin de passe
        pending.append((sel, f, label))

    # Menus react-select (Greenhouse & co : pas de <select> natif)
    _fill_react_selects(page, profile, job, report, use_ai)

    # Filet IA multilingue : classe les champs restants (labels en toute langue)
    if use_ai and pending:
        _resolve_pending_with_ai(page, profile, job, report, pending)
    else:
        for _sel, f, label in pending:
            report.unknown.append(label or f["type"])

    return report


def _resolve_pending_with_ai(page, profile, job, report, pending):
    payload = [
        {"idx": i, "context": lbl, "tag": f["tag"], "type": f["type"]}
        for i, (sel, f, lbl) in enumerate(pending)
    ]
    decisions = ai.classify_fields(profile, job, payload)
    for i, (sel, f, label) in enumerate(pending):
        dec = decisions.get(str(i)) or decisions.get(i)
        if not dec or dec == "SKIP":
            report.unknown.append(label or f["type"])
            continue
        if dec == "ESSAY":
            answer = ai.answer_question(profile, job, label or "Tell us about yourself and your motivation")
            if answer and (f["tag"] == "textarea" or f["type"] in ("text", "")):
                if _react_fill(page, sel, answer, label):
                    report.essays.append((label or "question") + " (IA)")
                    continue
            report.unknown.append(label or f["type"])
            continue
        # dec = une clé de profil (ex: first_name, email...) dans n'importe quelle langue
        value = str(profile.get(dec, default="")).strip()
        if not value:
            report.unknown.append(label or dec)
            continue
        if f["tag"] == "select":
            _apply(page, sel, f, value, report, label, ai_ctx=(profile, job))
        elif _react_fill(page, sel, value, label):
            report.filled.append(f"{label or dec} -> {dec} (IA)")
        else:
            report.unknown.append(label or dec)


def _react_combo_labels(page) -> list[dict]:
    """Tague chaque widget react-select et renvoie [{id, label, current}]."""
    return page.evaluate(
        r"""() => {
          const out = [];
          document.querySelectorAll('.select__control').forEach((c, i) => {
            c.setAttribute('data-applybot-combo', String(i));
            let label = '', node = c;
            for (let up = 0; up < 7 && node; up++) {
              node = node.parentElement;
              if (!node) break;
              const lab = node.querySelector('label, legend, .label');
              if (lab && lab.innerText.trim()) { label = lab.innerText.trim(); break; }
            }
            out.push({ id: i, label: label, current: (c.innerText || '').trim() });
          });
          return out;
        }"""
    )


def _fill_react_selects(page, profile, job, report, use_ai):
    try:
        combos = _react_combo_labels(page)
    except Exception:  # noqa: BLE001
        return

    for c in combos:
        label = c["label"]
        # déjà rempli (autre chose que "Select...") -> on ne touche pas
        if c["current"] and "select" not in _norm(c["current"]):
            continue
        sel = f'[data-applybot-combo="{c["id"]}"]'
        try:
            page.click(sel)
            page.wait_for_timeout(550)
            opts = page.evaluate(
                "() => { const e=[...document.querySelectorAll('.select__option')];"
                " e.forEach((o,i)=>o.setAttribute('data-applybot-opt',String(i)));"
                " return e.map(o=>o.innerText.trim()); }"
            )
        except Exception:  # noqa: BLE001
            report.unknown.append(label or "combobox")
            continue

        if not opts:
            _press_escape(page)
            report.unknown.append(label or "combobox (vide)")
            continue

        # décider la valeur : intention connue, sinon IA
        target = None
        kind = classify(label)
        if kind.startswith("value:"):
            value = str(profile.get(kind.split(":", 1)[1], default=""))
            target = _pick_option(value, opts) if value else None
        if not target and use_ai and label:
            choice = ai.choose_option(profile, job, label, opts)
            target = _pick_option(choice, opts) if choice else None

        if target and target in opts:
            try:
                page.click(f'[data-applybot-opt="{opts.index(target)}"]')
                report.filled.append(f"{label} -> {target}")
                page.wait_for_timeout(150)
                continue
            except Exception:  # noqa: BLE001
                pass
        _press_escape(page)
        report.unknown.append(label or "combobox")


def _press_escape(page):
    try:
        page.keyboard.press("Escape")
    except Exception:  # noqa: BLE001
        try:
            page.click("body")
        except Exception:  # noqa: BLE001
            pass


def _react_fill(page, sel: str, value: str, label: str = "") -> bool:
    """Écrit dans un input/textarea de façon compatible React (setter natif +
    event 'input' bubblé). Si l'étiquette data-applybot-id a sauté (re-render
    React sur Ashby & co), re-localise le champ par son `label`."""
    import json as _json

    js = (
        "() => {"
        " const norm=s=>(s||'').toLowerCase().replace(/\\s+/g,' ').trim();"
        " const wl=norm(%s);"
        " const labelOf=el=>{"
        "   if(el.id){const l=document.querySelector('label[for=\"'+CSS.escape(el.id)+'\"]'); if(l&&l.innerText.trim())return l.innerText.trim();}"
        "   const w=el.closest('label'); if(w&&w.innerText.trim())return w.innerText.trim();"
        "   const a=el.getAttribute('aria-label'); if(a)return a;"
        "   const g=el.closest('.field,[class*=field],div'); if(g){const l=g.querySelector('label,legend,.label'); if(l&&l.innerText.trim())return l.innerText.trim();}"
        "   return el.getAttribute('placeholder')||el.name||'';"
        " };"
        " let el=document.querySelector(%s);"
        " if(!el && wl){ el=[...document.querySelectorAll('input,textarea')].find(e=>{const nl=norm(labelOf(e)); return nl && (nl.includes(wl)||wl.includes(nl));}); }"
        " if(!el) return false;"
        " el.focus();"
        " const proto = el.tagName==='TEXTAREA'?window.HTMLTextAreaElement.prototype:window.HTMLInputElement.prototype;"
        " const d=Object.getOwnPropertyDescriptor(proto,'value');"
        " (d&&d.set?d.set:function(v){this.value=v;}).call(el,%s);"
        " el.dispatchEvent(new Event('input',{bubbles:true}));"
        " el.dispatchEvent(new Event('change',{bubbles:true}));"
        " el.blur();"
        " return el.value===%s; }"
    ) % (_json.dumps(label), _json.dumps(sel), _json.dumps(value), _json.dumps(value))
    try:
        return bool(page.evaluate(js))
    except Exception:  # noqa: BLE001
        return False


def _apply(page, sel, f, value, report, label, is_essay=False, ai_ctx=None):
    """Écrit `value` dans le champ selon son type.

    ai_ctx = (profile, job) : si fourni, un <select> dont la valeur ne matche
    aucune option bascule sur un choix IA plutôt que de rester vide.
    """
    try:
        if f["tag"] == "select":
            opt = _pick_option(value, f["options"])
            if not opt and ai_ctx:
                profile, job = ai_ctx
                choice = ai.choose_option(profile, job, label, f["options"])
                opt = _pick_option(choice, f["options"]) if choice else None
            if opt:
                page.select_option(sel, label=opt)
                report.filled.append(f"{label} -> {opt}")
            else:
                report.unknown.append(label)
        elif f["type"] in ("radio", "checkbox"):
            # On coche seulement les oui/consentements évidents.
            if _norm(value) in ("yes", "oui", "true", "1"):
                page.check(sel)
                report.filled.append(f"{label} (coché)")
            else:
                report.unknown.append(label)
        else:
            if _react_fill(page, sel, value, label):
                (report.essays if is_essay else report.filled).append(
                    (label + " (IA)") if is_essay else label
                )
            else:
                try:
                    page.fill(sel, value)  # dernier repli
                    (report.essays if is_essay else report.filled).append(label)
                except Exception:  # noqa: BLE001
                    report.unknown.append(label)
    except Exception as e:  # noqa: BLE001
        report.unknown.append(f"{label} [erreur: {e}]")
