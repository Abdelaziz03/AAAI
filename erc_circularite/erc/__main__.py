"""python -m erc [--demo] [--jusqua étape] [--dossier chemin] [--projet chemin] [--racine chemin]"""
import argparse

from .config import ETAPES, charger
from .etapes import executer


def main():
    a = argparse.ArgumentParser(prog="python -m erc", description="Pipeline ERC circularité : sources → artefacts → outil des décideurs")
    a.add_argument("--demo", action="store_true", help="jeu de démonstration fictif (dossier demo/)")
    a.add_argument("--jusqua", default="synthese", choices=ETAPES)
    a.add_argument("--dossier", help="dossier de travail (défaut : celui du paquet)")
    a.add_argument("--projet", help="dossier des extractions R26")
    a.add_argument("--racine", help="dossier des référentiels (défaut : parent du projet)")
    o = a.parse_args()
    cfg = charger(dossier=o.dossier, projet=o.projet, racine=o.racine, demo=True if o.demo else None)
    ctx = executer(o.jusqua, cfg=cfg)
    print("Dossier :", ctx.cfg.dossier, "| artefacts dans", ctx.cfg.artefacts.name + "/")


if __name__ == "__main__":
    main()
