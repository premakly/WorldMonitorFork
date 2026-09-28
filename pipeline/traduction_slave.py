"""
Traduction croate / serbe / bosnien → anglais, langues absentes d'Argos.

Modèle : Helsinki-NLP/opus-mt-sla-en (Opus-MT, langues slaves → anglais),
converti une fois au format CTranslate2 (int8, ~80 Mo), puis utilisé sans
transformers ni GPU : seulement ctranslate2 et sentencepiece, déjà installés
avec Argos.

  python pipeline/traduction_slave.py preparer
      Télécharge le modèle depuis Hugging Face et le convertit dans DOSSIER.
      Nécessite une fois : pip install transformers  (torch est déjà là via Argos)

  python pipeline/traduction_slave.py test
      Traduit quelques titres croates et serbes d'exemple.

Emplacement du modèle : $WM_MODELES/opus-mt-sla-en
(par défaut ~/.local/share/wm-modeles/opus-mt-sla-en).
"""
import os
import sys
from pathlib import Path

MODELE_HF = "Helsinki-NLP/opus-mt-sla-en"
DOSSIER = Path(os.environ.get("WM_MODELES",
                              Path.home() / ".local" / "share" / "wm-modeles")) / "opus-mt-sla-en"
LANGUES = {"hr", "sr", "bs"}

_moteur = None


def disponible():
    return (DOSSIER / "model.bin").exists()


def preparer():
    if disponible():
        print(f"Modèle déjà prêt : {DOSSIER}")
        return
    try:
        from ctranslate2.converters import TransformersConverter
        import transformers  # noqa: F401
    except ImportError as e:
        sys.exit(f"Il manque une dépendance pour la conversion ({e}).\n"
                 "Installe-la une fois : pip install transformers")
    print(f"Téléchargement et conversion de {MODELE_HF}…")
    DOSSIER.parent.mkdir(parents=True, exist_ok=True)
    tmp = DOSSIER.with_name(DOSSIER.name + ".part")
    TransformersConverter(MODELE_HF, copy_files=["source.spm", "target.spm"]).convert(
        str(tmp), quantization="int8", force=True)
    tmp.replace(DOSSIER)
    taille = sum(p.stat().st_size for p in DOSSIER.iterdir()) / 1e6
    print(f"✔ modèle prêt : {DOSSIER} ({taille:.0f} Mo)")


def _charger():
    global _moteur
    if _moteur is None:
        import ctranslate2
        import sentencepiece as spm
        _moteur = (
            ctranslate2.Translator(str(DOSSIER), device="cpu", compute_type="int8",
                                   inter_threads=1, intra_threads=os.cpu_count() or 1),
            spm.SentencePieceProcessor(model_file=str(DOSSIER / "source.spm")),
            spm.SentencePieceProcessor(model_file=str(DOSSIER / "target.spm")),
        )
    return _moteur


def traduire_lot(titres, taille_lot=32):
    """Liste de titres → liste de traductions (None si échec pour un titre)."""
    if not disponible():
        return [None] * len(titres)
    trad, sp_src, sp_tgt = _charger()
    out = []
    for i in range(0, len(titres), taille_lot):
        lot = titres[i:i + taille_lot]
        sources = [sp_src.encode(str(t), out_type=str) + ["</s>"] for t in lot]
        try:
            res = trad.translate_batch(sources, beam_size=4, max_decoding_length=200)
            for r in res:
                pieces = [p for p in r.hypotheses[0] if p not in ("</s>", "<pad>")]
                texte = sp_tgt.decode(pieces).strip()
                out.append(texte or None)
        except Exception as e:
            print(f"  ⚠ Opus-MT : {type(e).__name__}: {e}")
            out.extend([None] * len(lot))
    return out


def traduire(titre):
    return traduire_lot([titre])[0]


EXEMPLES = [
    "Vlada je donijela nove mjere protiv inflacije",
    "Potres jačine 5,2 po Richteru pogodio je Zagreb",
    "Hrvatska mornarica dobila novi ophodni brod",
    "Predsjednik Srbije sastao se s delegacijom EU u Beogradu",
    "Premijer najavio smanjenje poreza na gorivo od 1. listopada",
]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "preparer":
        preparer()
    elif cmd == "test":
        if not disponible():
            sys.exit("Modèle absent : lance d'abord « preparer ».")
        for src, dst in zip(EXEMPLES, traduire_lot(EXEMPLES)):
            print(f"  {src}\n  → {dst}\n")
    else:
        sys.exit(__doc__)
