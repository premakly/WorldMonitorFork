"""
Stockage de l'archive en fichiers compressés, en local (archive/) et dans les
Releases GitHub du dépôt.

Rangement :
  - articles datés de 2025 ou après  → Release « data-AAAA », un fichier par jour
                                       AAAA-MM-JJ.csv.gz
  - articles datés d'avant 2025      → Release « data-anciens », AAAA.csv.gz
  - articles sans date valide        → Release « data-anciens », sans-date.csv.gz
  - état du collecteur (vus.txt)     → Release « etat », vus.txt.gz

Les gzip sont écrits sans horodatage : même contenu = mêmes octets, ce qui
permet de ne renvoyer que les fichiers réellement modifiés.

Synchronisation avec GitHub (nécessite GitHub CLI « gh », authentifié) : activée
seulement si la variable d'environnement WM_REPO est définie (ex. « user/depot »).
Sans WM_REPO, tout reste local.

Ligne de commande :
  python pipeline/archive.py preparer   récupère vus.txt depuis la Release « etat »
  python pipeline/archive.py publier    envoie les fichiers modifiés + vus.txt
"""
import csv
import gzip
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
ARCHIVE = RACINE / "archive"
A_PUBLIER = ARCHIVE / ".a_publier.txt"
VUS = RACINE / "pipeline" / "vus.txt"
ANNEE_MIN_JOURNALIER = 2025
REPO = os.environ.get("WM_REPO", "").strip()

COLS = ["nom_du_media", "titre", "lien", "time_stamp", "country_headquarters",
        "country_article", "region", "sujet_article", "sujet_media",
        "official_rating", "indice_fiabilite", "notation", "fiabilité_calcul",
        "indice_interet_naval", "region_maritime", "fiabilité2", "intérêt marine calcul",
        "intérêt_par_fiabilité", "confiance_pays_article", "langue", "titre_vo"]

_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


# ---------------------------------------------------------------- rangement

def emplacement(time_stamp):
    """Renvoie (release, nom_du_fichier) pour un article selon sa date."""
    m = _DATE.match(time_stamp or "")
    if not m:
        return "data-anciens", "sans-date.csv.gz"
    annee = int(m.group(1))
    if annee >= ANNEE_MIN_JOURNALIER:
        return f"data-{annee}", f"{m.group(0)}.csv.gz"
    return "data-anciens", f"{annee}.csv.gz"


def emplacement_jour(jour):
    """Emplacement du fichier d'un jour donné (datetime.date)."""
    return emplacement(jour.isoformat())


def chemin_local(release, fichier):
    return ARCHIVE / release / fichier


def fichiers_locaux():
    """Tous les fichiers d'articles présents dans archive/ → [(release, fichier)]."""
    return sorted((p.parent.name, p.name) for p in ARCHIVE.glob("data-*/*.csv.gz"))


# ---------------------------------------------------------------- lecture / écriture

def serialiser(rows):
    rows = sorted(rows, key=lambda r: (r.get("time_stamp") or "", r.get("lien") or ""),
                  reverse=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLS, delimiter=";", restval="",
                       extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0, filename="") as gz:
        gz.write(buf.getvalue().encode("utf-8"))
    return out.getvalue()


def ecrire_fichier(path, rows):
    """Écrit le fichier. Renvoie True si son contenu a changé."""
    data = serialiser(rows)
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def lire_fichier(path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


# ---------------------------------------------------------------- GitHub (gh)

_assets = {}   # cache : release → set des noms de fichiers en ligne (None = pas de release)


def _gh(*args, check=True):
    return subprocess.run(["gh", *args, "-R", REPO], capture_output=True, text=True,
                          check=check)


def assets_en_ligne(release):
    """Fichiers présents dans une Release (None si la Release n'existe pas).
    Lève une erreur en cas de problème réseau : on ne doit jamais prendre
    « injoignable » pour « inexistant », sinon on écraserait un fichier en ligne
    avec une version incomplète."""
    if release not in _assets:
        r = subprocess.run(["gh", "api", f"repos/{REPO}/releases/tags/{release}",
                            "--jq", ".id"], capture_output=True, text=True)
        if r.returncode != 0:
            if "404" in r.stderr or "not found" in r.stderr.lower():
                _assets[release] = None
                return None
            raise RuntimeError(f"gh api (release {release}) : {r.stderr.strip()}")
        rid = r.stdout.strip()
        r = subprocess.run(["gh", "api", "--paginate",
                            f"repos/{REPO}/releases/{rid}/assets?per_page=100",
                            "--jq", ".[].name"], capture_output=True, text=True, check=True)
        _assets[release] = set(r.stdout.split())
    return _assets[release]


def charger(release, fichier):
    """Articles d'un fichier : local s'il existe, sinon téléchargé depuis la Release
    (si WM_REPO est défini), sinon liste vide (fichier qui n'existe pas encore)."""
    path = chemin_local(release, fichier)
    if not path.exists() and REPO and fichier in (assets_en_ligne(release) or set()):
        path.parent.mkdir(parents=True, exist_ok=True)
        _gh("release", "download", release, "-p", fichier, "-D", str(path.parent),
            "--clobber")
    return lire_fichier(path) if path.exists() else []


def marquer_a_publier(release, fichier):
    ARCHIVE.mkdir(exist_ok=True)
    deja = set(A_PUBLIER.read_text().split()) if A_PUBLIER.exists() else set()
    deja.add(f"{release}/{fichier}")
    A_PUBLIER.write_text("\n".join(sorted(deja)) + "\n")


def _creer_release_si_besoin(release):
    if assets_en_ligne(release) is None:
        _gh("release", "create", release, "--title", release,
            "--notes", "Archive World Monitor, fichiers générés automatiquement.")
        _assets[release] = set()


def preparer():
    """Récupère vus.txt depuis la Release « etat »."""
    if not REPO:
        sys.exit("WM_REPO n'est pas défini (ex. export WM_REPO=user/depot)")
    if "vus.txt.gz" not in (assets_en_ligne("etat") or set()):
        print("⚠ aucun vus.txt en ligne : le collecteur repartira de zéro "
              "(sans doublons, les articles déjà archivés sont dédupliqués par lien)")
        return
    tmp = ARCHIVE / "etat"
    tmp.mkdir(parents=True, exist_ok=True)
    _gh("release", "download", "etat", "-p", "vus.txt.gz", "-D", str(tmp), "--clobber")
    with gzip.open(tmp / "vus.txt.gz", "rb") as src, open(VUS, "wb") as dst:
        shutil.copyfileobj(src, dst)
    print(f"vus.txt récupéré ({VUS.stat().st_size / 1e6:.1f} Mo)")


def publier():
    """Envoie dans les Releases les fichiers modifiés depuis la dernière publication,
    puis l'état du collecteur (vus.txt)."""
    if not REPO:
        sys.exit("WM_REPO n'est pas défini (ex. export WM_REPO=user/depot)")
    liste = A_PUBLIER.read_text().split() if A_PUBLIER.exists() else []
    for item in liste:
        release, fichier = item.split("/", 1)
        _creer_release_si_besoin(release)
        _gh("release", "upload", release, str(chemin_local(release, fichier)), "--clobber")
    print(f"{len(liste)} fichier(s) d'archive publié(s)")
    if VUS.exists():
        dest = ARCHIVE / "etat" / "vus.txt.gz"
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(VUS, "rb") as src, open(dest, "wb") as f, \
                gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="") as gz:
            shutil.copyfileobj(src, gz)
        _creer_release_si_besoin("etat")
        _gh("release", "upload", "etat", str(dest), "--clobber")
        print("vus.txt publié")
    if A_PUBLIER.exists():
        A_PUBLIER.unlink()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "preparer":
        preparer()
    elif cmd == "publier":
        publier()
    else:
        sys.exit(__doc__)
