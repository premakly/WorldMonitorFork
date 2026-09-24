#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Évalue les dictionnaires/règles contre le fichier de référence (les 5 499
articles classés à la main). À relancer après chaque modification de
themes.txt, pays.txt ou regles.txt :

    python3 evaluer.py world_monitor_consolide_1.xlsx
"""
import sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import classify

try:
    import openpyxl
except ImportError:
    sys.exit("Installe openpyxl :  pip install openpyxl")

if len(sys.argv) < 2:
    sys.exit(__doc__)

themes = classify.compile_dict(classify.load_dict(Path(__file__).parent / "themes.txt"))
pays_raw = classify.load_dict(Path(__file__).parent / "pays.txt")
pays = classify.compile_dict(pays_raw)
rules = classify.load_rules(Path(__file__).parent / "regles.txt", pays_raw)

wb = openpyxl.load_workbook(sys.argv[1], read_only=True)
rows = list(wb.worksheets[0].iter_rows(values_only=True))
hdr = list(rows[0]); data = rows[1:]
i = {h: k for k, h in enumerate(hdr)}

med = {}
for r in data:
    m = str(r[i["nom_du_media"]]).strip().lower()
    if m not in med:
        sm = str(r[i["sujet_media"]])
        med[m] = (r[i["country_headquarters"]] or "",
                  "Politique" if ".gov" in m else sm)

okT = totT = okP = totP = 0
per = collections.defaultdict(lambda: [0, 0])
missT = collections.Counter()
for r in data:
    titre = r[i["titre"]]
    predT = classify.classify_theme(titre, themes, rules)
    if predT == "Non déterminé":
        predT = classify.THEME_FALLBACK.get(
            med.get(str(r[i["nom_du_media"]]).strip().lower(), ("", ""))[1],
            "Non déterminé")
    predP, _ = classify.classify_pays(titre, pays,
                                      med.get(str(r[i["nom_du_media"]]).strip().lower()))
    refT = r[i["sujet_article"]]
    if refT and refT not in ("Non déterminé", "Inclassable/Non pertinent"):
        totT += 1; okT += predT == refT
        per[refT][0] += predT == refT; per[refT][1] += 1
        if predT != refT:
            missT[(refT, predT)] += 1
    refP = r[i["country_article"]]
    if refP and refP not in ("Undetermined", "None", "Inclassable/Non pertinent"):
        if str(refP) == "Hong-Kong": refP = "Hong Kong"
        totP += 1; okP += predP == refP

print(f"\nTHÈMES : {okT/totT:.1%} d'accord avec la référence ({totT} articles)")
for th, (o, t) in sorted(per.items(), key=lambda x: -x[1][1]):
    if t >= 20:
        print(f"  {th:<40} {o/t:>4.0%}  ({t})")
print(f"\nPAYS : {okP/totP:.1%} d'accord ({totP} articles)")
print("\nConfusions les plus fréquentes (référence → prédiction) :")
for (a, b), n in missT.most_common(8):
    print(f"  {a} → {b} : {n}")
