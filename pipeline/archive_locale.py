"""
Travailler en local sur l'archive complète stockée dans les Releases GitHub.

  python pipeline/archive_locale.py telecharger [--annee 2026]
      Télécharge les Releases « data-* » (ou une seule année) dans
      archive/AAAA/MM/AAAA-MM-JJ.parquet. Seuls les fichiers absents ou modifiés
      sont téléchargés : relancer la commande met l'archive locale à jour.

  python pipeline/archive_locale.py parquet
      Construit archive/world_monitor.parquet (toute l'archive en un seul fichier).

  python pipeline/archive_locale.py sqlite
      Construit archive/world_monitor.db (table « articles ») depuis archive/.

  python pipeline/archive_locale.py csv
      Construit archive/world_monitor.csv (un seul fichier, séparateur « ; »).

  python pipeline/archive_locale.py site --jours 60
      Génère le site local sur les N derniers jours, puis :
      cd docs && python -m http.server 8000

  python pipeline/archive_locale.py retraiter
      Retraitement complet : télécharge tout, réapplique les dictionnaires actuels
      à toute l'archive (assembler.py --full), puis renvoie les fichiers modifiés
      dans les Releases. Les jours récents sont laissés au workflow, qui les
      retraite lui-même, pour ne pas écraser ce qu'il vient de collecter.
      Nécessite GitHub CLI (gh) authentifié.

Le dépôt est lu dans WM_REPO (ex. export WM_REPO=user/depot), sinon déduit du
remote git « origin ». GH_TOKEN, s'il est défini, relève la limite de l'API.

Pour interroger l'archive sans rien exporter, DuckDB lit directement les fichiers :
  duckdb -c "SELECT country_article, count(*) n
             FROM 'archive/*/*/*.parquet'
             GROUP BY 1 ORDER BY n DESC LIMIT 20"
(pandas : pd.read_parquet('archive/2026/07') lit tout un mois.)
"""
import argparse
import csv
import datetime
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import archive  # noqa: E402


# ---------------------------------------------------------------- dépôt / API

def depot():
    if archive.REPO:
        return archive.REPO
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=archive.RACINE,
                             capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        url = ""
    m = re.search(r"github\.com[:/](.+?/.+?)(?:\.git)?$", url)
    if not m:
        sys.exit("Dépôt introuvable : définis WM_REPO (ex. export WM_REPO=user/depot)")
    return m.group(1)


API = os.environ.get("WM_API", "https://api.github.com")
_token = None


def jeton():
    """GH_TOKEN, sinon le jeton de GitHub CLI s'il est connecté (évite la limite
    de 60 requêtes/heure de l'API anonyme)."""
    global _token
    if _token is None:
        _token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
        if not _token:
            try:
                _token = subprocess.run(["gh", "auth", "token"], capture_output=True,
                                        text=True).stdout.strip()
            except FileNotFoundError:
                pass
    return _token


def _requete(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "wm-archive"})
    if url.startswith(API) and jeton():
        req.add_header("Authorization", f"Bearer {jeton()}")
    try:
        return urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        if e.code in (403, 429) and url.startswith(API):
            sys.exit("Limite de l'API GitHub atteinte : connecte GitHub CLI (gh auth login) "
                     "ou définis GH_TOKEN, puis relance.")
        raise


def api_pagine(url):
    """GET paginé sur l'API GitHub → liste de tous les éléments."""
    items = []
    while url:
        with _requete(url) as r:
            items += json.load(r)
            lien = r.headers.get("Link", "")
        m = re.search(r'<([^>]+)>;\s*rel="next"', lien)
        url = m.group(1) if m else None
    return items


def inventaire(repo, annee=None):
    """[(release, asset)] pour toutes les Releases data-*."""
    out = []
    for rel in api_pagine(f"{API}/repos/{repo}/releases?per_page=100"):
        nom = rel["tag_name"]
        if not nom.startswith("data-") or (annee and nom != f"data-{annee}"):
            continue
        for a in api_pagine(f"{API}/repos/{repo}/releases/{rel['id']}/assets?per_page=100"):
            if a["name"].endswith(".parquet"):
                out.append((nom, a))   # a["state"] != "uploaded" : envoi interrompu
    return out


def a_jour(path, asset):
    if not path.exists() or path.stat().st_size != asset["size"]:
        return False
    digest = asset.get("digest") or ""
    if digest.startswith("sha256:"):
        return hashlib.sha256(path.read_bytes()).hexdigest() == digest[7:]
    return True


# ---------------------------------------------------------------- commandes

def telecharger(annee=None):
    repo = depot()
    print(f"Inventaire des Releases de {repo}…")
    todo, echecs = [], []
    for release, asset in inventaire(repo, annee):
        if asset.get("state", "uploaded") != "uploaded":
            echecs.append(f"{release}/{asset['name']} (envoi incomplet sur GitHub)")
            continue
        path = archive.chemin_local(release, asset["name"])
        if not a_jour(path, asset):
            todo.append((release, asset["name"], path, asset["browser_download_url"]))
    print(f"{len(todo)} fichier(s) à télécharger")

    def dl(item):
        release, nom, path, url = item
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        try:
            with _requete(url, accept="application/octet-stream") as r, open(tmp, "wb") as f:
                f.write(r.read())
        except (urllib.error.URLError, TimeoutError) as e:
            tmp.unlink(missing_ok=True)
            return f"{release}/{nom} ({e})"
        tmp.replace(path)
        return None

    with ThreadPoolExecutor(8) as ex:
        for i, err in enumerate(ex.map(dl, todo), 1):
            if err:
                echecs.append(err)
            if i % 50 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}")
    print(f"archive locale : {len(archive.fichiers_locaux())} fichiers dans {archive.ARCHIVE}/")
    if echecs:
        print(f"✘ {len(echecs)} fichier(s) non récupéré(s) :")
        for e in echecs[:20]:
            print(f"  {e}")
        if len(echecs) > 20:
            print(f"  … et {len(echecs) - 20} autre(s)")
        sys.exit(1)
    print("✔ archive locale à jour")


def iter_articles():
    for c in archive.fichiers_locaux():
        yield from archive.lire_fichier(archive.chemin_local(*c))


def verifier_archive():
    if not archive.fichiers_locaux():
        sys.exit("archive/ est vide : lance d'abord « telecharger »")


def export_parquet():
    verifier_archive()
    import pyarrow.parquet as pq
    dest = archive.ARCHIVE / "world_monitor.parquet"
    tmp = dest.with_suffix(".parquet.part")
    n = 0
    with pq.ParquetWriter(tmp, archive.SCHEMA, compression="zstd") as w:
        for c in archive.fichiers_locaux():
            t = pq.read_table(archive.chemin_local(*c)).select(archive.COLS).cast(archive.SCHEMA)
            w.write_table(t)
            n += t.num_rows
    tmp.replace(dest)
    print(f"✔ {n} articles → {dest} ({dest.stat().st_size / 1e6:.0f} Mo)")


def export_sqlite():
    verifier_archive()
    dest = archive.ARCHIVE / "world_monitor.db"
    tmp = dest.with_suffix(".db.part")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    cols = ", ".join(f'"{c}" {"REAL" if c in archive.COLS_NUM else "TEXT"}'
                     for c in archive.COLS)
    con.execute(f"CREATE TABLE articles ({cols})")
    place = ", ".join("?" for _ in archive.COLS)
    n = 0
    lot = []
    for r in iter_articles():
        lot.append([(r.get(c) or None) if c in archive.COLS_NUM else r.get(c, "")
                    for c in archive.COLS])
        if len(lot) >= 20000:
            con.executemany(f"INSERT INTO articles VALUES ({place})", lot)
            n += len(lot)
            lot = []
    con.executemany(f"INSERT INTO articles VALUES ({place})", lot)
    n += len(lot)
    for c in ("time_stamp", "country_article", "sujet_article", "nom_du_media", "region"):
        con.execute(f'CREATE INDEX "idx_{c}" ON articles ("{c}")')
    con.commit()
    con.close()
    tmp.replace(dest)
    print(f"✔ {n} articles → {dest} ({dest.stat().st_size / 1e6:.0f} Mo)")


def export_csv():
    verifier_archive()
    dest = archive.ARCHIVE / "world_monitor.csv"
    n = 0
    with open(dest, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=archive.COLS, delimiter=";", restval="",
                           extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in iter_articles():
            w.writerow(r)
            n += 1
    print(f"✔ {n} articles → {dest} ({dest.stat().st_size / 1e6:.0f} Mo)")


def site(jours):
    env = dict(os.environ, JOURS_SITE=str(jours), WM_REPO=depot())
    subprocess.run([sys.executable, str(HERE / "assembler.py"), "--no-logs"], env=env,
                   check=True)
    print("Pour l'ouvrir : cd docs && python -m http.server 8000")


def retraiter():
    repo = depot()
    telecharger()
    env = dict(os.environ, WM_REPO=repo)
    subprocess.run([sys.executable, str(HERE / "assembler.py"), "--full", "--no-logs"],
                   env=env, check=True)

    limite = (datetime.datetime.now(datetime.timezone.utc).date()
              - datetime.timedelta(days=int(os.environ.get("JOURS_SITE", "7")) + 2))

    def ancien(release, fichier):
        m = re.match(r"(\d{4}-\d{2}-\d{2})\.parquet$", fichier)
        return not m or datetime.date.fromisoformat(m.group(1)) < limite

    liste = archive.A_PUBLIER.read_text().split() if archive.A_PUBLIER.exists() else []
    a_envoyer = [i for i in liste if ancien(*i.split("/", 1))]
    if not a_envoyer:
        print("Aucun fichier ancien modifié : rien à publier.")
        return
    rep = input(f"{len(a_envoyer)} fichier(s) à renvoyer dans les Releases de {repo}. "
                "Continuer ? [o/N] ")
    if rep.strip().lower() not in ("o", "oui", "y", "yes"):
        print("Annulé. La liste reste dans archive/.a_publier.txt.")
        return
    archive.REPO = repo
    archive.publier(inclure_vus=False, garder=ancien)
    # Les jours récents modifiés localement ne doivent jamais être envoyés plus tard
    # (le workflow les a peut-être complétés entre-temps) : on les oublie.
    archive.A_PUBLIER.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("telecharger")
    t.add_argument("--annee", type=int)
    sub.add_parser("parquet")
    sub.add_parser("sqlite")
    sub.add_parser("csv")
    s = sub.add_parser("site")
    s.add_argument("--jours", type=int, default=30)
    sub.add_parser("retraiter")
    args = ap.parse_args()
    if args.cmd == "telecharger":
        telecharger(args.annee)
    elif args.cmd == "parquet":
        export_parquet()
    elif args.cmd == "sqlite":
        export_sqlite()
    elif args.cmd == "csv":
        export_csv()
    elif args.cmd == "site":
        site(args.jours)
    elif args.cmd == "retraiter":
        retraiter()


if __name__ == "__main__":
    main()
