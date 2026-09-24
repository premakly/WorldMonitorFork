#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Assembleur : enchaîne tout le pipeline sur l'archive en fichiers journaliers
(voir archive.py).

  python pipeline/assembler.py
      Mode léger (à chaque cron) :
      • charge les fichiers des JOURS_SITE derniers jours ;
      • traduit les titres pas encore traduits de ces jours ;
      • classe les nouveaux logs et les range dans le fichier de leur jour
        (téléchargé depuis les Releases si besoin, quand WM_REPO est défini) ;
      • régénère le site : docs/data/AAAA-MM-JJ.json + docs/meta.json.

  python pipeline/assembler.py --full
      Mode complet : réapplique les dictionnaires (bans, fusions, fiches, dates,
      scores navals, zones maritimes) à TOUS les fichiers présents dans archive/.
      En CI, seuls les jours récents sont présents ; en local, après avoir tout
      téléchargé, c'est toute l'archive qui est retraitée.

  python pipeline/assembler.py --no-logs
      Régénère le site sans classer de nouveaux logs.

Les fichiers d'archive modifiés sont listés dans archive/.a_publier.txt ;
« python pipeline/archive.py publier » les envoie dans les Releases.
"""
import argparse
import csv
import datetime
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import archive  # noqa: E402

SITE = HERE.parent / "docs"
DONNEES_SITE = SITE / "data"
JOURS_SITE = int(os.environ.get("JOURS_SITE", "7"))


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def num(v):
    try:
        f = float(str(v).replace(",", "."))
        return int(f) if f == int(f) else round(f, 4)
    except (ValueError, TypeError):
        return None


def passe_traduction(rows):
    """Passe LÉGÈRE, à chaque exécution. Traite :
      • les titres pas encore traduits (langue inconnue, ou non anglais sans
        titre_vo) — incrémental, ne concerne plus que les nouveaux une fois
        l'archive rattrapée ;
      • les anciens titres dont la traduction est VISIBLEMENT CASSÉE (boucle
        « mainstremainstre… », longueur anormale) : on les reprend depuis
        l'original, et si la re-traduction rate encore, on garde l'original
        lisible plutôt que le charabia."""
    sys.path.insert(0, str(HERE))
    import traduction
    med_langues = traduction.load_medias_langues()
    print("moteur de traduction :", traduction.moteur_statut())
    a_traduire = sum(1 for r in rows
                     if (r.get("langue") or "") not in ("", "en")
                     and not (r.get("titre_vo") or "").strip())
    n_casses = sum(1 for r in rows
                   if (r.get("titre_vo") or "").strip()
                   and traduction.traduction_cassee(r.get("titre") or "", r.get("titre_vo")))
    print(f"à traduire : {a_traduire} · traductions cassées à reprendre : {n_casses}")
    n_trad, n_repare = 0, 0
    for r in rows:
        lg = (r.get("langue") or "").strip()
        vo = (r.get("titre_vo") or "").strip()
        cur = r.get("titre") or ""
        casse = bool(vo) and traduction.traduction_cassee(cur, vo)
        if not (not lg or (lg != "en" and not vo) or casse):
            continue
        source = vo if vo else cur          # on retraduit depuis l'original si on l'a
        t, newvo, lang = traduction.ensure_english(source, r["nom_du_media"], med_langues)
        r["langue"] = lang
        if casse:
            n_repare += 1
        if newvo:                            # traduction propre
            r["titre"], r["titre_vo"] = t, newvo
            n_trad += 1
        else:                                # intraduisible / encore cassée → original lisible
            r["titre"], r["titre_vo"] = t, ""
    if n_trad or n_repare:
        print(f"traduction : {n_trad} titres (re)traduits, dont {n_repare} anciens cassés repris")
    return (n_trad or n_repare) > 0


def migration_complete(rows):
    """Passe COMPLÈTE (mode --full uniquement) : re-scanne toute l'archive pour
    réappliquer les dictionnaires (bans, fusions, fiches, rescore naval, régions).
    C'est ce qui coûte O(N) : on ne le fait que sur demande."""
    sys.path.insert(0, str(HERE))
    import classify
    alias = classify.load_alias(HERE / "medias_alias.csv")
    bans = classify.load_bans(HERE / "medias_bannis.txt")
    medias = {}
    with open(HERE / "medias.csv", encoding="utf-8") as f:
        for m in csv.DictReader(f, delimiter=";"):
            medias[m["media"].strip().lower()] = m
    naval_pats = classify.load_naval(HERE / "naval.txt")
    zones = classify.load_zones(HERE / "regions_maritimes.txt")
    propres, n_ban, n_dates, n_fusion, n_fiab, n_fiche, n_naval = [], 0, 0, 0, 0, 0, 0
    for r in rows:
        if classify.est_banni(r["nom_du_media"], bans):
            n_ban += 1
            continue
        d2 = classify.norm_date(r["time_stamp"])
        if d2 != r["time_stamp"]:
            n_dates += 1
            r["time_stamp"] = d2
        can = classify.canonical_media(r["nom_du_media"], alias)
        if can != r["nom_du_media"]:
            n_fusion += 1
            r["nom_du_media"] = can
            m = medias.get(can.lower())
            if m:
                r["country_headquarters"] = m["pays_siege"] or r["country_headquarters"]
                r["sujet_media"] = m["theme_media"] or r["sujet_media"]
                r["official_rating"] = m["note"] or r["official_rating"]
        fm = medias.get(r["nom_du_media"].strip().lower())
        if fm:
            if fm.get("pays_siege") and (r.get("country_headquarters") or "") \
               in ("", "Undetermined", "None"):
                r["country_headquarters"] = fm["pays_siege"]
                n_fiche += 1
            if fm.get("theme_media") and not (r.get("sujet_media") or "").strip():
                r["sujet_media"] = fm["theme_media"]
            if fm.get("note") and not (r.get("official_rating") or "").strip():
                r["official_rating"] = fm["note"]
        no = ((fm.get("notation") if fm else "") or "F").strip().upper()
        try:
            fi_new = float((fm.get("indice_fiabilite") if fm else "") or 4.5)
        except ValueError:
            fi_new = 4.5
        fi_new = int(fi_new) if fi_new == int(fi_new) else fi_new
        r["notation"] = no
        nv_new = classify.score_naval(r["titre"], naval_pats)
        r["region_maritime"] = classify.zone_maritime(r["titre"], zones)
        if num(r.get("indice_interet_naval")) != nv_new:
            n_naval += 1
            r["indice_interet_naval"] = nv_new
        if num(r.get("indice_fiabilite")) != fi_new or \
           num(r.get("intérêt marine calcul")) != round(nv_new * 0.4 / 40, 4):
            n_fiab += 1
            r["indice_fiabilite"] = fi_new
            r["fiabilité_calcul"] = round(40 / fi_new, 4)
            r["fiabilité2"] = round(0.6 / fi_new, 4)
            r["intérêt marine calcul"] = round(nv_new * 0.4 / 40, 4)
            r["intérêt_par_fiabilité"] = round(0.6 / fi_new + nv_new * 0.4 / 40, 4)
        propres.append(r)
    print(f"migration complète : {n_ban} doublons retirés, {n_dates} dates "
          f"normalisées, {n_fusion} fusions, {n_fiab} notes/fiabilités, "
          f"{n_fiche} sièges complétés, {n_naval} scores navals recalculés")
    return propres


def jours_du_site(ref=None):
    """Les JOURS_SITE derniers jours (UTC), plus le lendemain pour absorber les
    décalages horaires des flux."""
    ref = ref or datetime.datetime.now(datetime.timezone.utc).date()
    return [ref + datetime.timedelta(days=1 - i) for i in range(JOURS_SITE + 1)]


def rec_site(r):
    return {"m": r["nom_du_media"], "t": r["titre"], "l": r["lien"],
            "d": (r["time_stamp"] or "")[:16],
            "ch": r["country_headquarters"], "ca": r["country_article"],
            "rg": r["region"], "sa": r["sujet_article"],
            "sm": r["sujet_media"], "or": num(r["official_rating"]),
            "fi": num(r["indice_fiabilite"]),
            "nv": num(r["indice_interet_naval"]) or 0,
            "ip": num(r["intérêt_par_fiabilité"]),
            "cf": r["confiance_pays_article"],
            "rm": r.get("region_maritime") or "",
            "lg": r.get("langue") or "en",
            "tv": r.get("titre_vo") or "",
            "no": r.get("notation") or "F"}


def build_site(fichiers, jours, ajout):
    """docs/data/AAAA-MM-JJ.json pour chaque jour du site + docs/meta.json."""
    DONNEES_SITE.mkdir(parents=True, exist_ok=True)
    publies, total = [], 0
    for jour in sorted(jours, reverse=True):
        rows = fichiers.get(archive.emplacement_jour(jour), [])
        if not rows:
            continue
        rows = sorted(rows, key=lambda r: r["time_stamp"] or "", reverse=True)
        nom = f"{jour.isoformat()}.json"
        (DONNEES_SITE / nom).write_text(
            json.dumps([rec_site(r) for r in rows], ensure_ascii=False,
                       separators=(",", ":")), encoding="utf-8")
        publies.append({"jour": jour.isoformat(), "fichier": f"data/{nom}",
                        "count": len(rows)})
        total += len(rows)
    garder = {p["fichier"].split("/")[1] for p in publies}
    for vieux in DONNEES_SITE.glob("*.json"):
        if vieux.name not in garder:
            vieux.unlink()
    (SITE / "meta.json").write_text(json.dumps({
        "generated": datetime.datetime.now(datetime.timezone.utc)
                     .strftime("%d/%m/%Y %H:%M UTC"),
        "count": total, "added": ajout, "jours_site": JOURS_SITE,
        "jours": publies, "repo": archive.REPO}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default=str(HERE / "logs.csv"))
    ap.add_argument("--no-logs", action="store_true",
                    help="ne pas classifier, juste régénérer le site")
    ap.add_argument("--full", action="store_true",
                    help="réappliquer les dictionnaires à tous les fichiers de archive/")
    ap.add_argument("--date-ref", help=argparse.SUPPRESS)   # tests : AAAA-MM-JJ
    args = ap.parse_args()

    ref = datetime.date.fromisoformat(args.date_ref) if args.date_ref else None
    jours = jours_du_site(ref)

    # --- fichiers de travail : les jours du site (+ toute l'archive locale en --full)
    cles = {archive.emplacement_jour(j) for j in jours}
    if args.full:
        cles |= set(archive.fichiers_locaux())
    fichiers = {c: archive.charger(*c) for c in sorted(cles)}
    avant = {c: archive.serialiser(rows) for c, rows in fichiers.items()}
    rows = [r for lot in fichiers.values() for r in lot]
    print(f"fichiers de travail : {len(fichiers)} ({len(rows)} articles) | "
          f"mode : {'COMPLET' if args.full else 'léger'}")

    # --- traduction incrémentale, puis re-scan complet si demandé
    passe_traduction(rows)
    if args.full:
        rows = migration_complete(rows)

    # --- nouveaux logs
    ajout = 0
    if not args.no_logs and Path(args.logs).exists():
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            out = tmp.name
        subprocess.run([sys.executable, str(HERE / "classify.py"),
                        args.logs, "-o", out], check=True)
        nouveaux = read_csv(out)
        os.unlink(out)
        for r in nouveaux:
            c = archive.emplacement(r["time_stamp"])
            if c not in fichiers:           # jour hors fenêtre : on charge son fichier
                fichiers[c] = archive.charger(*c)
                avant[c] = archive.serialiser(fichiers[c])
                rows.extend(fichiers[c])
        rows.extend(nouveaux)

    # --- regroupement par fichier (les dates ont pu changer en --full), sans doublon
    regroupes = defaultdict(list)
    liens = set()
    for r in rows:
        if r["lien"] and r["lien"] in liens:
            continue
        liens.add(r["lien"])
        regroupes[archive.emplacement(r["time_stamp"])].append(r)
    total_avant = sum(len(v) for v in fichiers.values())
    for c in fichiers:
        fichiers[c] = regroupes.pop(c, [])
    fichiers.update(regroupes)   # (ne devrait pas arriver : sécurité)
    ajout = sum(len(v) for v in fichiers.values()) - total_avant
    if not args.no_logs and Path(args.logs).exists():
        print(f"+ {ajout} nouveaux articles classifiés")
        Path(args.logs).replace(str(args.logs) + ".integres")

    # --- écriture des fichiers modifiés
    n_modifs = 0
    for c, lot in fichiers.items():
        if archive.serialiser(lot) != avant.get(c):
            archive.ecrire_fichier(archive.chemin_local(*c), lot)
            archive.marquer_a_publier(*c)
            n_modifs += 1
    print(f"{n_modifs} fichier(s) d'archive modifié(s)")

    total = build_site(fichiers, jours, max(ajout, 0))
    print(f"site régénéré : {total} articles sur {JOURS_SITE} jours → {DONNEES_SITE}/")


if __name__ == "__main__":
    main()
