"""Outils communs aux tests de la couche de données : des sources fictives générées une fois, copiées pour chaque test."""
import shutil
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

import erc  # noqa: E402
from erc import config as mod_config  # noqa: E402


@pytest.fixture(scope="session")
def sources_demo(tmp_path_factory):
    """Dossier de démonstration généré une fois : <d>/demo/sources contient les fichiers fictifs aux formats réels."""
    d = tmp_path_factory.mktemp("demo_session")
    erc.charger_config(dossier=d, demo=True)
    return d / "demo" / "sources"


@pytest.fixture()
def reel(tmp_path, sources_demo):
    """Copie des sources fictives, utilisée comme si c'étaient des données réelles (aucun mode démonstration).
    Renvoie (dossier de travail, projet, racine)."""
    src = tmp_path / "sources"
    shutil.copytree(sources_demo, src)
    return tmp_path / "dossier", src / mod_config.NOM_PROJET, src


def lancer(dossier, projet, racine, jusqua="synthese", **options):
    """Pipeline en mode « données réelles », sans figures et avec peu de tirages pour rester rapide."""
    cfg = erc.charger_config(dossier=dossier, projet=projet, racine=racine, demo=False)
    cfg.figures, cfg.n_monte_carlo = False, 25
    for k, v in options.items():
        setattr(cfg, k, v)
    return erc.executer(jusqua, cfg=cfg, silencieux=True)
