# applybot — bot de candidature semi-auto (Rustwright)

Bot qui **remplit automatiquement** les formulaires de candidature (Greenhouse,
Lever, Ashby, Workday, LinkedIn) et **rédige tes réponses ouvertes avec l'IA** à
partir de ton CV — puis **s'arrête pour que tu relises et cliques « Submit »**
toi-même (mode semi-auto). Construit sur [Rustwright](https://github.com/Skyvern-AI/rustwright)
(clone de Playwright en Rust, anti-détection).

> **Pourquoi semi-auto ?** Chaque offre a des questions différentes et certains
> sites bloquent les bots. Le bot fait 90% du boulot (tous les champs + les
> rédactions), toi tu valides en 10 s. Résultat : bien plus fiable, meilleures
> candidatures, moins de risques de blocage/CGU qu'un envoi 100% automatique.

## Installation (déjà faite ici)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m rustwright install chromium
```

## Configuration

1. **Ton profil** → édite `profile.yaml` (nom, email, tél, réponses types,
   pitch pour l'IA). Tout est en clair, aucun code à toucher.
2. **Ton CV** → dépose ton PDF dans `documents/` et vérifie le chemin
   `documents.resume_path` dans `profile.yaml`.
3. **Clé OpenAI** → dans `.env` (déjà rempli). ⚠️ **Révoque la clé collée dans
   le chat et remplace-la ici.** Modèle par défaut : `gpt-4o-mini` (le moins cher).

Vérifie que tout est prêt :

```bash
python run.py check
```

## Utilisation

### 1) Trouver des offres (optionnel)

Liste les entreprises qui t'intéressent dans `companies.txt`
(`greenhouse:slug` ou `lever:slug`), puis :

```bash
python run.py discover "growth,product,business"   # filtre par mots-clés -> jobs.csv
```

Tu peux aussi remplir `jobs.csv` toi-même : une URL d'offre par ligne.

### 2) Postuler (semi-auto)

```bash
python run.py apply                # toutes les offres de jobs.csv
python run.py apply --limit 10     # les 10 premières
```

Le navigateur s'ouvre. Pour chaque offre le bot remplit tout, puis affiche :

```
[ENTRÉE]     = j'ai relu + cliqué Submit -> offre suivante
s + ENTRÉE   = passer cette offre
q + ENTRÉE   = arrêter
```

Connecte-toi **une seule fois** à LinkedIn/Workday dans la fenêtre : la session
est gardée (profil persistant dans `.browser_profile/`).

Toutes les candidatures sont journalisées dans `runs/applications_log.csv`.

## Architecture

| Fichier | Rôle |
|---|---|
| `profile.yaml` | Tes données (édite librement) |
| `applybot/config.py` | Chargement profil + `.env` |
| `applybot/browser.py` | Session Rustwright persistante + pause de validation |
| `applybot/ai.py` | Rédaction IA **factuelle** (verrou anti-invention dans le prompt) |
| `applybot/ats/detect.py` | Détection de l'ATS (URL + DOM) |
| `applybot/ats/base.py` | Remplisseur générique : label → intention → valeur. **Table d'intentions éditable en haut du fichier.** |
| `applybot/ats/fillers.py` | Étapes spécifiques par ATS (ouvrir le formulaire) |
| `applybot/discovery.py` | Découverte via API publiques Greenhouse/Lever |
| `applybot/runner.py` | Boucle principale + logging |
| `run.py` | CLI (`check` / `discover` / `apply`) |

## Limites honnêtes

- **Greenhouse / Lever / Ashby** : très bien gérés (formulaires standard).
- **Workday / LinkedIn** : multi-étapes + anti-bot. Le bot remplit l'écran
  courant ; tu gères la navigation entre pages et le submit. Plus de travail
  manuel.
- **CAPTCHA** : le bot ne les résout pas (volontairement). Tu les passes à la main.
- Vise **la qualité** : 40 offres ciblées + relues > 200 envoyées à l'aveugle.
