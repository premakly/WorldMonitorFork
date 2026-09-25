"""
Stockage de l'archive : un fichier Parquet par jour.

En local (archive/) :
    archive/2026/07/2026-07-15.parquet      un fichier par jour, rangé par année/mois
    archive/sans-date.parquet               articles sans date exploitable

Sur GitHub (les Releases ne peuvent pas contenir de dossiers) :
    Release « data-2026 »      → 2026-07-15.parquet, 2026-07-16.parquet, …
    Release « data-sans-date » → sans-date.parquet
    Release « etat »           → vus.txt.gz (état du collecteur)

Colonnes : texte, sauf time_stamp (timestamp, UTC, à la minute) et les indices
numériques (float). Dans le pipeline, les lignes restent des dict de chaînes ;
la conversion se fait à la lecture et à l'écriture.

Synchronisation avec GitHub (GitHub CLI « gh » authentifié) : activée seulement
si WM_REPO est défini (ex. « user/depot »). Sans WM_REPO, tout reste local.

Ligne de commande :
  python pipeline/archive.py preparer   récupère vus.txt depuis la Release « etat »
  python pipeline/archive.py publier    envoie les fichiers modifiés + vus.txt
"""
import datetime
import gzip
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

RACINE = Path(__file__).resolve().parent.parent
ARCHIVE = RACINE / "archive"
A_PUBLIER = ARCHIVE / ".a_publier.txt"
VUS = RACINE / "pipeline" / "vus.txt"
REPO = os.environ.get("WM_REPO", "").strip()

COLS = ["nom_du_media", "titre", "lien", "time_stamp", "country_headquarters",
        "country_article", "region", "sujet_article", "sujet_media",
        "official_rating", "indice_fiabilite", "notation", "fiabilité_calcul",
        "indice_interet_naval", "region_maritime", "fiabilité2", "intérêt marine calcul",
        "intérêt_par_fiabilité", "confiance_pays_article", "langue", "titre_vo"]
COLS_NUM = {"official_rating", "indice_fiabilite", "fiabilité_calcul",
            "indice_interet_naval", "fiabilité2", "intérêt marine calcul",
            "intérêt_par_fiabilité"}
SCHEMA = pa.schema([
    (c, pa.timestamp("s") if c == "time_stamp"
        else pa.float64() if c in COLS_NUM else pa.string())
    for c in COLS])
FORMAT_TS = "%Y-%m-%d %H:%M"
SANS_DATE = ("data-sans-date", "sans-date.parquet")

_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


# ---------------------------------------------------------------- rangement

def emplacement(time_stamp):
    """(release, nom_du_fichier) d'un article selon sa date."""
    m = _DATE.match(time_stamp or "")
    if not m:
        return SANS_DATE
    return f"data-{m.group(1)}", f"{m.group(0)}.parquet"


def emplacement_jour(jour):
    """Emplacement du fichier d'un jour donné (datetime.date)."""
    return emplacement(jour.isoformat())


def chemin_local(release, fichier):
    if (release, fichier) == SANS_DATE:
        return ARCHIVE / fichier
    return ARCHIVE / fichier[:4] / fichier[5:7] / fichier


def fichiers_locaux():
    """Tous les fichiers d'articles présents dans archive/ → [(release, fichier)]."""
    out = [(f"data-{p.name[:4]}", p.name)
           for p in ARCHIVE.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]/*.parquet")]
    if chemin_local(*SANS_DATE).exists():
        out.append(SANS_DATE)
    return sorted(out)


# ---------------------------------------------------------------- conversions

def _vers_ts(v):
    v = (v or "").strip()
    for fmt in (FORMAT_TS, "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(v[:16] if fmt == FORMAT_TS else v[:10], fmt)
        except ValueError:
            pass
    return None


def _vers_num(v):
    v = str(v if v is not None else "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _vers_texte(v):
    if v is None:
        return ""
    if isinstance(v, datetime.datetime):
        return v.strftime(FORMAT_TS)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    return str(v)


def serialiser(rows):
    """Contenu Parquet (bytes) d'une liste d'articles, du plus récent au plus ancien.
    Refuse une valeur qui serait perdue à la conversion."""
    rows = sorted(rows, key=lambda r: (r.get("time_stamp") or "", r.get("lien") or ""),
                  reverse=True)
    cols = {}
    for c in COLS:
        brut = [r.get(c) for r in rows]
        if c == "time_stamp":
            vals = [_vers_ts(v) for v in brut]
        elif c in COLS_NUM:
            vals = [_vers_num(v) for v in brut]
        else:
            vals = [None if v is None else str(v) for v in brut]
        if c == "time_stamp" or c in COLS_NUM:
            for b, v in zip(brut, vals):
                if v is None and str(b or "").strip() and _DATE.match(str(b)):
                    raise ValueError(f"{c} illisible : {b!r}")
        cols[c] = vals
    table = pa.Table.from_pydict(cols, schema=SCHEMA)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd", use_dictionary=True)
    return buf.getvalue()


def ecrire_fichier(path, rows):
    """Écrit le fichier. Renvoie True si son contenu a changé."""
    data = serialiser(rows)
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.part")
    tmp.write_bytes(data)
    tmp.replace(path)
    return True


def lire_fichier(path):
    """Articles d'un fichier Parquet, sous forme de dict de chaînes."""
    table = pq.read_table(path)
    colonnes = {c: table.column(c).to_pylist() for c in table.column_names}
    n = table.num_rows
    return [{c: _vers_texte(colonnes[c][i]) if c in colonnes else "" for c in COLS}
            for i in range(n)]


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


def creer_release_si_besoin(release):
    if assets_en_ligne(release) is None:
        _gh("release", "create", release, "--title", release,
            "--notes", "Archive World Monitor : un fichier Parquet par jour, "
                       "généré automatiquement.")
        _assets[release] = set()


def envoyer(release, fichier):
    creer_release_si_besoin(release)
    _gh("release", "upload", release, str(chemin_local(release, fichier)), "--clobber")
    _assets[release].add(fichier)


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


def publier(inclure_vus=True, garder=None):
    """Envoie dans les Releases les fichiers modifiés depuis la dernière publication,
    puis l'état du collecteur (vus.txt).
    garder : fonction (release, fichier) → bool pour n'envoyer qu'une partie ;
    les fichiers écartés restent dans la liste pour une publication ultérieure."""
    if not REPO:
        sys.exit("WM_REPO n'est pas défini (ex. export WM_REPO=user/depot)")
    tout = A_PUBLIER.read_text().split() if A_PUBLIER.exists() else []
    liste = [i for i in tout if garder is None or garder(*i.split("/", 1))]
    reste = [i for i in tout if i not in liste]
    for item in liste:
        envoyer(*item.split("/", 1))
    print(f"{len(liste)} fichier(s) d'archive publié(s)")
    if inclure_vus and VUS.exists():
        dest = ARCHIVE / "etat" / "vus.txt.gz"
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(VUS, "rb") as src, open(dest, "wb") as f, \
                gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="") as gz:
            shutil.copyfileobj(src, gz)
        creer_release_si_besoin("etat")
        _gh("release", "upload", "etat", str(dest), "--clobber")
        print("vus.txt publié")
    if reste:
        A_PUBLIER.write_text("\n".join(reste) + "\n")
    elif A_PUBLIER.exists():
        A_PUBLIER.unlink()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "preparer":
        preparer()
    elif cmd == "publier":
        publier()
    else:
        sys.exit(__doc__)