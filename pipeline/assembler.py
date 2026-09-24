#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Assembleur — enchaîne tout le pipeline.

DEUX MODES pour éviter que chaque passage soit de plus en plus long / lourd :

  python3 assembler.py            (mode LÉGER, à chaque cron)
      • traduit seulement les titres pas encore traduits (incrémental) ;
      • classe les nouveaux logs et les ajoute à l'archive ;
      • régénère UNIQUEMENT le fichier du site data.js (+ meta.json).
      → l'archive déjà traitée n'est PAS re-scannée, les gros exports ne sont
        PAS régénérés : le temps par passage reste proportionnel au nouveau
        contenu, et le dépôt git ne gonfle presque plus.

  python3 assembler.py --full     (mode COMPLET, à la demande / hebdo)
      • re-scanne TOUTE l'archive (bans, dates, fusions, fiches, rescore naval
        déplafonné, régions maritimes) — utile quand tu changes tes dictionnaires ;
      • régénère aussi les gros exports : world_monitor.csv / .db / .xlsx.

  python3 assembler.py --no-logs  régénère le site depuis l'archive sans classer.
"""
import csv, json, sys, os, sqlite3, argparse, subprocess, tempfile
from pathlib import Path

HERE = Path(__file__).parent
MASTER = HERE / "consolide_master.csv"
SITE = HERE.parent / "docs"   # dossier servi par GitHub Pages

COLS = ["nom_du_media", "titre", "lien", "time_stamp", "country_headquarters",
        "country_article", "region", "sujet_article", "sujet_media",
        "official_rating", "indice_fiabilite", "notation", "fiabilité_calcul",
        "indice_interet_naval", "region_maritime", "fiabilité2", "intérêt marine calcul",
        "intérêt_par_fiabilité", "confiance_pays_article", "langue", "titre_vo"]


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def write_master(rows):
    with open(MASTER, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, delimiter=";",
                           restval="", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def num(v):
    try:
        f = float(str(v).replace(",", "."))
        return int(f) if f == int(f) else round(f, 4)
    except (ValueError, TypeError):
        return None


def build_site(rows, added=0, heavy=False):
    """Génère toujours data.js + meta.json (légers, nécessaires au site).
    Ne régénère les gros exports (CSV / SQLite / XLSX) que si heavy=True."""
    SITE.mkdir(exist_ok=True)
    # --- meta.json (horodatage affiché par le bouton Actualiser) ---
    import datetime
    (SITE / "meta.json").write_text(json.dumps({
        "generated": datetime.datetime.now(datetime.timezone.utc)
                     .strftime("%d/%m/%Y %H:%M UTC"),
        "count": len(rows), "added": added}, ensure_ascii=False),
        encoding="utf-8")
    # --- data.js (données du site) ---
    recs = []
    for r in rows:
        recs.append({"m": r["nom_du_media"], "t": r["titre"], "l": r["lien"],
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
                     "no": r.get("notation") or "F"})
    js = "window.DATA_WM=" + json.dumps(
        recs, ensure_ascii=False, separators=(",", ":")).replace(
        "</script", "<\\/script") + ";"
    (SITE / "data.js").write_text(js, encoding="utf-8")

    if not heavy:
        return   # mode léger : on s'arrête là, pas de gros exports recommités

    # --- CSV téléchargeable ---
    with open(SITE / "world_monitor.csv", "w", encoding="utf-8-sig",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, delimiter=";")
        w.writeheader()
        w.writerows(rows)

    # --- SQLite ---
    db = SITE / "world_monitor.db"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE articles (%s)" %
                ", ".join(f'"{c}"' for c in COLS))
    con.executemany("INSERT INTO articles VALUES (%s)" %
                    ",".join("?" * len(COLS)),
                    [[r.get(c, "") for c in COLS] for r in rows])
    con.commit()
    con.close()

    # --- XLSX (si openpyxl est disponible) ---
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Articles"
        ws.append(COLS)
        for r in rows:
            ws.append([num(r.get(c)) if num(r.get(c)) is not None and
                       c in ("official_rating", "indice_fiabilite",
                             "fiabilité_calcul", "indice_interet_naval",
                             "fiabilité2", "intérêt marine calcul",
                             "intérêt_par_fiabilité") else r.get(c, "") for c in COLS])
        wb.save(SITE / "world_monitor.xlsx")
    except ImportError:
        print("(openpyxl absent : export XLSX sauté)")


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default=str(HERE / "logs.csv"))
    ap.add_argument("--no-logs", action="store_true",
                    help="ne pas classifier, juste régénérer le site")
    ap.add_argument("--full", action="store_true",
                    help="re-scanner toute l'archive + régénérer les gros exports "
                         "(CSV/DB/XLSX). À lancer à la demande / une fois par semaine.")
    args = ap.parse_args()

    rows = read_csv(MASTER) if MASTER.exists() else []
    print(f"historique : {len(rows)} articles | mode : {'COMPLET' if args.full else 'léger'}")

    # --- toujours : traduction incrémentale (ne touche que les non-traduits) ---
    changed = passe_traduction(rows)

    # --- seulement en --full : re-scan complet de l'archive figée ---
    if args.full:
        rows = migration_complete(rows)
        changed = True

    if changed:
        write_master(rows)

    liens = {r["lien"] for r in rows}

    # --- nouveaux logs (à chaque passage) ---
    ajout = 0
    if not args.no_logs and Path(args.logs).exists():
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            out = tmp.name
        subprocess.run([sys.executable, str(HERE / "classify.py"),
                        args.logs, "-o", out], check=True)
        for r in read_csv(out):
            if r["lien"] and r["lien"] not in liens:
                liens.add(r["lien"])
                rows.append(r)
                ajout += 1
        os.unlink(out)
        print(f"+ {ajout} nouveaux articles classifiés")
        write_master(rows)
        Path(args.logs).rename(str(args.logs) + ".integres")

    rows.sort(key=lambda r: r["time_stamp"] or "", reverse=True)
    build_site(rows, ajout, heavy=args.full)
    print(f"site régénéré ({len(rows)} articles, exports lourds : "
          f"{'oui' if args.full else 'non'}) → {SITE}/")


if __name__ == "__main__":
    main()
