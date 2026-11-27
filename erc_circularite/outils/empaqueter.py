"""Fabrique l'archive à déposer sur un poste : le dossier complet, sans données ni résultats, avec la liste des empreintes.

    python outils/empaqueter.py [dossier de sortie]      écrit ERC_circularite_<version>.zip

L'archive contient le code, les documents, les notebooks de démonstration et les tests. Elle ne contient ni artefacts,
ni paramètres saisis, ni cortex, ni la démonstration générée (elle se régénère au premier lancement). La liste
EMPREINTES.txt (SHA-256 de chaque fichier) permet au poste de vérifier que rien n'a été altéré : python -m erc.diagnostic.
"""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent.parent
INCLUS = ["README.md", "INSTALLATION.md", "requirements.txt", "Lancer.bat", "lancer.sh", ".dockerignore", "erc", "notebooks", "docs", "outils", "tests", "papier",
          "deploiement", "parametres/.gitkeep"]
ECARTES = {"__pycache__", ".ipynb_checkpoints", ".pytest_cache"}
JAMAIS = ("papier/site/", "papier/manuscrit_site.", "papier/Manuscrit_Overleaf_site.zip", "deploiement/volumes/")   # chiffres et résultats du site : ne quittent pas le poste
JAMAIS_EXACT = {"deploiement/.env"}                          # chemin de vos données sur la machine
REGENERABLES = ("papier/genere/", "papier/manuscrit.pdf", "papier/manuscrit.bbl", "papier/Manuscrit_Overleaf.zip")   # réécrits par python -m erc.papier --demo : hors empreintes
SUFFIXES_LATEX = {".aux", ".log", ".out", ".blg", ".toc"}
NOM_RACINE = "erc_circularite"
FICHIER_EMPREINTES = "EMPREINTES.txt"


def fichiers(racine: Path = DOSSIER) -> list:
    """Chemins relatifs des fichiers de l'archive, triés."""
    out = []
    for nom in INCLUS:
        p = racine / nom
        if p.is_file():
            out.append(Path(nom))
        elif p.is_dir():
            out += [f.relative_to(racine) for f in p.rglob("*") if f.is_file() and not (set(f.parts) & ECARTES) and f.suffix != ".pyc"]
    garde = lambda f: ((f.as_posix() == "papier/manuscrit_site.tex" or not f.as_posix().startswith(JAMAIS)) and f.as_posix() not in JAMAIS_EXACT
                       and f.suffix not in SUFFIXES_LATEX)
    return sorted([f for f in out if garde(f)], key=lambda f: f.as_posix())


def empaqueter(sortie, racine: Path = DOSSIER) -> Path:
    sys.path.insert(0, str(racine))
    import erc
    sortie = Path(sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    archive = sortie / f"ERC_circularite_{erc.__version__}.zip"
    liste = fichiers(racine)
    empreintes = "".join(f"{hashlib.sha256((racine / f).read_bytes()).hexdigest()}  {f.as_posix()}\n" for f in liste
                         if not f.as_posix().startswith(REGENERABLES))
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for f in liste:
            z.write(racine / f, f"{NOM_RACINE}/{f.as_posix()}")
        z.writestr(f"{NOM_RACINE}/{FICHIER_EMPREINTES}", empreintes)
    return archive


if __name__ == "__main__":
    a = empaqueter(sys.argv[1] if len(sys.argv) > 1 else DOSSIER.parent / "dist")
    print(f"{a}  ({a.stat().st_size / 1e6:.1f} Mo, {len(fichiers())} fichiers)")
