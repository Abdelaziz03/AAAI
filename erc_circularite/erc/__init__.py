"""ERC circularité : du flux des FRU scrapées à la décision (ligne de démontage et de tri, réemploi, recyclage).

    import erc
    ctx = erc.executer()                 # tout le pipeline ; ctx.res[étape][nom], ctx.depot, ctx.src
    ctx = erc.executer(jusqua="flux")    # seulement jusqu'à une étape
"""
from .config import ETAPES, charger as charger_config, memoriser_chemins
from .etapes import Contexte, executer

__version__ = "1.0.0"
__all__ = ["ETAPES", "charger_config", "memoriser_chemins", "Contexte", "executer", "__version__"]
