"""Configuration du dossier ERC circularité : où sont les sources, où vont les artefacts.

Le dossier contient tout ce qui est produit :
    <dossier>/parametres/   classeur des paramètres saisis (ERC_Parametres.xlsx) et chemins.json
    <dossier>/artefacts/    tables, figures, classeurs par étape, manifeste, outil des décideurs
    <dossier>/demo/         jeu de démonstration complet (sources fictives, paramètres, artefacts)

Les données réelles ne sont jamais copiées dans le dossier : elles sont lues là où elles se trouvent.
    projet  : dossier des extractions R26 (ERC_R26_extraction_*.xlsx, Classification_matieres/, Extraction_R26/, Acquisition/)
    racine  : son dossier parent (ERC_Valorisation_MICV_v1.xlsx, FRU_info.xlsx, fichier de fiabilité)

Ordre de résolution des chemins : argument de `charger`, variable d'environnement (ERC_PROJET, ERC_RACINE,
ERC_DOSSIER, ERC_DEMO), `parametres/chemins.json`, puis recherche automatique. Sans extraction trouvée, le
mode démonstration s'active et le signale partout.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

MOTIF_EXTRACTION = "ERC_R26_extraction_????????_????????.xlsx"
NOM_PROJET = "ERC_Flux_Dechets_Ateliers"
NOM_CLASSEUR = "ERC_Parametres.xlsx"
ETAPES = ["sources", "classement", "flux", "fiabilite", "rex", "ligne", "synthese"]
DOSSIER_ETAPE = {e: f"{i:02d}_{e}" for i, e in enumerate(ETAPES)}


@dataclass
class Config:
    dossier: Path                       # racine du dossier (contient parametres/ et artefacts/)
    projet: Path | None                 # extractions R26 et sous-dossiers
    racine: Path | None                 # parent du projet : valorisation, FRU_info, fiabilité
    demo: bool = False
    # Options d'analyse
    ateliers_prioritaires: list = field(default_factory=lambda: ["MR", "TSUI"])
    debut: str | None = None            # "AAAA-MM-JJ" inclus ; None = tout
    fin: str | None = None              # "AAAA-MM-JJ" exclu ; None = tout
    n_top: int = 30                     # lignes affichées dans les notebooks (les artefacts gardent tout)
    n_fru_gabarit: int = 10             # types de FRU proposés dans le classeur de paramètres
    n_pieces_gabarit: int = 7           # pièces proposées par FRU (+ la carcasse)
    par_flux: str = "Benne"             # granularité du suivi hebdomadaire : "Benne" ou "Type de déchet"
    col_date_rebut: str | None = None   # colonne qui date le rebut ; None = recherche automatique affichée
    fenetre_elf_jours: float | None = None
    garantie_jours: int = 365
    n_monte_carlo: int = 400
    graine: int = 2026

    @property
    def artefacts(self) -> Path:
        return self.dossier / "artefacts"

    @property
    def parametres(self) -> Path:
        return self.dossier / "parametres"

    @property
    def classeur(self) -> Path:
        return self.parametres / NOM_CLASSEUR

    @property
    def mode(self) -> str:
        return "DÉMONSTRATION (données fictives)" if self.demo else "données réelles"

    def resume(self) -> dict:
        return {"Mode": self.mode, "Dossier": str(self.dossier), "Extractions (projet)": str(self.projet),
                "Référentiels (racine)": str(self.racine), "Artefacts": str(self.artefacts), "Paramètres": str(self.classeur)}


def dossier_par_defaut() -> Path:
    return Path(os.environ.get("ERC_DOSSIER") or Path(__file__).resolve().parent.parent)


def _a_des_extractions(p: Path | None) -> bool:
    return bool(p) and Path(p).is_dir() and any(Path(p).glob(MOTIF_EXTRACTION))


def _chercher_projet(dossier: Path) -> Path | None:
    candidats = [Path.cwd(), *Path.cwd().parents, dossier, *dossier.parents]
    candidats += [c / NOM_PROJET for c in list(candidats)]
    try:                                   # dossiers synchronisés du poste (« OneDrive », « OneDrive - <organisation> ») et Documents
        candidats += [d / NOM_PROJET for d in sorted(Path.home().glob("OneDrive*")) if d.is_dir()]
    except OSError:
        pass
    candidats.append(Path.home() / "Documents" / NOM_PROJET)
    for c in candidats:
        try:
            if _a_des_extractions(c):
                return c
        except OSError:
            continue
    return None


def charger(dossier=None, projet=None, racine=None, demo: bool | None = None, **options) -> Config:
    """Construit la configuration. `options` remplace les options d'analyse (n_top, debut, fin, ...)."""
    dossier = Path(dossier) if dossier else dossier_par_defaut()
    memo = {}
    f = dossier / "parametres" / "chemins.json"
    if f.is_file():
        try:
            memo = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            memo = {}
    if demo is None:
        demo = os.environ.get("ERC_DEMO", "").strip() in ("1", "true", "oui")
    if not demo:
        projet = projet or os.environ.get("ERC_PROJET") or memo.get("projet")
        projet = Path(projet) if projet else _chercher_projet(dossier)
        if not _a_des_extractions(projet):
            demo = True                 # aucune extraction : démonstration, signalée dans tous les artefacts
    if demo:
        from . import demo as _demo
        d = dossier / "demo"
        cfg = Config(dossier=d, projet=d / "sources" / NOM_PROJET, racine=d / "sources", demo=True)
        _demo.generer(cfg)
    else:
        racine = racine or os.environ.get("ERC_RACINE") or memo.get("racine")
        cfg = Config(dossier=dossier, projet=Path(projet), racine=Path(racine) if racine else Path(projet).parent, demo=False)
    for k, v in {**memo.get("options", {}), **options}.items():
        if hasattr(cfg, k) and v is not None:
            setattr(cfg, k, v)
    return cfg


def memoriser_chemins(projet, racine=None, dossier=None, **options) -> Path:
    """Écrit parametres/chemins.json pour que tous les notebooks retrouvent les sources réelles."""
    dossier = Path(dossier) if dossier else dossier_par_defaut()
    f = dossier / "parametres" / "chemins.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"projet": str(projet), "racine": str(racine) if racine else None, "options": options},
                            ensure_ascii=False, indent=2), encoding="utf-8")
    return f
