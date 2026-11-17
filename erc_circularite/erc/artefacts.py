"""Dépôt des artefacts : tout ce que le pipeline produit est écrit ici et inscrit au manifeste.

    artefacts/
        manifeste.json                      liste de tous les artefacts (étape, nom, fichier, description, date, mode)
        00_sources/ ... 06_synthese/        une table = un CSV (séparateur « ; », décimale « , », UTF-8 avec BOM : s'ouvre dans Excel)
        <étape>/<étape>.xlsx                les tables de l'étape réunies dans un classeur
        <étape>/figures/*.png               les figures
        outil/ERC_Outil_Decision.html       l'outil des décideurs

Les notebooks n'affichent que ce qui est dans ce dépôt : ce qu'on voit à l'écran est ce qui est sur le disque.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DOSSIER_ETAPE


def _nom_fichier(nom: str) -> str:
    """« État des sources » → « Etat_des_sources » : sans accent ni espace, lisible sur tout système."""
    sans = "".join(c for c in unicodedata.normalize("NFKD", str(nom)) if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", sans).strip("_")


def vers_json(o):
    """Conversion sûre en JSON : NaN/NaT → null, numpy → python, dates → ISO, tuples → listes."""
    if o is None:
        return None
    if isinstance(o, dict):
        return {str(k): vers_json(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [vers_json(v) for v in o]
    if isinstance(o, pd.DataFrame):
        return [vers_json(r) for r in o.to_dict("records")]
    if isinstance(o, pd.Series):
        return vers_json(o.to_dict())
    if isinstance(o, (pd.Timestamp, datetime)):
        return None if pd.isna(o) else o.isoformat()
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if o is pd.NaT or (not isinstance(o, str) and pd.api.types.is_scalar(o) and pd.isna(o)):
        return None
    if isinstance(o, Path):
        return str(o)
    return o


class Depot:
    def __init__(self, racine: Path, demo: bool = False):
        self.racine = Path(racine)
        self.demo = demo
        self.racine.mkdir(parents=True, exist_ok=True)
        self._entrees: dict[tuple, dict] = {}
        self._tables: dict[str, dict[str, pd.DataFrame]] = {}
        f = self.racine / "manifeste.json"
        if f.is_file():
            try:
                for e in json.loads(f.read_text(encoding="utf-8")).get("artefacts", []):
                    self._entrees[(e["etape"], e["nom"], e["type"])] = e
            except (OSError, ValueError, KeyError):
                pass

    # ------------------------------------------------------------------ écriture
    def dossier(self, etape: str) -> Path:
        d = self.racine / DOSSIER_ETAPE.get(etape, etape)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _inscrire(self, etape, nom, type_, chemin: Path, description, **plus):
        self._entrees[(etape, nom, type_)] = {
            "etape": etape, "nom": nom, "type": type_, "fichier": chemin.relative_to(self.racine).as_posix(),
            "description": description, "genere_le": datetime.now().isoformat(timespec="seconds"),
            "donnees": "démonstration" if self.demo else "réelles", **plus}
        return chemin

    def table(self, etape: str, nom: str, df: pd.DataFrame, description: str = "") -> Path:
        df = df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
        chemin = self.dossier(etape) / f"{_nom_fichier(nom)}.csv"
        df.to_csv(chemin, sep=";", decimal=",", index=False, encoding="utf-8-sig")
        self._tables.setdefault(etape, {})[nom] = df
        return self._inscrire(etape, nom, "table", chemin, description, lignes=int(len(df)), colonnes=[str(c) for c in df.columns])

    def json(self, etape: str, nom: str, objet, description: str = "") -> Path:
        chemin = self.dossier(etape) / f"{_nom_fichier(nom)}.json"
        chemin.write_text(json.dumps(vers_json(objet), ensure_ascii=False, indent=1), encoding="utf-8")
        return self._inscrire(etape, nom, "json", chemin, description)

    def figure(self, etape: str, nom: str, fig, description: str = "") -> Path:
        d = self.dossier(etape) / "figures"
        d.mkdir(exist_ok=True)
        chemin = d / f"{_nom_fichier(nom)}.png"
        fig.savefig(chemin, dpi=150, bbox_inches="tight")
        return self._inscrire(etape, nom, "figure", chemin, description)

    def fichier(self, etape: str, nom: str, chemin: Path, description: str = "", type_: str = "fichier") -> Path:
        return self._inscrire(etape, nom, type_, Path(chemin), description)

    def classeur(self, etape: str) -> Path | None:
        """Réunit les tables de l'étape dans <étape>.xlsx (en-têtes figés, largeurs ajustées)."""
        tables = self._tables.get(etape)
        if not tables:
            return None
        chemin = self.dossier(etape) / f"{DOSSIER_ETAPE.get(etape, etape)}.xlsx"
        try:
            with pd.ExcelWriter(chemin, engine="openpyxl") as w:
                for nom, df in tables.items():
                    d = df.copy()
                    for c in d.columns:                       # openpyxl n'écrit ni tuples ni listes
                        if d[c].map(lambda v: isinstance(v, (tuple, list, dict, set))).any():
                            d[c] = d[c].map(lambda v: repr(v) if isinstance(v, (tuple, list, dict, set)) else v)
                    d.to_excel(w, sheet_name=_nom_fichier(nom)[:31] or "table", index=False)
                    ws = w.sheets[_nom_fichier(nom)[:31] or "table"]
                    ws.freeze_panes = "A2"
                    for i, c in enumerate(d.columns, 1):
                        largeur = max([len(str(c))] + [len(str(v)) for v in d[c].head(200)]) + 2
                        ws.column_dimensions[ws.cell(1, i).column_letter].width = min(largeur, 60)
        except (PermissionError, OSError):
            return None                                       # classeur ouvert dans Excel : les CSV restent à jour
        return self._inscrire(etape, f"classeur {etape}", "classeur", chemin, f"Toutes les tables de l'étape « {etape} »")

    def ecrire_manifeste(self) -> Path:
        f = self.racine / "manifeste.json"
        self._entrees = {k: e for k, e in self._entrees.items() if (self.racine / e["fichier"]).is_file()}
        entrees = sorted(self._entrees.values(), key=lambda e: (DOSSIER_ETAPE.get(e["etape"], e["etape"]), e["type"], e["nom"]))
        f.write_text(json.dumps({"donnees": "démonstration" if self.demo else "réelles",
                                 "mis_a_jour": datetime.now().isoformat(timespec="seconds"), "artefacts": entrees},
                                ensure_ascii=False, indent=1), encoding="utf-8")
        return f

    # ------------------------------------------------------------------ lecture
    def manifeste(self) -> pd.DataFrame:
        cols = ["etape", "type", "nom", "fichier", "lignes", "description", "genere_le", "donnees"]
        d = pd.DataFrame(list(self._entrees.values()))
        return d.reindex(columns=cols).sort_values(["etape", "type", "nom"]).reset_index(drop=True) if len(d) else pd.DataFrame(columns=cols)

    def chemin(self, etape: str, nom: str, type_: str = "table") -> Path | None:
        e = self._entrees.get((etape, nom, type_))
        return self.racine / e["fichier"] if e else None

    def lire_table(self, etape: str, nom: str) -> pd.DataFrame:
        if nom in self._tables.get(etape, {}):
            return self._tables[etape][nom]
        c = self.chemin(etape, nom)
        if c is None or not c.is_file():
            raise FileNotFoundError(f"Artefact absent : {etape}/{nom}. Exécuter l'étape « {etape} ».")
        return pd.read_csv(c, sep=";", decimal=",", encoding="utf-8-sig")

    def lire_json(self, etape: str, nom: str):
        c = self.chemin(etape, nom, "json")
        if c is None or not c.is_file():
            raise FileNotFoundError(f"Artefact absent : {etape}/{nom}. Exécuter l'étape « {etape} ».")
        return json.loads(c.read_text(encoding="utf-8"))

    def figures(self, etape: str) -> list[Path]:
        return [self.racine / e["fichier"] for (et, _, t), e in sorted(self._entrees.items()) if et == etape and t == "figure"
                and (self.racine / e["fichier"]).is_file()]
