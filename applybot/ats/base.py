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
    (["preferred first name", "preferred name", "nickname"], "value:preferred_name"),
    (["first name", "given name", "prénom"], "value:first_name"),
    (["last name", "family name", "surname", "nom de famille"], "value:last_name"),
    (["full name", "your name", "candidate name", "nom complet"], "value:full_name"),
    (["email", "e-mail", "courriel"], "value:email"),
    (["phone", "mobile", "téléphone", "telephone"], "value:phone"),
    (["linkedin"], "value:linkedin"),
    (["github"], "value:github"),
    (["portfolio", "website", "personal site", "site web"], "value:portfolio"),
    # --- Autorisation de travail AVANT localisation (sinon "work in the country" matche "country") ---
    (["sponsor", "require sponsorship", "need sponsorship", "visa sponsorship"], "value:require_sponsorship"),
    (["authorized to work in the u", "authorized to work in the us", "us work authorization",
      "eligible to work in the u", "work in the united states"], "value:authorized_to_work_us"),
    (["authorized to work", "legally authorized", "work authorization", "right to work",
      "eligible to work", "legally entitled to work", "authorised to work"], "value:authorized_to_work_eu"),
    (["postal code", "zip", "code postal"], "value:postal_code"),
    (["street", "address line", "adresse"], "value:address_line"),
    (["city", "ville"], "value:city"),
    (["country", "pays"], "value:country"),
    (["location", "where are you", "localisation", "current location"], "value:location"),
    (["how did you hear", "referral source", "source"], "value:how_did_you_hear"),
    (["referral name", "who referred"], "value:referral_name"),
    (["salary", "compensation expectation", "expected pay", "desired salary", "rémunération"], "value:salary_expectation"),
    (["notice period", "préavis"], "value:notice_period"),
    (["cities are you available", "available to work", "which cities", "work location", "cities available"], "value:location"),
    (["start date", "earliest start", "when can you start", "date de début", "availability date"], "value:earliest_start_date"),
    (["relocate", "relocation", "déménager"], "value:willing_to_relocate"),
    (["work onsite", "on-site", "in-person", "in office", "in-office"], "value:willing_to_work_onsite"),
    (["remote"], "value:remote_ok"),
    (["years of experience", "years experience", "années d'expérience"], "value:years_of_experience"),
    (["highest degree", "level of education", "education level", "diplôme"], "value:highest_degree"),
    (["university", "school", "college", "établissement", "université"], "value:university"),
    (["field of study", "major", "domaine d'étude"], "value:field_of_study"),
    (["graduation year", "year of graduation", "année d'obtention"], "value:graduation_year"),
    (["gpa"], "value:gpa"),
    (["current company", "current employer", "entreprise actuelle"], "value:current_company"),
    (["current title", "current role", "job title", "poste actuel"], "value:current_title"),
    (["18 years", "over 18", "at least 18", "legal age", "majeur"], "value:over_18"),
    (["criminal", "convicted", "casier"], "value:criminal_record"),
    (["security clearance", "clearance"], "value:security_clearance"),
    (["previously employed", "worked here before", "former employee", "déjà travaillé"], "value:previously_employed_here"),
    (["non-compete", "non compete", "clause de non-concurrence"], "value:non_compete"),
    (["references", "référence"], "value:references_available"),
    (["consent", "gdpr", "data processing", "privacy policy", "consentement",
      "i certify", "certify", "i agree", "i acknowledge", "i understand",
      "true and correct", "terms and conditions", "agree to the"], "value:consent_data_processing"),
    (["pronoun"], "value:pronouns"),
    (["gender", "genre"], "value:gender"),
    (["hispanic", "latino"], "value:hispanic_latino"),
    (["race", "ethnicity", "ethnie"], "value:race_ethnicity"),
    (["veteran"], "value:veteran_status"),
    (["disability", "handicap"], "value:disability_status"),
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


def _resolve_value(profile: Profile, job: dict, key: str) -> str:
    """Valeur d'une clé de profil, avec ajustements selon l'offre :
    localisation dynamique + autorisation de travail selon le pays."""
    if key in ("location", "city", "country"):
        loc = profile.location_for(job)
        return loc.get("city" if key in ("location", "city") else "country", "")
    if key == "authorized_to_work_eu":
        return "No" if profile.location_for(job)["country"] == "United States" else "Yes"
    return str(profile.get(key, default="")).strip()


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

    # 1) CV : choisi selon l'intitulé du poste, upload sur le 1er input file
    resume = profile.resume_for(job.get("title", ""))
    if resume:
        try:
            fh = page.query_selector('input[type="file"]')
            if fh:
                fh.set_input_files(str(resume))
                report.filled.append("CV (upload)")
        except Exception:  # noqa: BLE001
            pass

    # 2) Lettre de motivation : révèle le champ ("Enter manually") et rédige via IA.
    #    Le textarea révélé n'est pas dans `fields` (extrait avant) -> pas de conflit.
    if use_ai:
        _handle_cover_letter(page, profile, job, report)

    for f in fields:
        sel = f'[data-applybot-id="{f["id"]}"]'
        label = f["label"]
        kind = classify(label)

        if kind == "skip" or f["type"] in ("file", "password"):
            report.skipped.append(label)
            continue

        if kind.startswith("value:"):
            key = kind.split(":", 1)[1]
            value = _resolve_value(profile, job, key)
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
            answer = (ai.cover_letter(profile, job) if _looks_like_cover(label)
                      else ai.answer_question(profile, job, label)) if label else None
            if answer:
                _apply(page, sel, f, answer, report, label, is_essay=True)
            else:
                report.unknown.append(label)
            continue

        # Heuristique : un <textarea> non reconnu = question ouverte -> IA
        if f["tag"] == "textarea" and use_ai and label:
            answer = (ai.cover_letter(profile, job) if _looks_like_cover(label)
                      else ai.answer_question(profile, job, label))
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


_COVER_KW = ("cover letter", "lettre de motivation", "motivation letter",
             "covering letter", "why do you want to work", "carta de presentación")


def _looks_like_cover(label: str) -> bool:
    n = _norm(label)
    return any(k in n for k in _COVER_KW) or n == "cover" or "cover letter" in n


def _handle_cover_letter(page, profile, job, report):
    """Clique 'Enter manually' pour révéler la zone lettre, puis la rédige (IA).
    Le bouton n'est pas toujours un <button> (souvent un <a>/<div>/<span>)."""
    # 1) révéler le champ : cliquer n'importe quel élément 'Enter manually'
    try:
        page.evaluate(
            r"""() => {
              const wanted = ['enter manually','write cover letter','rédiger',
                              'saisir manuellement','écrire'];
              const els = [...document.querySelectorAll('button,a,[role=button],div,span,label')];
              const b = els.find(e => wanted.includes((e.innerText||'').trim().toLowerCase()));
              if (b) { b.click(); return true; }
              return false;
            }"""
        )
        page.wait_for_timeout(800)
    except Exception:  # noqa: BLE001
        pass

    # 2) localiser le textarea de la lettre (révélé ou déjà présent)
    sel = page.evaluate(
        r"""() => {
          const norm = s => (s||'').toLowerCase();
          const kws = ['cover letter','lettre de motivation','motivation letter','covering letter'];
          const tas = [...document.querySelectorAll('textarea')];
          const match = el => {
            const idn = norm((el.id||'') + ' ' + (el.name||''));
            if (idn.includes('cover')) return true;
            const box = el.closest('.field,[class*=field],div');
            const ctx = norm((box ? box.innerText : '') + ' ' +
                             (el.getAttribute('aria-label')||'') + ' ' + (el.placeholder||''));
            return kws.some(k => ctx.includes(k));
          };
          const el = tas.find(match);
          if (!el) return null;
          el.setAttribute('data-applybot-cover', '1');
          return '[data-applybot-cover="1"]';
        }"""
    )
    if not sel:
        return  # pas de section lettre sur cette offre
    letter = ai.cover_letter(profile, job)
    if letter and _react_fill(page, sel, letter, "cover letter"):
        report.essays.append("Cover Letter (IA, personnalisée)")
    else:
        report.unknown.append("Cover Letter")


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


def _open_combo_options(page, sel) -> list:
    """Ouvre un react-select de façon robuste et renvoie ses options."""
    read = (
        "() => { const e=[...document.querySelectorAll('.select__option')];"
        " e.forEach((o,i)=>o.setAttribute('data-applybot-opt',String(i)));"
        " return e.map(o=>o.innerText.trim()); }"
    )
    for attempt in range(3):
        try:
            page.click(sel)
            page.wait_for_timeout(500 + attempt * 300)
            opts = page.evaluate(read)
            if opts:
                return opts
            # 2e tentative : cliquer l'input interne du widget
            try:
                page.click(sel + " input")
                page.wait_for_timeout(500)
                opts = page.evaluate(read)
                if opts:
                    return opts
            except Exception:  # noqa: BLE001
                pass
            _press_escape(page)
        except Exception:  # noqa: BLE001
            _press_escape(page)
    return []


def _fill_react_selects(page, profile, job, report, use_ai, passes: int = 3):
    """Remplit les react-select. Plusieurs passes : les widgets ratés (timing,
    menu pas encore chargé) sont retentés tant qu'il en reste des vides."""
    for _pass in range(passes):
        try:
            combos = _react_combo_labels(page)
        except Exception:  # noqa: BLE001
            return
        todo = [c for c in combos
                if not c["current"] or "select" in _norm(c["current"])]
        if not todo:
            return  # tout est rempli
        progressed = False
        for c in todo:
            label = c["label"]
            sel = f'[data-applybot-combo="{c["id"]}"]'
            opts = _open_combo_options(page, sel)
            if not opts:
                continue  # retenté à la passe suivante

            target = None
            kind = classify(label)
            if kind.startswith("value:"):
                value = _resolve_value(profile, job, kind.split(":", 1)[1])
                target = _pick_option(value, opts) if value else None
            if not target and use_ai and label:
                choice = ai.choose_option(profile, job, label, opts)
                target = _pick_option(choice, opts) if choice else None

            if target and target in opts:
                try:
                    page.click(f'[data-applybot-opt="{opts.index(target)}"]')
                    page.wait_for_timeout(200)
                    report.filled.append(f"{label} -> {target}")
                    progressed = True
                    continue
                except Exception:  # noqa: BLE001
                    pass
            _press_escape(page)
        if not progressed:
            break  # plus aucune amélioration possible

    # signaler ce qui reste vide après toutes les passes
    try:
        for c in _react_combo_labels(page):
            if not c["current"] or "select" in _norm(c["current"]):
                report.unknown.append(c["label"] or "menu (vide)")
    except Exception:  # noqa: BLE001
        pass


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
