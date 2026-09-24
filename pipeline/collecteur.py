#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Collecteur World Monitor — lit le catalogue de flux RSS du dépôt open source
worldmonitor (koala73) et en extrait les nouveaux articles.

À chaque exécution :
 1. télécharge la DERNIÈRE version du catalogue de flux (feeds.ts) et du
    classement des sources (source-tiers.json) depuis le dépôt GitHub de WM
    → si WM ajoute des sources ou change son tri, on suit automatiquement ;
 2. interroge chaque flux RSS/Atom (en parallèle) ;
 3. écarte ce qui a déjà été vu (fichier d'état vus.txt) ;
 4. écrit les nouveaux articles dans logs.csv : media;titre;lien;date

Usage :
    python3 collecteur.py                    # collecte complète
    python3 collecteur.py --max-feeds 10     # test rapide sur 10 flux
Aucune dépendance externe (bibliothèque standard uniquement).
"""
import re, csv, sys, json, argparse, hashlib, datetime, email.utils
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = Path(__file__).parent
REPO = "https://raw.githubusercontent.com/koala73/worldmonitor/main"
FEEDS_TS = REPO + "/src/config/feeds.ts"
TIERS = REPO + "/shared/source-tiers.json"
UA = {"User-Agent": "Mozilla/5.0 (WorldMonitorPipeline/1.0)"}


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_feeds(ts_text):
    """Extrait [(nom, url)] du fichier feeds.ts de World Monitor."""
    pat = re.compile(r"name:\s*'([^']+)'\s*,\s*url:\s*\w+\(\s*'([^']+)'", re.S)
    seen, out = set(), []
    for name, url in pat.findall(ts_text):
        if name not in seen:
            seen.add(name)
            out.append((name, url))
    return out


def parse_rss(xml_bytes):
    """Extrait [(titre, lien, date_iso)] d'un flux RSS ou Atom, avec tolérance."""
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    # RSS 2.0
    for it in root.iter("item"):
        t = (it.findtext("title") or "").strip()
        l = (it.findtext("link") or "").strip()
        d = it.findtext("pubDate") or it.findtext(
            "{http://purl.org/dc/elements/1.1/}date") or ""
        items.append((t, l, to_iso(d)))
    # Atom
    if not items:
        for it in root.iter("{http://www.w3.org/2005/Atom}entry"):
            t = (it.findtext("atom:title", namespaces=ns) or "").strip()
            le = it.find("atom:link", ns)
            l = le.get("href", "").strip() if le is not None else ""
            d = it.findtext("atom:published", namespaces=ns) or \
                it.findtext("atom:updated", namespaces=ns) or ""
            items.append((t, l, to_iso(d)))
    return items


def to_iso(d):
    d = (d or "").strip()
    if not d:
        return ""
    try:  # format RFC 2822 (RSS)
        return email.utils.parsedate_to_datetime(d).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    try:  # format ISO (Atom)
        return datetime.datetime.fromisoformat(
            d.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return d[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=str(HERE / "logs.csv"))
    ap.add_argument("--state", default=str(HERE / "vus.txt"),
                    help="fichier des liens déjà collectés")
    ap.add_argument("--max-feeds", type=int, default=0, help="limite (tests)")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    print("Téléchargement du catalogue World Monitor…")
    feeds = parse_feeds(fetch(FEEDS_TS).decode("utf-8", "replace"))
    try:
        tiers = json.loads(fetch(TIERS))
        (HERE / "source-tiers.json").write_text(
            json.dumps(tiers, ensure_ascii=False), encoding="utf-8")
    except Exception:
        tiers = {}
    print(f"{len(feeds)} flux au catalogue"
          + (f" (limité à {args.max_feeds})" if args.max_feeds else ""))
    if args.max_feeds:
        feeds = feeds[: args.max_feeds]

    vus = set()
    state = Path(args.state)
    if state.exists():
        vus = set(state.read_text(encoding="utf-8").split())

    def job(nf):
        name, url = nf
        try:
            return name, parse_rss(fetch(url)), None
        except Exception as e:
            return name, [], str(e)[:80]

    nouveaux, erreurs = [], 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for fut in as_completed(ex.submit(job, nf) for nf in feeds):
            name, items, err = fut.result()
            if err:
                erreurs += 1
                continue
            for t, l, d in items:
                if not t or not l:
                    continue
                h = hashlib.sha1(l.encode()).hexdigest()
                if h in vus:
                    continue
                vus.add(h)
                nouveaux.append((name, t, l, d))

    new_file = not Path(args.out).exists()
    with open(args.out, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        if new_file:
            w.writerow(["media", "titre", "lien", "date"])
        w.writerows(nouveaux)
    state.write_text("\n".join(sorted(vus)), encoding="utf-8")

    print(f"{len(nouveaux)} nouveaux articles | {erreurs} flux en erreur "
          f"(normal : certains flux sont capricieux)")
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()
