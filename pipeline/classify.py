#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Classificateur World Monitor — thèmes, pays, région, enrichissement média.
Aucune dépendance externe (bibliothèque standard Python uniquement).

Usage :
    python3 classify.py logs.csv -o consolide.csv
logs.csv attendu (séparateur ;) : media;titre;lien;date
Les dictionnaires themes.txt / pays.txt / medias.csv / regions.json
doivent être dans le même dossier.
"""
import re, csv, json, sys, argparse, unicodedata
from pathlib import Path

HERE = Path(__file__).parent

# ---------------------------------------------------------------- dictionnaires
def load_dict(path):
    """Lit un fichier 'Classe: mot1, *motfort, …' → liste (classe, [(mot, poids)])."""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        cls, kws = line.split(":", 1)
        entries = []
        for kw in kws.split(","):
            kw = kw.strip().lower()
            if not kw:
                continue
            weight = 2 if kw.startswith("*") else 1
            entries.append((kw.lstrip("*"), weight))
        out.append((cls.strip(), entries))
    return out

def compile_dict(d):
    """Pré-compile chaque mot-clé en regex avec frontières de mots."""
    comp = []
    for cls, entries in d:
        pats = [(re.compile(r"(?<![\w’'])" + re.escape(kw) + r"(?![\w])"), w)
                for kw, w in entries]
        comp.append((cls, pats))
    return comp

def _kw_regex(kw):
    return r"(?<![\w’'])" + re.escape(kw) + r"(?![\w])"

def load_rules(path, pays_dict):
    """Règles de contexte : 'Thème: mot1|variante + mot2 + !exclu'.
    @pays = n'importe quel pays (mots forts du dictionnaire pays).
    '@pays + @pays' exige DEUX pays différents dans le titre.
    Dans une alternative mixte ('@pays|meeting'), @pays compte comme
    'un pays supplémentaire distinct'.
    Toutes les parties reliées par + doivent être présentes ; ! exclut.
    Règles prioritaires sur le score par mots-clés, première gagnante."""
    if not Path(path).exists():
        return None
    # une regex par pays (mots forts), pour compter les pays distincts
    country_pats = []
    for cls, entries in pays_dict:
        strong = [kw for kw, w in entries if w == 2]
        if strong:
            country_pats.append(re.compile("|".join(_kw_regex(k) for k in strong)))
    rules = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        cls, expr = line.split(":", 1)
        pos, neg, needed_pays = [], [], 0
        for term in expr.split("+"):
            term = term.strip().lower()
            if not term:
                continue
            negate = term.startswith("!")
            term = term.lstrip("!").strip()
            alts = [a.strip() for a in term.split("|") if a.strip()]
            has_pays = "@pays" in alts
            words = [a for a in alts if a != "@pays"]
            pat = re.compile("|".join(_kw_regex(a) for a in words)) if words else None
            if negate:
                if pat:
                    neg.append(pat)
            elif has_pays and not words:
                needed_pays += 1                  # '@pays' seul : +1 pays requis
            else:
                pos.append((has_pays, pat))       # mots, ou mixte '@pays|mots'
        rules.append((cls.strip(), pos, neg, needed_pays))
    return {"rules": rules, "country_pats": country_pats}

def apply_rules(title, ruleset):
    t = norm(title)
    distinct = sum(1 for p in ruleset["country_pats"] if p.search(t))
    for cls, pos, neg, needed in ruleset["rules"]:
        if distinct < needed:
            continue
        if any(n.search(t) for n in neg):
            continue
        ok = True
        for has_pays, pat in pos:
            hit = bool(pat and pat.search(t))
            if has_pays:                          # mixte : mots OU un pays de plus
                hit = hit or distinct >= needed + 1
            if not hit:
                ok = False
                break
        if ok:
            return cls
    return None

# ---------------------------------------------------------------- classification
def norm(s):
    return unicodedata.normalize("NFKD", str(s)).lower()

def score(title, comp):
    """[(classe, score)] trié par score, puis par position du 1er mot trouvé
    dans le titre (le plus tôt gagne), puis par ordre du fichier."""
    t = norm(title)
    res = []
    for idx, (cls, pats) in enumerate(comp):
        s, first = 0, 10**9
        for p, w in pats:
            m = p.search(t)
            if m:
                s += w
                first = min(first, m.start())
        if s:
            res.append((s, -first, -idx, cls))
    res.sort(reverse=True)
    return [(cls, s) for s, _, _, cls in res]

def classify_theme(title, comp, rules=None):
    if rules:
        hit = apply_rules(title, rules)
        if hit:
            return hit
    r = score(title, comp)
    return r[0][0] if r else "Non déterminé"

def classify_pays(title, comp, media_info=None):
    """media_info = (pays_siege, theme_media) : repli quand le titre est muet,
    pour les médias locaux / politiques / gouvernementaux (.gov)."""
    r = score(title, comp)
    if r and r[0][1] >= 2:
        conf = "high" if r[0][1] >= 3 else "medium"
        return r[0][0], conf
    if media_info:
        ch, sm = media_info
        if sm in ("Local/Régional", "Politique"):
            if ch:
                return ch, "media-default"
    # un mot faible seul ne décide jamais (trop de faux positifs)
    return "Undetermined", "none"

def load_naval(path):
    """Barème naval : lignes 'poids: mot1, mot2, …' → [(regex, poids)]."""
    if not Path(path).exists():
        return []
    pats = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        w, kws = line.split(":", 1)
        try:
            w = int(w.strip())
        except ValueError:
            continue
        for kw in kws.split(","):
            kw = kw.strip().lower()
            if kw:
                pats.append((re.compile(_kw_regex(kw)), w))
    return pats

def load_zones(path):
    """regions_maritimes.txt → [(zone, [regex])] dans l'ordre du fichier."""
    zones = []
    if not Path(path).exists():
        return zones
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        zone, kws = line.split(":", 1)
        pats = [re.compile(_kw_regex(kw.strip().lower()))
                for kw in kws.split(",") if kw.strip()]
        if pats:
            zones.append((zone.strip(), pats))
    return zones

def zone_maritime(title, zones):
    """Zone maritime chaude du titre ('' si aucune). Plus de mots-clés gagne,
    l'ordre du fichier départage."""
    t = norm(title)
    best, bs = "", 0
    for zone, pats in zones:
        s = sum(1 for p in pats if p.search(t))
        if s > bs:
            best, bs = zone, s
    return best

def score_naval(title, naval_pats, cap=None):
    """Somme des poids des mots trouvés. Sans plafond par défaut
    (passer cap=40 pour retrouver l'ancien comportement)."""
    t = norm(title)
    s = sum(w for p, w in naval_pats if p.search(t))
    return s if cap is None else min(cap, s)

# ------------------------------------------------------- langue / dates / alias
# scripts non latins : grec, cyrillique, arabe, hébreu, CJK, coréen, thaï, devanagari…
_NON_LATIN = re.compile(r"[Ͱ-Ͽἀ-῿Ѐ-ӿ԰-֏֐-׿؀-ۿ"
                        r"ऀ-෿฀-๿ሀ-፿぀-ヿ"
                        r"一-鿿가-힯]")
_VIET = re.compile(r"[ăđơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.I)
# latin étendu (ő ű ł ż ś ć ș ț ř ě š č ğ ı …) : jamais utilisé en anglais
_LATIN_EXT = re.compile(r"[Ā-ɏ]")
_STOPS = {
    "en": {"the", "of", "to", "and", "in", "for", "on", "with", "as", "at", "by",
           "from", "is", "are", "was", "will", "after", "over", "new", "says",
           "his", "her", "its", "their", "has", "have", "be", "not", "no", "how",
           "what", "who", "more", "about", "into", "amid", "up", "out", "than"},
    "fr": {"le", "la", "les", "des", "une", "du", "au", "aux", "avec", "pour",
           "dans", "est", "sont", "sur", "pas", "par", "qui", "que", "plus", "ce"},
    "es": {"el", "los", "las", "una", "del", "por", "para", "con", "más", "este",
           "esta", "como", "pero", "sus", "según", "tras", "entre"},
    "de": {"der", "die", "das", "und", "ist", "nicht", "mit", "für", "von", "dem",
           "den", "ein", "eine", "auf", "wird", "nach", "über", "beim", "gegen",
           "sich", "treffen", "wurde", "noch", "auch", "oder"},
    "it": {"il", "lo", "gli", "della", "delle", "di", "che", "con", "per", "una",
           "sono", "più", "anche", "dopo", "nel", "alla"},
    "pt": {"os", "uma", "das", "dos", "não", "com", "por", "para", "mais", "como",
           "foi", "são", "após", "sobre"},
    "nl": {"het", "een", "van", "voor", "met", "naar", "wordt", "niet", "aan",
           "bij", "over", "deze"},
    "id": {"yang", "dan", "di", "untuk", "dari", "dengan", "akan", "pada", "ini",
           "itu", "tidak"},
    "tr": {"ve", "bir", "için", "ile", "bu", "da", "de", "olarak", "sonra",
           "yeni", "daha"},
    "hu": {"és", "hogy", "nem", "már", "csak", "még", "lesz", "szerint",
           "után", "ellen", "miatt", "lehet", "volt", "kell", "vagy"},
    "pl": {"nie", "się", "jest", "oraz", "przez", "które", "która", "tylko",
           "jak", "czy", "dla", "został", "została", "będzie", "roku"},
    "ro": {"și", "nu", "este", "pentru", "din", "cu", "mai", "care", "după",
           "fost", "sunt", "într-un", "într-o", "despre", "către"},
    "cs": {"není", "jsou", "jako", "pro", "podle", "které", "byl", "bude",
           "ale", "aby", "roce"},
    "sv": {"och", "att", "är", "för", "med", "inte", "som", "har", "ett",
           "den", "efter", "ska", "kan", "vill", "öka", "nya", "mot"},
    "da": {"og", "er", "til", "det", "ikke", "som", "har", "ved", "efter",
           "kan", "skal"},
    "fi": {"ja", "ei", "että", "joka", "mutta", "myös", "kun", "vuoden"},
}

def est_anglais(titre):
    """True si le titre semble anglais. Heuristique : scripts non latins,
    diacritiques vietnamiens, puis duel de mots-outils anglais vs autres."""
    t = str(titre)
    if _NON_LATIN.search(t):
        return False
    if len(_VIET.findall(t)) >= 2:
        return False
    toks = re.findall(r"[a-zà-ÿā-ɏ']+", t.lower())
    en = sum(1 for w in toks if w in _STOPS["en"])
    autres = max((sum(1 for w in toks if w in s)
                  for l, s in _STOPS.items() if l != "en"), default=0)
    if autres >= 2 and autres > en:
        return False
    # caractères latins étendus (ő ł ș ě ğ…) : inexistants en anglais
    ext = len(_LATIN_EXT.findall(t))
    if ext >= 2 or (ext == 1 and en == 0):
        return False
    # beaucoup d'accents et aucun mot-outil anglais → probablement pas anglais
    if en == 0 and len(re.findall(r"[à-ÿ]", t.lower())) >= 3:
        return False
    return True

def load_bans(path):
    """medias_bannis.txt → (exacts, préfixes). Médias écartés d'office."""
    exact, globs = set(), []
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.endswith("*"):
                globs.append(line[:-1].rstrip())
            else:
                exact.add(line)
    return exact, globs

def est_banni(name, bans):
    exact, globs = bans
    n = str(name).strip()
    return n in exact or any(n.startswith(p + " ") or n == p for p in globs)

_DATE_FORMATS = ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                 "%Y/%m/%d %H:%M", "%d/%m/%Y %H:%M", "%d/%m/%Y",
                 "%d-%m-%Y %H:%M", "%d %b %Y %H:%M", "%d %b %Y",
                 "%b %d, %Y %H:%M", "%b %d, %Y", "%B %d, %Y"]

def norm_date(d):
    """Normalise toute date en 'YYYY-MM-DD HH:MM' ('' si indéchiffrable)."""
    import datetime, email.utils
    d = str(d or "").strip()
    if not d:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", d):
        return d
    try:  # RFC 2822 : 'Wed, 08 Jul 2026 10:30:00 GMT'
        return email.utils.parsedate_to_datetime(d).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    try:  # ISO : '2026-07-08T10:30:00Z'
        return datetime.datetime.fromisoformat(
            d.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(d, fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return ""

def load_alias(path):
    """medias_alias.csv → (exacts{alias:canon}, préfixes[(préfixe,canon)])."""
    exact, globs = {}, []
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ";" not in line \
               or line.startswith("alias;"):
                continue
            a, c = [x.strip() for x in line.split(";", 1)]
            if a.endswith("*"):
                globs.append((a[:-1].rstrip(), c))
            else:
                exact[a] = c
    globs.sort(key=lambda x: -len(x[0]))
    return exact, globs

def canonical_media(name, alias):
    exact, globs = alias
    n = str(name).strip()
    if n in exact:
        return exact[n]
    for pref, canon in globs:
        if n.startswith(pref + " ") or n == pref:
            return canon
    return n

# repli : si le titre ne permet pas de classer, le thème du média décide
THEME_FALLBACK = {
    "Tech": "Tech",
    "Business": "Markets and business",
    "Sports": "Sports",
    "Tensions/guerre/violences/géopolitique": "Guerre/violence",
    "Politique américaine": "Politique américaine",
}

# ---------------------------------------------------------------- pipeline
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", help="CSV d'entrée : media;titre;lien;date")
    ap.add_argument("-o", "--out", default="consolide.csv")
    args = ap.parse_args()

    themes = compile_dict(load_dict(HERE / "themes.txt"))
    pays_raw = load_dict(HERE / "pays.txt")
    pays = compile_dict(pays_raw)
    rules = load_rules(HERE / "regles.txt", pays_raw)
    naval = load_naval(HERE / "naval.txt")
    zones = load_zones(HERE / "regions_maritimes.txt")
    alias = load_alias(HERE / "medias_alias.csv")
    bans = load_bans(HERE / "medias_bannis.txt")
    sys.path.insert(0, str(HERE))
    import traduction
    med_langues = traduction.load_medias_langues()
    regions = json.loads((HERE / "regions.json").read_text(encoding="utf-8"))
    medias = {}
    with open(HERE / "medias.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            medias[row["media"].strip().lower()] = row

    n_in = n_theme = n_pays = 0
    with open(args.logs, encoding="utf-8") as fin, \
         open(args.out, "w", encoding="utf-8", newline="") as fout:
        r = csv.DictReader(fin, delimiter=";")
        w = csv.writer(fout, delimiter=";")
        w.writerow(["nom_du_media", "titre", "lien", "time_stamp",
                    "country_headquarters", "country_article", "region",
                    "sujet_article", "sujet_media", "official_rating",
                    "indice_fiabilite", "notation", "fiabilité_calcul",
                    "indice_interet_naval", "region_maritime", "fiabilité2",
                    "intérêt marine calcul", "intérêt_par_fiabilité",
                    "confiance_pays_article", "langue", "titre_vo"])
        n_ban = n_trad = 0
        for row in r:
            n_in += 1
            if est_banni(row.get("media", ""), bans):
                n_ban += 1
                continue
            titre, titre_vo, lang = traduction.ensure_english(
                row.get("titre", ""), row.get("media", ""), med_langues)
            if titre_vo:
                n_trad += 1
            media = canonical_media(row.get("media", ""), alias)
            m = medias.get(media.lower(), {})
            gov = ".gov" in media.lower()
            minfo = (m.get("pays_siege", ""),
                     "Politique" if gov else m.get("theme_media", ""))
            th = classify_theme(titre, themes, rules)
            if th == "Non déterminé":
                th = THEME_FALLBACK.get(m.get("theme_media", ""), "Non déterminé")
            ca, conf = classify_pays(titre, pays, minfo)
            rg = regions.get(ca, "Undetermined")
            if th != "Non déterminé": n_theme += 1
            if ca != "Undetermined": n_pays += 1
            # indices fiabilité / naval — source inconnue = F et 4,5 par défaut
            notation = (m.get("notation") or "F").strip().upper()
            try:
                fia = float(m.get("indice_fiabilite") or 4.5)
            except ValueError:
                fia = 4.5
            fia = int(fia) if fia == int(fia) else fia
            nav = score_naval(titre, naval)
            zm = zone_maritime(titre, zones)
            fia_calc = round(40 / fia, 4)
            fia2 = round(0.6 / fia, 4)
            marine = round(nav * 0.4 / 40, 4)
            composite = round(fia2 + marine, 4)
            w.writerow([media, titre, row.get("lien", ""),
                        norm_date(row.get("date", "")),
                        m.get("pays_siege", "Undetermined"), ca, rg, th,
                        m.get("theme_media", ""), m.get("note", ""),
                        fia, notation, fia_calc, nav, zm, fia2, marine,
                        composite, conf, lang, titre_vo])

    print(f"{n_in} articles | {n_trad} traduits en anglais | {n_ban} doublons"
          f" écartés | thème déterminé : {n_theme} | pays déterminé : {n_pays}")
    print(f"→ {args.out}")

if __name__ == "__main__":
    main()
