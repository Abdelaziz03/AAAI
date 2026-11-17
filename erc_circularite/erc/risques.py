"""Risque matière et risque supply par pièce, et pré-sélection par front de Pareto.

Règle du projet : toute table codée en dur porte sa source ; une valeur inconnue reste inconnue.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 1. Risque matière : tables codées en dur
# ---------------------------------------------------------------------------
# Liste UE des matières premières critiques (CRM, 34) et stratégiques (17), Règlement (UE) 2024/1252
# (Critical Raw Materials Act), annexes I et II. À re-vérifier contre le texte publié avant diffusion.
CRM_UE = {
    "antimoine", "arsenic", "bauxite/alumine/aluminium", "baryte", "béryllium", "bismuth", "bore", "cobalt",
    "charbon à coke", "cuivre", "feldspath", "fluorine", "gallium", "germanium", "hafnium", "hélium",
    "terres rares lourdes", "terres rares légères", "lithium", "magnésium", "manganèse", "graphite naturel",
    "nickel", "niobium", "phosphate naturel", "phosphore", "platinoïdes (PGM)", "scandium", "silicium métal",
    "strontium", "tantale", "titane métal", "tungstène", "vanadium",
}
STRATEGIQUES_UE = {
    "bismuth", "bore", "cobalt", "cuivre", "gallium", "germanium", "lithium", "magnésium", "manganèse",
    "graphite naturel", "nickel", "platinoïdes (PGM)", "terres rares lourdes", "terres rares légères",
    "silicium métal", "titane métal", "tungstène", "bauxite/alumine/aluminium",
}
# Métaux précieux : pas CRM (sauf PGM) mais pilotent le prix recycleur des cartes.
PRECIEUX = {"or", "argent", "platinoïdes (PGM)"}

# Composition qualitative par type de pièce (présence, pas de teneur). Teneurs réelles : fiche
# matière fabricant (IPC-1752 / déclaration RoHS-REACH) ou analyse du recycleur, à demander.
COMPOSITION_TYPE = {
    # type               (motif sur la description,                                    matières présentes)
    "IGBT / module de puissance": (r"\bigbt\b|power module|mosfet", ["cuivre", "bauxite/alumine/aluminium", "silicium métal", "argent", "étain"]),
    "Condensateur électrolytique": (r"electrolytic|électrolytique|\bcap(acitor)?\b.*\buf\b", ["bauxite/alumine/aluminium", "papier", "électrolyte"]),
    "Condensateur tantale": (r"tantal", ["tantale", "manganèse"]),
    "Carte électronique": (r"board|\bbd\b|\bpwa\b|\bpcb\b|carte|driver|controller|assembly", ["cuivre", "or", "argent", "platinoïdes (PGM)", "étain", "tantale", "gallium", "antimoine", "verre-époxy"]),
    "Fusible": (r"fuse|fusible", ["cuivre", "argent", "céramique"]),
    "Résistance de puissance": (r"resist", ["nickel", "cuivre", "céramique"]),
    "Câble / faisceau": (r"cable|câble|harness|wire", ["cuivre", "PVC"]),
    "Bobine / antenne IRM": (r"\bcoil\b|bobine|antenne", ["cuivre", "verre-époxy", "or", "argent"]),
    "Aimant": (r"magnet|aimant|ndfeb", ["terres rares légères", "terres rares lourdes", "bore", "cobalt"]),
    "Ventilateur / moteur": (r"\bfan\b|ventil|motor|moteur", ["cuivre", "terres rares légères", "plastique"]),
    "Pièce plastique / mécanique": (r"cover|coque|grille|joystick|caoutch|bellow|soufflet|sleeve|key|cap |toggle|handle", ["plastique", "élastomère"]),
}


def type_piece(description: str) -> str:
    d = str(description).lower()
    for t, (motif, _) in COMPOSITION_TYPE.items():
        if re.search(motif, d):
            return t
    return "(type non reconnu)"


def risque_matiere(description: str) -> dict:
    """Score 0–1 : part des matières CRM pondérée (stratégique = 2, CRM = 1), plus indicateurs utiles au recycleur."""
    t = type_piece(description)
    mats = COMPOSITION_TYPE.get(t, (None, []))[1]
    if not mats:
        return {"Type de pièce": t, "Matières (présence)": "", "CRM": "", "Stratégiques": "",
                "Score risque matière (0-1)": np.nan, "Métaux précieux": False}
    crm = [m for m in mats if m in CRM_UE]
    strat = [m for m in mats if m in STRATEGIQUES_UE]
    points = sum(2 if m in STRATEGIQUES_UE else 1 for m in crm)
    return {"Type de pièce": t, "Matières (présence)": ", ".join(mats), "CRM": ", ".join(crm),
            "Stratégiques": ", ".join(strat), "Score risque matière (0-1)": min(points / 8, 1.0),
            "Métaux précieux": any(m in PRECIEUX for m in mats)}


# ---------------------------------------------------------------------------
# 2. Risque supply : table par référence, codée en dur, à remplir avec les achats
# ---------------------------------------------------------------------------
# Table remplie à l'exécution depuis l'onglet « Supply » du classeur de paramètres (achats) :
#   {référence: {"Délai (semaines)": 26, "Source": "achats, date"}}. Aucune référence n'est codée ici.
SUPPLY: dict = {}
# Délai au-delà duquel le risque supply est maximal (modifiable).
DELAI_CRITIQUE_SEM = 26


def risque_supply(reference: str, type_p: str = "") -> dict:
    """Risque supply = délai d'approvisionnement seul (choix du projet). Score = délai / DELAI_CRITIQUE_SEM, plafonné à 1.
    Source unique et fin de vie restent dans la table à titre d'information, hors score."""
    s = SUPPLY.get(str(reference), {})
    d = s.get("Délai (semaines)")
    return {"Délai (semaines)": d, "Score risque supply (0-1)": min(d / DELAI_CRITIQUE_SEM, 1.0) if d is not None else np.nan,
            "A priori supply (type)": 0.6 if type_p in ("IGBT / module de puissance", "Carte électronique") else np.nan,
            "Source supply": s.get("Source", "aucune")}


# ---------------------------------------------------------------------------
# 6. Pré-sélection : front de Pareto plutôt qu'une note unique
# ---------------------------------------------------------------------------
def front_pareto(df: pd.DataFrame, maximiser: list[str]) -> pd.Series:
    """True si aucune autre ligne n'est au moins aussi bonne sur tous les critères et meilleure sur un.
    Les NaN comptent comme le pire niveau : une référence sans donnée ne domine rien."""
    X = df[maximiser].astype(float).fillna(-np.inf).to_numpy()
    domine = np.zeros(len(X), bool)
    for i in range(len(X)):
        domine[i] = np.any(np.all(X >= X[i], axis=1) & np.any(X > X[i], axis=1))
    return pd.Series(~domine, index=df.index)


def score_pondere(df: pd.DataFrame, poids: dict) -> pd.Series:
    """Note 0–1 après normalisation rang-centile ; à n'utiliser qu'après accord de l'équipe sur les poids."""
    s = sum(w * df[c].rank(pct=True).fillna(0) for c, w in poids.items())   # donnée absente = pire niveau
    return s / sum(abs(w) for w in poids.values())
