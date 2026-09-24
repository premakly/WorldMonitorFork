"""
Migration unique : découpe pipeline/consolide_master.csv en fichiers journaliers
dans archive/ (voir archive.py) et compresse vus.txt dans archive/etat/.

    python pipeline/migrer_archive.py

Ne modifie aucun fichier existant du dépôt. Peut être relancé sans risque :
archive/ est entièrement régénéré.
"""
import csv
import gzip
import shutil
import sys
from collections import defaultdict
from pathlib import Path

from archive import ARCHIVE, emplacement, chemin_local, ecrire_fichier, lire_fichier

HERE = Path(__file__).resolve().parent
MASTER = HERE / "consolide_master.csv"
VUS = HERE / "vus.txt"


def main():
    if not MASTER.exists():
        sys.exit(f"Introuvable : {MASTER}")

    if ARCHIVE.exists():
        shutil.rmtree(ARCHIVE)

    print(f"Lecture de {MASTER.name}…")
    groupes = defaultdict(list)
    vus_liens = set()
    total = doublons = 0
    with open(MASTER, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            total += 1
            lien = row.get("lien", "")
            if lien in vus_liens:
                doublons += 1
                continue
            vus_liens.add(lien)
            groupes[emplacement(row.get("time_stamp", ""))].append(row)

    print(f"  {total} lignes, {doublons} doublons de lien ignorés")

    print("Écriture des fichiers journaliers…")
    par_release = defaultdict(lambda: [0, 0, 0])   # fichiers, articles, octets
    for (release, fichier), rows in sorted(groupes.items()):
        path = chemin_local(release, fichier)
        ecrire_fichier(path, rows)
        s = par_release[release]
        s[0] += 1
        s[1] += len(rows)
        s[2] += path.stat().st_size

    # Vérification : relecture complète
    relus = sum(len(lire_fichier(p)) for p in ARCHIVE.glob("data-*/*.csv.gz"))
    attendu = total - doublons
    if relus != attendu:
        sys.exit(f"ERREUR : {relus} articles relus pour {attendu} attendus")

    if VUS.exists():
        dest = ARCHIVE / "etat" / "vus.txt.gz"
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(VUS, "rb") as src, open(dest, "wb") as f, \
                gzip.GzipFile(fileobj=f, mode="wb", mtime=0, filename="") as gz:
            shutil.copyfileobj(src, gz)
        par_release["etat"] = [1, 0, dest.stat().st_size]
    else:
        print(f"  ⚠ {VUS.name} introuvable, état du collecteur non migré")

    print(f"\n{'Release':<14}{'fichiers':>9}{'articles':>10}{'taille':>10}")
    for release, (n, a, o) in sorted(par_release.items()):
        print(f"{release:<14}{n:>9}{a:>10}{o / 1e6:>8.1f} Mo")
    print(f"\n✔ {relus} articles vérifiés. Résultat dans {ARCHIVE}/")


if __name__ == "__main__":
    main()
