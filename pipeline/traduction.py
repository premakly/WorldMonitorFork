#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Traduction des titres non anglais — Argos Translate (open source, hors-ligne).

Principe éthique : on ne jette aucune langue. Un titre non anglais est traduit
en anglais (pour la classification et la recherche) ; l'original et la langue
source sont conservés. Si la traduction est impossible (modèle absent, échec)
OU visiblement ratée (boucle de répétition, longueur anormale), l'article est
GARDÉ avec son titre ORIGINAL lisible, marqué de sa langue.

Détection de langue sans dépendance : alphabets d'abord (grec, cyrillique,
arabe, hébreu, devanagari, CJK…), puis duel de mots-outils pour les langues
latines, puis la langue déclarée du média (medias_langues.csv).
"""
import re, csv
from pathlib import Path

HERE = Path(__file__).parent

# ---------------------------------------------------------------- détection
_SCRIPTS = [
    ("el", re.compile(r"[Ͱ-Ͽἀ-῿]")),
    ("ru", re.compile(r"[Ѐ-ӿ]")),
    ("ar", re.compile(r"[؀-ۿ]")),
    ("he", re.compile(r"[֐-׿]")),
    ("hi", re.compile(r"[ऀ-ॿ]")),
    ("th", re.compile(r"[฀-๿]")),
    ("ko", re.compile(r"[가-힯]")),
    ("ja", re.compile(r"[぀-ヿ]")),
    ("zh", re.compile(r"[一-鿿]")),
]
_VIET = re.compile(r"[ăđơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.I)
_STOPS = {
    "en": {"the", "of", "to", "and", "in", "for", "on", "with", "as", "at", "by",
           "from", "is", "are", "was", "will", "after", "over", "new", "says",
           "his", "her", "its", "their", "has", "have", "be", "not", "no",
           "what", "who", "more", "about", "into", "amid", "than"},
    "fr": {"le", "la", "les", "des", "une", "du", "au", "aux", "avec", "pour",
           "dans", "est", "sont", "sur", "pas", "par", "qui", "que", "plus"},
    "es": {"el", "los", "las", "una", "del", "por", "para", "con", "más",
           "este", "esta", "como", "pero", "sus", "según", "tras"},
    "de": {"der", "die", "das", "und", "ist", "nicht", "mit", "für", "von",
           "dem", "den", "ein", "eine", "auf", "wird", "nach", "über", "sich"},
    "it": {"il", "lo", "gli", "della", "delle", "di", "che", "con", "per",
           "una", "sono", "più", "anche", "dopo", "nel"},
    "pt": {"os", "uma", "das", "dos", "não", "com", "por", "para", "mais",
           "como", "foi", "são", "após"},
    "nl": {"het", "een", "van", "voor", "met", "naar", "wordt", "niet", "bij"},
    "id": {"yang", "dan", "untuk", "dari", "dengan", "akan", "pada", "tidak"},
    "tr": {"ve", "bir", "için", "ile", "bu", "olarak", "sonra", "yeni"},
    "hu": {"és", "hogy", "nem", "már", "csak", "még", "lesz", "szerint",
           "után", "ellen", "miatt", "volt", "kell"},
    "pl": {"nie", "się", "jest", "oraz", "przez", "które", "tylko", "czy",
           "dla", "został", "będzie", "roku"},
    "ro": {"și", "nu", "este", "pentru", "din", "mai", "care", "după",
           "fost", "sunt", "despre"},
    "cs": {"není", "jsou", "jako", "pro", "podle", "které", "byl", "bude"},
    "sv": {"och", "att", "är", "för", "med", "inte", "som", "har", "ett",
           "efter", "ska", "vill", "öka", "nya"},
    "da": {"og", "er", "til", "det", "ikke", "som", "ved", "efter", "skal"},
    "fi": {"ja", "ei", "että", "joka", "mutta", "myös", "kun"},
    "hr": {"je", "su", "za", "na", "koji", "kako", "nakon", "protiv"},
}
_LATIN_EXT = re.compile(r"[Ā-ɏ]")


def load_medias_langues(path=None):
    """medias_langues.csv → {media: code langue} (langue déclarée du flux)."""
    p = Path(path) if path else HERE / "medias_langues.csv"
    out = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ";" not in line:
                continue
            m, l = [x.strip() for x in line.split(";", 1)]
            if m and l and m != "media":
                out[m.lower()] = l.lower()
    return out


def detect_lang(titre, media="", medias_langues=None):
    """Code langue ('en', 'de', 'hu', …). Priorité : alphabet → mots-outils →
    langue déclarée du média → latin étendu → 'en'."""
    t = str(titre)
    for code, pat in _SCRIPTS:
        if pat.search(t):
            return code
    if len(_VIET.findall(t)) >= 2:
        return "vi"
    toks = re.findall(r"[a-zà-ÿā-ɏ']+", t.lower())
    scores = {l: sum(1 for w in toks if w in s) for l, s in _STOPS.items()}
    en = scores.pop("en")
    best = max(scores, key=scores.get) if scores else None
    if best and scores[best] >= 2 and scores[best] > en:
        return best
    if en >= 2:
        return "en"
    # signal faible : la langue déclarée du média tranche
    decl = (medias_langues or {}).get(str(media).strip().lower())
    if decl:
        return decl
    if en >= 1:
        return "en"
    if len(_LATIN_EXT.findall(t)) >= 1:
        return "xx"          # non anglais, langue latine indéterminée
    if len(re.findall(r"[à-ÿ]", t.lower())) >= 3:
        return "xx"
    return "en"


# ------------------------------------------------ contrôle qualité traduction
# un fragment de 2 à 20 caractères répété 5 fois ou plus d'affilée
_LOOP = re.compile(r"(.{2,20}?)\1{4,}")


def traduction_cassee(traduit, original=""):
    """True si la sortie du traducteur est visiblement ratée : boucle de
    répétition (« mainstremainstre… »), mot unique anormalement long, sortie
    démesurée par rapport à l'entrée, ou très peu de caractères distincts.
    Utilisée par ensure_english ET par assembler.py (pour repérer et reprendre
    les anciennes traductions déjà cassées de l'archive)."""
    t = (traduit or "").strip()
    if not t:
        return True
    if _LOOP.search(t):                                   # 1) boucle répétée
        return True
    if max((len(w) for w in t.split()), default=0) > 45:  # 2) mot géant sans espace
        return True
    o = (original or "").strip()
    if len(t) > 200 and len(t) > 3 * len(o) + 40:         # 3) sortie démesurée
        return True
    if len(t) > 60 and len(set(t)) / len(t) < 0.15:       # 4) trop peu de variété
        return True
    return False


# ---------------------------------------------------------------- traduction
_ARGOS_OK = None
_ARGOS_ERR = ""
_INSTALLED = set()
_ECHECS = set()


def _argos():
    """Charge argostranslate si présent (sinon mode dégradé sans traduction)."""
    global _ARGOS_OK, _ARGOS_ERR
    if _ARGOS_OK is None:
        try:
            import argostranslate.package, argostranslate.translate  # noqa
            _ARGOS_OK = True
        except Exception as e:
            _ARGOS_OK = False
            _ARGOS_ERR = f"{type(e).__name__}: {e}"
            print(f"⚠ TRADUCTION INDISPONIBLE — {_ARGOS_ERR}")
    return _ARGOS_OK


def moteur_statut():
    return "Argos opérationnel" if _argos() else f"ARGOS INDISPONIBLE ({_ARGOS_ERR})"


def _ensure_model(code):
    """Installe (et met en cache) le modèle code→en si nécessaire."""
    import argostranslate.package as pkg
    if code in _INSTALLED:
        return True
    installed = {(p.from_code, p.to_code) for p in pkg.get_installed_packages()}
    if (code, "en") in installed:
        _INSTALLED.add(code)
        return True
    if code in _ECHECS:
        return False
    try:
        pkg.update_package_index()
        for p in pkg.get_available_packages():
            if p.from_code == code and p.to_code == "en":
                print(f"  téléchargement du modèle {code}→en…")
                pkg.install_from_path(p.download())
                _INSTALLED.add(code)
                return True
        print(f"  ⚠ aucun modèle {code}→en dans l'index Argos")
    except Exception as e:
        print(f"  ⚠ échec modèle {code}→en : {type(e).__name__}: {e}")
    _ECHECS.add(code)
    return False


def traduire(titre, code):
    """Titre traduit en anglais, ou None si impossible / traduction ratée."""
    if code in ("en", "xx") or not _argos():
        return None
    try:
        if not _ensure_model(code):
            return None
        import argostranslate.translate as tr
        out = tr.translate(str(titre), code, "en")
        out = out.strip() if out else ""
        return out or None
    except Exception:
        return None


def ensure_english(titre, media="", medias_langues=None):
    """→ (titre_pour_classification, titre_vo, langue).
    Anglais : (titre, '', 'en'). Traduit OK : (traduction, original, langue).
    Intraduisible OU traduction ratée : (titre_original, '', langue) — on garde
    l'original lisible plutôt qu'un charabia, marqué de sa langue."""
    lang = detect_lang(titre, media, medias_langues)
    if lang == "en":
        return titre, "", "en"
    tr = traduire(titre, lang)
    if tr is None:                      # traduction impossible (modèle absent, échec)
        return titre, "", lang          #   → titre_vo vide : on retentera plus tard
    if traduction_cassee(tr, titre):    # traduction VISIBLEMENT ratée (boucle, longueur…)
        return titre, titre, lang       #   → garde l'original lisible, ne retente plus
    return tr, titre, lang              # traduction propre
