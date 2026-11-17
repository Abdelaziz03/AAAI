"""Classement des pièces consommées, lien avec les FRU rebutées, statistiques par couple (FRU, pièce).

Le MMICV est un coût standard : une référence provisoire, ni un prix de revente ni une valeur de réemploi.
La colonne « Valeur MICV » des extractions n'est pas utilisée : sur une ligne de plusieurs pièces, elle ne vaut pas
quantité × MMICV unitaire.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import risques
from .sources import Sources, origine

COLS_CLASSIF = ["Catégorie proposée", "Benne", "Poids unitaire (kg)", "Source poids", "Fabricant", "Nature réelle", "Niveau de preuve"]


def _joint(s):
    return ", ".join(sorted({str(x) for x in s if isinstance(x, str) and x}))


def classement(d: pd.DataFrame, src: Sources) -> pd.DataFrame:
    """Une ligne par pièce consommée dans `d` (sous-ensemble de src.ev), triée par MMICV total décroissant."""
    cols = ["Référence", "Description", "Ateliers", "Familles", "Pièces", "PO", "Jours avec sortie", "MMICV unitaire (USD)", "Source MMICV",
            "MMICV total (USD)", "Part du MMICV total", "Rang pièces", "Rang MMICV", *COLS_CLASSIF, "Kg (poids connus)", "Pièce posée"]
    if not len(d):
        return pd.DataFrame(columns=cols)
    g = d.groupby("Component ITEM").agg(Description=("Component Description", "first"), Ateliers=("Atelier", _joint), Familles=("Famille", _joint),
                                        Pièces=("Qte", "sum"), PO=("PO", "nunique"), **{"Jours avec sortie": ("Jour", "nunique")})
    g.index.name = "Référence"
    idx = g.index.to_series()
    g["MMICV unitaire (USD)"] = idx.map(src.mmicv)
    g["Source MMICV"] = idx.map(src.mmicv_source).fillna("aucune")
    g["MMICV total (USD)"] = g["Pièces"] * g["MMICV unitaire (USD)"]
    tot = g["MMICV total (USD)"].sum()
    g["Part du MMICV total"] = g["MMICV total (USD)"] / tot if tot else np.nan
    g["Rang pièces"] = g["Pièces"].rank(ascending=False, method="min").astype(int)
    g["Rang MMICV"] = g["MMICV total (USD)"].rank(ascending=False, method="min")
    for c in COLS_CLASSIF:
        g[c] = idx.map(src.classification[c]) if c in src.classification else np.nan
    g["Kg (poids connus)"] = g["Pièces"] * pd.to_numeric(g["Poids unitaire (kg)"], errors="coerce")
    g["Pièce posée"] = idx.map(origine)
    return g.sort_values(["MMICV total (USD)", "Pièces"], ascending=False).reset_index()[cols]


def calendrier(src: Sources) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Mois calendaires : jours extraits et pièces par mois. Un mois incomplet n'est jamais comparé à un chiffre mensuel."""
    if not src.couverts:
        return pd.DataFrame(columns=["Mois", "Jours extraits", "Jours du mois", "Mois complet"]), pd.DataFrame()
    jm = pd.Series(sorted(src.couverts)).dt.to_period("M").astype(str).value_counts().sort_index()
    cal = pd.DataFrame({"Mois": jm.index, "Jours extraits": jm.values})
    cal["Jours du mois"] = [pd.Period(m).days_in_month for m in cal["Mois"]]
    cal["Mois complet"] = np.where(cal["Jours extraits"].eq(cal["Jours du mois"]), "oui", "non")
    par_mois = pd.DataFrame()
    if len(src.ev):
        m = src.ev.assign(Mois=src.ev["Jour"].dt.to_period("M").astype(str))
        par_mois = m.pivot_table(index=["Atelier", "Component ITEM"], columns="Mois", values="Qte", aggfunc="sum", fill_value=0).reset_index()
    return cal, par_mois


def chiffres_a_verifier(src: Sources, chiffres: pd.DataFrame, cal: pd.DataFrame) -> pd.DataFrame:
    """Compare des chiffres annoncés (onglet « Chiffres_a_verifier ») aux pièces réellement sorties par mois complet.
    `chiffres` : Libellé, Motif (expression régulière sur la description), Atelier, Valeur par mois."""
    cols = ["Chiffre", "Annoncé par mois", "Mois", "Jours extraits", "Mois complet", "Pièces observées", "Écart", "Références"]
    if not len(chiffres) or not len(src.ev):
        return pd.DataFrame(columns=cols)
    m = src.ev.assign(Mois=src.ev["Jour"].dt.to_period("M").astype(str))
    cal_i = cal.set_index("Mois")
    lignes = []
    for _, c in chiffres.iterrows():
        if pd.isna(c.get("Motif")):
            continue
        d = m[m["Component Description"].astype(str).str.contains(str(c["Motif"]), case=False, na=False, regex=True)]
        if isinstance(c.get("Atelier"), str) and c["Atelier"]:
            d = d[d["Atelier"].eq(c["Atelier"])]
        for mois, q in d.groupby("Mois")["Qte"].sum().items():
            complet = cal_i.at[mois, "Mois complet"] if mois in cal_i.index else "non"
            annonce = pd.to_numeric(c.get("Valeur par mois"), errors="coerce")
            lignes.append({"Chiffre": c.get("Libellé"), "Annoncé par mois": annonce, "Mois": mois,
                           "Jours extraits": cal_i.at[mois, "Jours extraits"] if mois in cal_i.index else np.nan, "Mois complet": complet,
                           "Pièces observées": q, "Écart": q - annonce if complet == "oui" else np.nan,
                           "Références": ", ".join(sorted(d.loc[d["Mois"].eq(mois), "Component ITEM"].unique()))})
    return pd.DataFrame(lignes, columns=cols)


def fru_rebutees(src: Sources) -> tuple[pd.DataFrame, str]:
    """FRU rebutées par atelier et par type sur la période. Source : onglet FRU_rebutees, sinon la cohorte."""
    if len(src.fru_rebutees):
        u = src.fru_rebutees.groupby("FRU")["Unités"].sum().rename("FRU rebutées").reset_index()
        source = f"onglet FRU_rebutees des extractions ; date de rebut : {src.regle_date_rebut}"
    elif len(src.cohorte) and {"FRU ITEM", "Statut", "Unites"} <= set(src.cohorte.columns):
        co = src.cohorte[src.cohorte["Statut"].astype(str).eq("Scrapped")]
        u = co.groupby(co["FRU ITEM"].astype(str))["Unites"].sum().rename("FRU rebutées").reset_index().rename(columns={"FRU ITEM": "FRU"})
        source = "FRU_statut_cohorte (pas d'onglet FRU_rebutees) : cohorte de PO, pas un flux daté"
    else:
        return pd.DataFrame(columns=["Atelier", "FRU", "Description FRU", "FRU rebutées", "Poids FRU (kg)", "Masse rebutée (kg)"]), "aucune source de FRU rebutées"
    u["Atelier"] = u["FRU"].map(src.atelier_fru).fillna("(non rattaché)")
    u["Description FRU"] = u["FRU"].map(src.desc_fru)
    u["Poids FRU (kg)"] = u["FRU"].map(src.poids_fru)
    u["Masse rebutée (kg)"] = u["FRU rebutées"] * u["Poids FRU (kg)"]
    return u[["Atelier", "FRU", "Description FRU", "FRU rebutées", "Poids FRU (kg)", "Masse rebutée (kg)"]].sort_values("FRU rebutées", ascending=False), source


def couples_fru_piece(src: Sources) -> pd.DataFrame:
    """Statistiques par couple (FRU, pièce) tirées des consommations, base de l'a priori du modèle de Rex.

    Réparations du FRU   : nombre de PO distincts de ce type de FRU ayant consommé au moins une pièce.
    Max par PO           : plus grande quantité de la pièce consommée sur un même PO = MINIMUM du nombre de pièces par FRU.
    Part des réparations : part des PO du FRU qui ont consommé la pièce.
    """
    cols = ["FRU", "Pièce", "Description", "Atelier", "Pièces consommées", "PO avec la pièce", "Réparations du FRU", "Part des réparations",
            "Max par PO", "Pièces par PO concerné"]
    ev = src.ev.dropna(subset=["FRU ITEM"])
    if not len(ev):
        # Repli : nomenclature de consommation historique (sans PO, donc sans part ni maximum)
        if len(src.qc):
            g = src.qc.groupby(["FRU ITEM", "Component ITEM"])["Total Consumption Quantity"].sum().reset_index()
            g.columns = ["FRU", "Pièce", "Pièces consommées"]
            g["Description"] = g["Pièce"].map(src.desc_piece)
            g["Atelier"] = g["FRU"].map(src.atelier_fru)
            return g.reindex(columns=cols)
        return pd.DataFrame(columns=cols)
    par_po = ev.groupby(["FRU ITEM", "Component ITEM", "PO"], dropna=False)["Qte"].sum().reset_index()
    g = par_po.groupby(["FRU ITEM", "Component ITEM"]).agg(**{"Pièces consommées": ("Qte", "sum"), "PO avec la pièce": ("PO", "nunique"),
                                                             "Max par PO": ("Qte", "max")}).reset_index()
    n_po = ev.groupby("FRU ITEM")["PO"].nunique()
    g["Réparations du FRU"] = g["FRU ITEM"].map(n_po)
    g["Part des réparations"] = g["PO avec la pièce"] / g["Réparations du FRU"].replace(0, np.nan)
    g["Pièces par PO concerné"] = g["Pièces consommées"] / g["PO avec la pièce"].replace(0, np.nan)
    g = g.rename(columns={"FRU ITEM": "FRU", "Component ITEM": "Pièce"})
    g["Description"] = g["Pièce"].map(src.desc_piece)
    g["Atelier"] = g["FRU"].map(src.atelier_fru).fillna("(non rattaché)")
    return g[cols].sort_values(["FRU", "Pièces consommées"], ascending=[True, False]).reset_index(drop=True)


def composants_fru_rebutees(src: Sources, rebut: pd.DataFrame, couples: pd.DataFrame) -> pd.DataFrame:
    """Pièces présentes dans la nomenclature de consommation des FRU rebutées. Le nombre de pièces par FRU reste
    inconnu jusqu'à l'audit de démontage : seul le minimum observé par PO est donné."""
    cols = ["Référence", "Description", "FRU rebutées qui l'ont dans leur nomenclature", "FRU concernées", "Ateliers",
            "Pièces consommées sur la période", "MMICV unitaire (USD)", "Minimum de pièces par FRU (max observé par PO)"]
    if not len(rebut):
        return pd.DataFrame(columns=cols)
    bom = pd.concat([couples[["FRU", "Pièce"]], src.qc.rename(columns={"FRU ITEM": "FRU", "Component ITEM": "Pièce"})[["FRU", "Pièce"]]]).drop_duplicates()
    lien = rebut.merge(bom, on="FRU", how="inner")
    if not len(lien):
        return pd.DataFrame(columns=cols)
    c = lien.groupby("Pièce").agg(**{"FRU rebutées qui l'ont dans leur nomenclature": ("FRU rebutées", "sum"),
                                     "FRU concernées": ("FRU", _joint), "Ateliers": ("Atelier", _joint)}).reset_index().rename(columns={"Pièce": "Référence"})
    c["Description"] = c["Référence"].map(src.desc_piece)
    c["Pièces consommées sur la période"] = c["Référence"].map(src.ev.groupby("Component ITEM")["Qte"].sum()).fillna(0)
    c["MMICV unitaire (USD)"] = c["Référence"].map(src.mmicv)
    c["Minimum de pièces par FRU (max observé par PO)"] = c["Référence"].map(couples.groupby("Pièce")["Max par PO"].max())
    return c[cols].sort_values(["Pièces consommées sur la période", "MMICV unitaire (USD)"], ascending=False).reset_index(drop=True)


def priorisation(cl: pd.DataFrame, contenu: pd.DataFrame, fiab: pd.DataFrame | None = None) -> pd.DataFrame:
    """Critères de pré-sélection et front de Pareto (aucune pondération imposée)."""
    if not len(cl):
        return pd.DataFrame()
    rm = pd.DataFrame([risques.risque_matiere(d) for d in cl["Description"]], index=cl.index)
    rs = pd.DataFrame([risques.risque_supply(r, t) for r, t in zip(cl["Référence"].astype(str), rm["Type de pièce"])], index=cl.index)
    t = pd.concat([cl[["Référence", "Description", "Ateliers", "Pièces", "MMICV unitaire (USD)", "MMICV total (USD)", "Catégorie proposée", "Benne"]], rm, rs], axis=1)
    t["Risque supply retenu"] = t["Score risque supply (0-1)"].fillna(t["A priori supply (type)"])
    t["Source supply retenue"] = np.where(t["Score risque supply (0-1)"].notna(), "délai fourni par les achats",
                                          np.where(t["A priori supply (type)"].notna(), "a priori de type", "aucune"))
    col = "FRU rebutées qui l'ont dans leur nomenclature"
    t["FRU rebutées (nomenclature)"] = t["Référence"].map(contenu.set_index("Référence")[col]).fillna(0) if len(contenu) else np.nan
    t["Fiabilité réemploi (1/rapport)"] = np.nan
    if fiab is not None and len(fiab) and "Rapport au neuf (taux)" in fiab and fiab["Rapport au neuf (taux)"].notna().any():
        from .sources import base_ref
        r = fiab[fiab["Origine posée"].ne("Neuve")].groupby("Référence")["Rapport au neuf (taux)"].min()
        t["Fiabilité réemploi (1/rapport)"] = 1 / t["Référence"].astype(str).map(base_ref).map(r)
    criteres = ["MMICV total (USD)", "FRU rebutées (nomenclature)", "Score risque matière (0-1)", "Risque supply retenu", "Fiabilité réemploi (1/rapport)"]
    actifs = [c for c in criteres if t[c].notna().any()]
    t["Sur le front de Pareto"] = risques.front_pareto(t, actifs) if actifs else False
    t["Note (poids égaux, indicatif)"] = risques.score_pondere(t, {c: 1 for c in actifs}) if actifs else np.nan
    t.attrs["Critères actifs"] = actifs
    t.attrs["Critères inactifs faute de données"] = [c for c in criteres if c not in actifs]
    return t.sort_values(["Sur le front de Pareto", "MMICV total (USD)"], ascending=False).reset_index(drop=True)
