"""Flux d'entrée suivi à la semaine : masse estimée (SQL × poids unitaires) contre masse pesée sur le terrain.

Le modèle de ligne (erc.ligne) n'est fiable qu'à la granularité où ce flux est vérifié : ce module donne
  1. le tableau composants → type de déchet → benne ;
  2. la masse estimée par semaine et par flux, avec sa marge d'erreur ;
  3. le rapprochement avec les pesées, l'écart et ses causes candidates.

Marge d'erreur de l'estimation (aucune hypothèse cachée) :
  borne basse = kg des pièces au poids connu (les autres comptées à 0) ;
  borne haute = borne basse / part des pièces au poids connu (les autres supposées au poids moyen du flux) ;
  s'y ajoute l'incertitude relative des poids unitaires (INCERTITUDE_POIDS, None tant qu'elle n'est pas mesurée).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .sources import ref, semaine

INCERTITUDE_POIDS = None      # ex. 0.10 pour ±10 % sur les poids unitaires ; None = non comptée, à mesurer par pesées répétées
SEUIL_COUVERTURE = 0.80       # sous ce taux de pièces au poids connu, la semaine est signalée


def tableau_composants(cl: pd.DataFrame, ev: pd.DataFrame | None = None, atelier_fru: dict | None = None) -> pd.DataFrame:
    """Composants avec type de déchet et benne, depuis l'onglet Classement_Tous_ateliers.
    Avec `ev` : une ligne par couple (FRU, composant) observé dans les extractions, avec les pièces consommées sur ce FRU."""
    cols = ["Référence", "Description", "Ateliers", "Catégorie proposée", "Benne", "Poids unitaire (kg)", "Source poids",
            "Niveau de preuve", "Pièces", "Kg (poids connus)"]
    t = cl[[c for c in cols if c in cl]].copy()
    t["Référence"] = t["Référence"].map(ref)
    t = t.rename(columns={"Catégorie proposée": "Type de déchet"})
    t["Poids connu"] = t["Poids unitaire (kg)"].notna() if "Poids unitaire (kg)" in t else False
    if ev is None or not len(ev):
        return t
    g = ev.groupby(["FRU ITEM", "Component ITEM"]).agg(**{"Pièces sur ce FRU": ("Qte", "sum"), "Jours avec sortie": ("Jour", "nunique")}).reset_index()
    g = g.rename(columns={"FRU ITEM": "FRU", "Component ITEM": "Référence"})
    out = g.merge(t.drop(columns=[c for c in ("Pièces", "Kg (poids connus)") if c in t]), on="Référence", how="left")
    out["Kg sur ce FRU (poids connus)"] = out["Pièces sur ce FRU"] * out["Poids unitaire (kg)"]
    if atelier_fru:
        out.insert(1, "Atelier du FRU", out["FRU"].map(atelier_fru))
    premiers = ["FRU"] + (["Atelier du FRU"] if atelier_fru else []) + ["Référence", "Description", "Type de déchet", "Benne"]
    return out[premiers + [c for c in out.columns if c not in premiers]].sort_values(["FRU", "Pièces sur ce FRU"], ascending=[True, False])


def estimation_hebdo(ev: pd.DataFrame, comp: pd.DataFrame, couverts: set, par="Benne") -> pd.DataFrame:
    """Masse estimée par semaine et par flux (`par` = « Benne » ou « Type de déchet »)."""
    c = comp.drop_duplicates("Référence").set_index("Référence")
    d = ev.copy()
    d["Semaine"] = semaine(d["Jour"])
    d["Flux"] = d["Component ITEM"].map(c[par]).fillna("(non classé)")
    d["Poids"] = d["Component ITEM"].map(c["Poids unitaire (kg)"])
    d["kg"] = d["Qte"] * d["Poids"]
    d["Qte connue"] = d["Qte"].where(d["Poids"].notna(), 0)
    g = d.groupby(["Semaine", "Flux"]).agg(**{"Pièces": ("Qte", "sum"), "Pièces au poids connu": ("Qte connue", "sum"),
                                             "Références": ("Component ITEM", "nunique"),
                                             # min_count=1 : un flux dont aucun poids n'est connu a une masse inconnue, pas nulle
                                             "Estimé bas (kg)": ("kg", lambda x: x.sum(min_count=1))}).reset_index()
    g["Couverture poids"] = g["Pièces au poids connu"] / g["Pièces"].replace(0, np.nan)
    g["Estimé haut (kg)"] = g["Estimé bas (kg)"] / g["Couverture poids"]
    if INCERTITUDE_POIDS:
        g["Estimé bas (kg)"] *= 1 - INCERTITUDE_POIDS
        g["Estimé haut (kg)"] *= 1 + INCERTITUDE_POIDS
    g["Estimé central (kg)"] = (g["Estimé bas (kg)"] + g["Estimé haut (kg)"]) / 2
    g["Marge d'erreur (± kg)"] = (g["Estimé haut (kg)"] - g["Estimé bas (kg)"]) / 2
    js = pd.Series(sorted(couverts))
    n_j = semaine(js).value_counts() if len(js) else pd.Series(dtype=int)
    g["Jours extraits"] = g["Semaine"].map(n_j).fillna(0).astype(int)
    return g


def rapprocher(est: pd.DataFrame, mesures: pd.DataFrame) -> pd.DataFrame:
    """Estimé contre mesuré. `mesures` : colonnes Semaine (une date de la semaine), Flux, Masse mesurée (kg),
    et facultatives Incertitude mesure (kg), Périmètre (ateliers dont les déchets sont dans cette pesée), Commentaire,
    Cause constatée (cause de l'écart observée sur place, reportée dans la dernière colonne du tableau)."""
    m = mesures.copy()
    m["Semaine"] = semaine(pd.to_datetime(m["Semaine"], dayfirst=True)) if len(m) else pd.to_datetime(m["Semaine"])
    m["Masse mesurée (kg)"] = pd.to_numeric(m["Masse mesurée (kg)"], errors="coerce")
    for c in ("Incertitude mesure (kg)", "Périmètre", "Commentaire", "Cause constatée"):
        if c not in m:
            m[c] = np.nan
    m = m.groupby(["Semaine", "Flux"]).agg(**{"Masse mesurée (kg)": ("Masse mesurée (kg)", "sum"),
                                              "Incertitude mesure (kg)": ("Incertitude mesure (kg)", lambda s: np.sqrt((s.fillna(0) ** 2).sum())),
                                              "Périmètre": ("Périmètre", "first"), "Commentaire": ("Commentaire", "first"),
                                              "Cause constatée": ("Cause constatée", "first")}).reset_index()
    m["Semaine"] = pd.to_datetime(m["Semaine"])
    t = est.merge(m, on=["Semaine", "Flux"], how="outer").sort_values(["Flux", "Semaine"])
    for c in ("Masse mesurée (kg)", "Incertitude mesure (kg)", "Estimé central (kg)", "Estimé bas (kg)", "Estimé haut (kg)"):
        t[c] = pd.to_numeric(t[c], errors="coerce")           # un fichier de pesées vide ne doit pas casser le calcul
    t["Écart (kg)"] = t["Masse mesurée (kg)"] - t["Estimé central (kg)"]
    t["Écart (%)"] = t["Écart (kg)"] / t["Estimé central (kg)"]
    u = t["Incertitude mesure (kg)"].fillna(0)
    t["Dans la marge"] = np.where(t["Masse mesurée (kg)"].isna() | t["Estimé central (kg)"].isna(), "non comparable",
                                  np.where((t["Masse mesurée (kg)"] + u >= t["Estimé bas (kg)"]) & (t["Masse mesurée (kg)"] - u <= t["Estimé haut (kg)"]), "oui", "non"))
    # Cumul par flux sur les semaines où les deux existent : absorbe le décalage des bacs individuels.
    deux = t["Masse mesurée (kg)"].notna() & t["Estimé central (kg)"].notna()
    t["Cumul estimé (kg)"] = t["Estimé central (kg)"].where(deux).groupby(t["Flux"]).cumsum()
    t["Cumul mesuré (kg)"] = t["Masse mesurée (kg)"].where(deux).groupby(t["Flux"]).cumsum()
    t["Écart cumulé (%)"] = (t["Cumul mesuré (kg)"] - t["Cumul estimé (kg)"]) / t["Cumul estimé (kg)"]
    t["Causes candidates de l'écart"] = t.apply(_causes, axis=1)
    # Saisie par l'atelier dans la colonne facultative « Cause constatée » du fichier des pesées, reportée telle quelle.
    t["Cause constatée (à saisir)"] = t["Cause constatée"].where(t["Cause constatée"].notna(), "") if "Cause constatée" in t else ""
    t = t.drop(columns=["Cause constatée"], errors="ignore")
    return t


def _causes(r) -> str:
    if pd.isna(r.get("Masse mesurée (kg)")):
        return "pas de pesée cette semaine"
    if pd.isna(r.get("Estimé central (kg)")):
        return "pesée sans consommation SQL : flux hors périmètre de l'extraction ou stock ancien"
    c = []
    if r.get("Jours extraits", 7) < 7:
        c.append(f"semaine SQL incomplète ({int(r['Jours extraits'])} j extraits)")
    if pd.notna(r.get("Couverture poids")) and r["Couverture poids"] < SEUIL_COUVERTURE:
        c.append(f"poids unitaires manquants ({1 - r['Couverture poids']:.0%} des pièces)")
    if r["Dans la marge"] == "non":
        if r["Écart (kg)"] > 0:
            c.append("mesuré > estimé : benne partagée avec d'autres ateliers, FRU entières rebutées, emballages, vidage de bacs remplis les semaines précédentes")
        else:
            c.append("mesuré < estimé : pièces encore dans les bacs individuels, pièces renvoyées en réparation ou réemployées, pièce consommée ≠ pièce jetée (kit)")
        if pd.notna(r.get("Écart cumulé (%)")) and abs(r["Écart cumulé (%)"]) < abs(r["Écart (%)"]) / 2:
            c.append("le cumul réduit l'écart de plus de moitié : décalage temporel probable")
    return " ; ".join(c) if c else "écart dans la marge d'erreur"


# ---------------------------------------------------------------------------
# Flux d'entrée du modèle de ligne : FRU rebutées par semaine et par type
# ---------------------------------------------------------------------------
def flux_fru_hebdo(fr: pd.DataFrame, couverts: set, poids_fru: pd.Series | None = None) -> pd.DataFrame:
    """Semaine x FRU : FRU rebutées et masse estimée. Les semaines extraites sans rebut comptent pour 0 (et non absentes)."""
    js = pd.Series(sorted(couverts))
    n_j = semaine(js).value_counts().sort_index() if len(js) else pd.Series(dtype=int)
    d = fr[fr["Date rebut"].isin(couverts)] if len(couverts) else fr
    g = d.assign(Semaine=semaine(d["Date rebut"])).groupby(["Semaine", "FRU"])["Unités"].sum()
    grille = pd.MultiIndex.from_product([n_j.index, sorted(d["FRU"].unique())], names=["Semaine", "FRU"])
    t = g.reindex(grille, fill_value=0).rename("FRU rebutées").reset_index()
    t["Jours extraits"] = t["Semaine"].map(n_j).astype(int)
    t["Semaine complète"] = t["Jours extraits"].eq(7)
    if poids_fru is not None:
        t["Poids FRU (kg)"] = t["FRU"].map(poids_fru)
        t["Masse estimée (kg)"] = t["FRU rebutées"] * t["Poids FRU (kg)"]
    return t


def rebut_annuel(flux: pd.DataFrame, n_boot=2000, rng=None) -> pd.DataFrame:
    """N_f du modèle : moyenne hebdomadaire x 52 sur les semaines COMPLÈTES, avec intervalle par ré-échantillonnage
    des semaines. `rebut_an` est le triangle (bas, moyen, haut) à passer à la ligne de tri."""
    rng = np.random.default_rng(2026) if rng is None else rng      # un générateur par appel : deux exécutions donnent le même intervalle
    lignes = []
    for f, g in flux[flux["Semaine complète"]].groupby("FRU"):
        x = g["FRU rebutées"].to_numpy(float)
        if len(x) < 2:
            lignes.append({"FRU": f, "Semaines complètes": len(x), "Moyenne hebdo": x.mean() if len(x) else np.nan, "rebut_an": None,
                           "Note": "moins de 2 semaines complètes : pas d'intervalle"})
            continue
        b = rng.choice(x, (n_boot, len(x))).mean(axis=1) * 52
        bas, moy, haut = float(np.quantile(b, 0.05)), float(x.mean() * 52), float(np.quantile(b, 0.95))
        lignes.append({"FRU": f, "Semaines complètes": len(x), "Moyenne hebdo": x.mean(), "Écart-type hebdo": x.std(ddof=1),
                       "Rebut annuel bas (5 %)": bas, "Rebut annuel moyen": moy, "Rebut annuel haut (95 %)": haut,
                       "rebut_an": (bas, moy, haut) if haut > bas else moy, "Note": ""})
    return pd.DataFrame(lignes)
