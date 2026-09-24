# Flux WM Aggregate — Explorateur de presse mondiale

Flux WM Aggregate collecte en continu les articles publiés par plus d'un millier de médias du monde entier, les classe automatiquement (thème, pays, région, intérêt naval, fiabilité de la source) et les publie dans un site web statique qui permet de les explorer, de les croiser et de les télécharger.

Le projet s'appuie sur le catalogue de flux RSS du projet open source [World Monitor](https://github.com/koala73/worldmonitor) (koala73) : à chaque passage, la dernière version de ce catalogue est récupérée, donc les sources ajoutées côté World Monitor sont suivies automatiquement.

À la dernière génération, l'archive compte environ **184 000 articles**.

---

## Sommaire

1. [Ce que fait le projet](#ce-que-fait-le-projet)
2. [Architecture](#architecture)
3. [Le pipeline en détail](#le-pipeline-en-détail)
4. [Le site web](#le-site-web)
5. [Lancer le projet en local](#lancer-le-projet-en-local)
6. [Automatisation GitHub Actions](#automatisation-github-actions)
7. [Personnaliser la classification](#personnaliser-la-classification)
8. [Format des données](#format-des-données)
9. [Points d'attention](#points-dattention)

---

## Ce que fait le projet

Toutes les 30 minutes, un robot GitHub Actions :

1. télécharge le catalogue de flux RSS de World Monitor ;
2. interroge tous les flux en parallèle et garde uniquement les articles jamais vus ;
3. détecte la langue de chaque titre et traduit en anglais ceux qui ne le sont pas (hors ligne, avec Argos Translate), en conservant le titre original ;
4. classe chaque article : thème, pays traité, région du monde, zone maritime, score d'intérêt naval, note de fiabilité du média ;
5. ajoute le tout à l'archive et régénère les données du site ;
6. commite et pousse le résultat, ce qui met à jour le site GitHub Pages.

Aucun modèle d'IA ni service payant n'est utilisé pour la classification : elle repose sur des dictionnaires de mots-clés et de règles, éditables en texte brut.

---

## Architecture

```
Flux_WM_Aggregate-main/
├── .github/workflows/update.yml   # Cron GitHub Actions (collecte + publication)
├── requirements.txt               # openpyxl, argostranslate
├── index.html                     # Ancienne version du site (voir « Points d'attention »)
│
├── pipeline/                      # Tout le traitement Python
│   ├── collecteur.py              # 1. Collecte RSS  → logs.csv
│   ├── classify.py                # 2. Classification → CSV enrichi
│   ├── traduction.py              #    Détection de langue + traduction Argos
│   ├── assembler.py               # 3. Orchestration → archive + fichiers du site
│   ├── evaluer.py                 # Outil : mesure la qualité des dictionnaires
│   │
│   ├── themes.txt                 # Dictionnaire des thèmes
│   ├── regles.txt                 # Règles de contexte (prioritaires sur themes.txt)
│   ├── pays.txt                   # Dictionnaire des pays
│   ├── regions.json               # Pays → région du monde
│   ├── naval.txt                  # Barème d'intérêt naval
│   ├── regions_maritimes.txt      # Zones maritimes « chaudes »
│   ├── medias.csv                 # Fiches médias (siège, thème, note de fiabilité A–F)
│   ├── medias_alias.csv           # Fusion des déclinaisons d'un même média
│   ├── medias_bannis.txt          # Médias exclus (doublons purs)
│   ├── medias_langues.csv         # Langue déclarée des flux non anglophones
│   ├── source-tiers.json          # Classement des sources (copié depuis World Monitor)
│   │
│   ├── consolide_master.csv       # ARCHIVE COMPLÈTE (source de vérité)
│   ├── vus.txt                    # État : empreintes SHA-1 des liens déjà collectés
│   └── logs.csv.integres          # Dernier lot de logs intégré
│
└── docs/                          # Site statique servi par GitHub Pages
    ├── index.html                 # Application principale (Explorer, Graphiques, Cartographie)
    ├── carto.js / graph.js        # Onglets Cartographie et Graphe pondéré
    ├── secu.js / ui.js / doc.js   # Note aéronavale, retouches UI, onglet Documentation
    ├── data.js                    # Données du site (régénéré à chaque passage)
    ├── meta.json                  # Date de génération, nombre d'articles
    └── world_monitor.{csv,db,xlsx}# Exports complets (régénérés en mode complet)
```

---

## Le pipeline en détail

### 1. Collecte — `collecteur.py`

Le script récupère `src/config/feeds.ts` et `shared/source-tiers.json` directement depuis le dépôt World Monitor, extrait la liste des flux (nom + URL), puis les interroge avec 16 threads en parallèle. Il lit les formats RSS 2.0 et Atom et normalise les dates au format `YYYY-MM-DD HH:MM`.

Chaque lien est haché (SHA-1) et comparé au fichier `vus.txt` : seuls les nouveaux articles sont écrits dans `logs.csv` (`media;titre;lien;date`). Il est normal que certains flux soient en erreur à chaque passage, ils sont simplement ignorés.

Il n'utilise que la bibliothèque standard Python.

### 2. Classification — `classify.py`

Pour chaque ligne de `logs.csv` :

- **Exclusion** : les médias listés dans `medias_bannis.txt` sont écartés.
- **Langue et traduction** (`traduction.py`) : la langue est détectée par l'alphabet (cyrillique, arabe, CJK…), puis par comptage de mots-outils pour les langues latines, et en dernier recours par la langue déclarée du média. Les titres non anglais sont traduits par Argos Translate (open source, hors ligne). Si la traduction est impossible ou visiblement ratée (boucle de répétition, mot géant, longueur aberrante), l'article est conservé avec son titre original. Aucune langue n'est jetée.
- **Média canonique** : les variantes (« Reuters World », « Reuters Business »…) sont rattachées à un seul média via `medias_alias.csv`, puis enrichies avec sa fiche dans `medias.csv`.
- **Thème** : les règles de `regles.txt` sont testées en premier (première règle qui correspond l'emporte). Sinon, un score par mots-clés est calculé à partir de `themes.txt`. Si rien ne correspond, le thème du média sert de repli.
- **Pays** : score par mots-clés sur `pays.txt`. Un mot faible seul ne suffit jamais. Pour les médias locaux ou politiques, le pays du siège sert de repli. Un niveau de confiance est enregistré (`high`, `medium`, `media-default`, `none`).
- **Région** : déduite du pays via `regions.json`.
- **Intérêt naval** : somme des poids des mots de `naval.txt` trouvés dans le titre, sans plafond.
- **Zone maritime** : la zone de `regions_maritimes.txt` qui a le plus de mots-clés dans le titre (Ormuz, Taïwan, mer de Chine méridionale, mer Rouge, Suez, Panama, Malacca, mer Noire, Baltique, Arctique).
- **Fiabilité** : notation de A (1) à F (4,5) issue de `medias.csv`. Une source inconnue reçoit F / 4,5 par défaut. Un indice composite est calculé :
  `intérêt_par_fiabilité = 0,6 / indice_fiabilité + intérêt_naval × 0,4 / 40`

### 3. Assemblage — `assembler.py`

C'est le script qui orchestre tout. Il fonctionne en deux modes pour éviter que chaque passage devienne de plus en plus long :

| Mode | Commande | Ce qu'il fait |
|---|---|---|
| **Léger** (défaut) | `python pipeline/assembler.py` | Traduit les titres encore non traduits (et répare les traductions cassées), classe les nouveaux logs, les ajoute à l'archive, régénère uniquement `data.js` et `meta.json`. |
| **Complet** | `python pipeline/assembler.py --full` | Tout le mode léger, plus un re-scan de toute l'archive avec les dictionnaires actuels (bannissements, fusions de médias, fiches, dates, scores navals, zones maritimes), et régénération des gros exports CSV / SQLite / XLSX. |
| **Sans logs** | `python pipeline/assembler.py --no-logs` | Régénère le site depuis l'archive sans classer de nouveaux articles. |

Après intégration, `logs.csv` est renommé en `logs.csv.integres`. Les doublons sont éliminés par lien.

Lancez le mode complet après chaque modification des dictionnaires, pour que l'ancienne archive en profite.

### 4. Évaluation — `evaluer.py`

Compare la classification automatique à un fichier de référence classé à la main (5 499 articles) et affiche le taux d'accord par thème et par pays, ainsi que les confusions les plus fréquentes :

```bash
python pipeline/evaluer.py world_monitor_consolide_1.xlsx
```

Le fichier de référence n'est pas inclus dans le dépôt.

---

## Le site web

Le site est une application HTML/JavaScript entièrement statique (dossier `docs/`), sans framework. Elle charge `data.js` au démarrage et propose :

- **🔍 Explorer** : tableau paginé et triable de tous les articles, avec recherche plein texte, filtres (pays, thème, média, région, période…) et fiches détaillées par pays, média, thème et région.
- **📊 Graphiques croisés** : un générateur de graphiques où l'on choisit une dimension en X (y compris jour, mois, année), une mesure, un découpage optionnel, le type de graphique et un top N.
- **🗺️ Cartographie** : carte du monde colorée selon la mesure choisie, avec une couche optionnelle des détroits stratégiques.
- **Graphe pondéré** : réseau orienté entre deux dimensions (par exemple Média → Pays traité), où l'épaisseur des liens représente le nombre d'articles. Rendu avec vis-network, chargé depuis jsDelivr.
- **Documentation** : un mini-blog de billets. Pour en ajouter un, copiez un bloc dans le tableau `POSTS` de `docs/doc.js`.
- **Note aéronavale** (`secu.js`) : une colonne « 🛡 Fiab. aéronavale » dans le tableau, calculée ainsi : `(6 − indice_fiabilité) × intérêt_naval ÷ 100`.
- **🔄 Actualiser** : recharge les données les plus récentes sans recharger la page.
- **⬇ Télécharger** : export filtré (dates, thèmes, médias, pays, régions) en CSV, ou export complet en XLSX / SQLite.

Les modules `carto.js`, `graph.js`, `secu.js`, `ui.js` et `doc.js` sont autonomes : chacun s'ajoute avec une simple balise `<script>` en fin de `index.html` et réutilise les fonctions déjà présentes dans la page.

---

## Lancer le projet en local

### Prérequis

- Python 3.11 ou plus récent
- Un accès internet (pour la collecte et le téléchargement des modèles de traduction)

### Installation

```bash
git clone <url-du-dépôt>
cd Flux_WM_Aggregate-main
pip install -r requirements.txt
```

`openpyxl` sert uniquement à l'export XLSX et à `evaluer.py`. `argostranslate` sert à la traduction. Les deux sont facultatifs : sans eux, le pipeline tourne quand même, en sautant l'étape concernée. Au premier lancement, Argos télécharge un modèle par langue rencontrée (dans `~/.local/share/argos-translate`), ce qui peut prendre du temps.

### Lancer le pipeline

Depuis la racine du dépôt :

```bash
# 1. Collecter les nouveaux articles
python pipeline/collecteur.py

# Variante de test rapide, sur 10 flux seulement
python pipeline/collecteur.py --max-feeds 10

# 2. Classer et régénérer le site
python pipeline/assembler.py           # mode léger
python pipeline/assembler.py --full    # mode complet (plus long)
```

On peut aussi utiliser le classificateur seul sur n'importe quel fichier `media;titre;lien;date` :

```bash
python pipeline/classify.py mes_logs.csv -o resultat.csv
```

### Ouvrir le site

Le site charge ses données avec `fetch()`, donc un double-clic sur `index.html` ne suffit pas (le navigateur bloque les requêtes en `file://`). Il faut le servir via un petit serveur HTTP :

```bash
cd docs
python -m http.server 8000
```

Puis ouvrir <http://localhost:8000>.

---

## Automatisation GitHub Actions

Le workflow `.github/workflows/update.yml` s'exécute :

- **toutes les 30 minutes** en mode léger ;
- **chaque lundi à 04:00 UTC** en mode complet ;
- **à la demande**, depuis l'onglet *Actions* → *Mise à jour World Monitor* → *Run workflow*, en choisissant `leger` ou `complet`.

Il installe les dépendances (l'échec d'Argos n'est pas bloquant), met en cache les modèles de traduction, lance `collecteur.py` puis `assembler.py`, et commite les changements sous le nom `wm-bot`.

Pour qu'il fonctionne sur votre propre fork :

1. Dans *Settings → Actions → General*, autorisez les workflows en lecture et écriture (*Read and write permissions*).
2. Dans *Settings → Pages*, choisissez la branche `main` et le dossier `/docs` comme source.
3. Pour une fréquence horaire au lieu de 30 minutes, remplacez `'*/30 * * * *'` par `'0 * * * *'` dans le workflow.

---

## Personnaliser la classification

Tous les dictionnaires sont de simples fichiers texte, insensibles à la casse, où les lignes commençant par `#` sont des commentaires. Après une modification, lancez `assembler.py --full` pour réappliquer les changements à toute l'archive, et `evaluer.py` pour en mesurer l'effet.

**`themes.txt` et `pays.txt`** : une classe par ligne. Un `*` devant un mot en fait un mot fort (2 points au lieu d'1). En cas d'égalité, le mot trouvé le plus tôt dans le titre l'emporte, puis l'ordre des lignes.
```
Politique américaine: *trump, *white house, *congress, supreme court, gop
```

**`regles.txt`** : règles de contexte, testées avant les mots-clés. `+` signifie « et », `|` signifie « ou », `!` exclut, et `@pays` représente n'importe quel pays du dictionnaire (`@pays + @pays` exige deux pays différents). La première règle qui correspond gagne.
```
Guerre/violence: @pays + strikes|struck|strike + !deal|agreement|trade|union|workers
```

**`naval.txt`** : un poids par ligne, suivi de ses mots.
```
20: navy, aircraft carrier, submarine, warship
2: ship, sea, port
```

**`regions_maritimes.txt`** : une zone par ligne, suivie de ses mots-clés.

**`medias.csv`** : `media;pays_siege;theme_media;note;indice_fiabilite;notation;justification`. La notation va de A (le plus fiable, indice 1) à F (inconnu, indice 4,5).

**`medias_alias.csv`** : `alias;canonique`. Un `*` final désigne un préfixe (`Guardian *;The Guardian`). Les correspondances exactes passent avant les préfixes.

**`medias_bannis.txt`** : un nom par ligne, `*` final pour un préfixe. Sert uniquement à écarter les éditions en langue étrangère d'un média dont l'édition anglaise est déjà collectée.

**`medias_langues.csv`** : `media;langue` (codes ISO, par exemple `de`, `fr`).

---

## Format des données

L'archive `consolide_master.csv` (séparateur `;`, UTF-8) et les exports contiennent les colonnes suivantes :

| Colonne | Description |
|---|---|
| `nom_du_media` | Nom canonique du média |
| `titre` | Titre en anglais (traduit si nécessaire) |
| `titre_vo` | Titre original, si l'article a été traduit |
| `langue` | Langue détectée (code ISO) |
| `lien` | URL de l'article (clé d'unicité) |
| `time_stamp` | Date de publication, `YYYY-MM-DD HH:MM` |
| `country_headquarters` | Pays du siège du média |
| `country_article` | Pays traité par l'article |
| `confiance_pays_article` | `high`, `medium`, `media-default` ou `none` |
| `region` | Région du monde du pays traité |
| `sujet_article` | Thème de l'article |
| `sujet_media` | Thème principal du média |
| `official_rating` | Note brute issue de la fiche média |
| `notation` | Notation de fiabilité, A à F |
| `indice_fiabilite` | 1 (très fiable) à 5 ; 4,5 par défaut |
| `fiabilité_calcul` | 40 / indice_fiabilité |
| `fiabilité2` | 0,6 / indice_fiabilité |
| `indice_interet_naval` | Score naval (somme des poids, sans plafond) |
| `intérêt marine calcul` | intérêt_naval × 0,4 / 40 |
| `intérêt_par_fiabilité` | fiabilité2 + intérêt marine calcul |
| `region_maritime` | Zone maritime détectée, vide si aucune |

L'export SQLite (`docs/world_monitor.db`) contient une seule table, `articles`, avec ces mêmes colonnes.

---

## Points d'attention

- **Taille de `data.js`** : le fichier fait environ 104 Mo, soit juste sous la limite de 100 Mio par fichier imposée par GitHub. Il grossit à chaque passage, et le push finira par être refusé. Parmi les pistes possibles : découper les données par période, compresser, ne publier qu'une fenêtre glissante dans `data.js`, ou utiliser Git LFS pour les gros exports. Le même problème guette `consolide_master.csv` (environ 85 Mo). Par ailleurs, l'historique git s'alourdit à chaque commit de ces fichiers.
- **Deux `index.html`** : celui à la racine est une ancienne version (la mention « 5 499 articles » y est codée en dur, et il lui manque le panneau de téléchargement). Le site réel est `docs/index.html`. La copie à la racine peut être supprimée.
- **Fichiers parasites** : l'archive contient des fichiers `*:Zone.Identifier` (métadonnées Windows/WSL), des `.DS_Store` (macOS) et des `__pycache__/`. Ils peuvent être supprimés et ajoutés à un `.gitignore` :
  ```
  *Zone.Identifier
  .DS_Store
  __pycache__/
  ```
- **`requirements.txt` en double** : le même fichier existe à la racine et dans `pipeline/`.
- **Dépendance externe** : la collecte dépend du format de `feeds.ts` dans le dépôt World Monitor. Si sa structure change, l'expression régulière de `parse_feeds()` devra être adaptée.
- **Fiabilité de la classification** : elle repose sur des mots-clés et n'est donc qu'indicative. Utilisez `evaluer.py` pour la mesurer, et la colonne `confiance_pays_article` pour filtrer les attributions de pays les moins sûres.
