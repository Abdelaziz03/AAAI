"""Lecture des sources, une seule fois, avec un état lisible de ce qui est présent ou absent.

Aucune source n'est obligatoire : une source absente ou illisible est notée dans `Sources.etat` et les étapes
qui en dépendent rendent des tables vides ou des valeurs « inconnu », jamais des zéros inventés.

Fichiers attendus (noms et colonnes des extractions existantes) :
  projet/ERC_R26_extraction_AAAAMMJJ_AAAAMMJJ.xlsx   Composants_jour, FRU_rebutees, FRU_statut_cohorte
  projet/Classification_matieres/ERC_Classification_Cartes_resultats.xlsx (Classification), ERC_Referentiel_Grades.xlsx (Grades)
  projet/Extraction_R26/poids_items_vwAllItems.csv, fiabilite_ELF_references_ERC.csv, poses_2022_2023_par_reference.csv
  projet/Acquisition/pesees_hebdo.csv, audit_demontage.csv
  racine/ERC_Valorisation_MICV_v1.xlsx (QueryComponents, QueryERC_Flow_In_Out), FRU_info.xlsx, Parts_DI_ULS_Data_upd(2022, 23).xlsb
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config import MOTIF_EXTRACTION, Config

F_VALO = "ERC_Valorisation_MICV_v1.xlsx"
F_FRU = "FRU_info.xlsx"
F_FIAB = "Parts_DI_ULS_Data_upd(2022, 23).xlsb"
COLS_EV = ["Jour", "PO", "FRU ITEM", "Component ITEM", "Component Description", "Qte"]


def ref(x):
    """Référence en texte propre : « 5123456.0 » → « 5123456 », vide → NaN."""
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return np.nan
    return re.sub(r"\.0$", "", str(x).strip()) or np.nan


def base_ref(r) -> str:
    """Référence sans suffixe de pièce réparée ou récupérée (-H, -U, -R, -RA)."""
    return re.sub(r"-(H|U|R|RA)$", "", str(r).strip().upper())


def origine(r) -> str:
    r = str(r).strip().upper()
    return "Récupérée" if r.endswith(("-H", "-U")) else "Réparée" if r.endswith(("-R", "-RA")) else "Neuve"


def semaine(j):
    """Lundi de la semaine ISO (Series de dates → Series de dates)."""
    j = pd.to_datetime(j)
    return (j - pd.to_timedelta(j.dt.weekday, unit="D")).dt.normalize()


@dataclass
class Sources:
    cfg: Config
    etat: list = field(default_factory=list)
    ev: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=COLS_EV + ["Atelier", "Famille"]))
    couverts: set = field(default_factory=set)
    fru_rebutees: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["Date rebut", "FRU", "Unités"]))
    regle_date_rebut: str = "aucun onglet FRU_rebutees"
    cohorte: pd.DataFrame = field(default_factory=pd.DataFrame)
    atelier_fru: dict = field(default_factory=dict)
    famille_fru: dict = field(default_factory=dict)
    classification: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(
        columns=["Catégorie proposée", "Benne", "Poids unitaire (kg)", "Source poids", "Fabricant", "Nature réelle", "Niveau de preuve"]))
    qc: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(
        columns=["FRU ITEM", "FRU Description", "Component ITEM", "Component Description", "Total Consumption Quantity", "Total value"]))
    mmicv: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    mmicv_source: pd.Series = field(default_factory=lambda: pd.Series(dtype=object))
    prix_recycleur: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    poids_fru: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    desc_fru: pd.Series = field(default_factory=lambda: pd.Series(dtype=object))
    desc_piece: pd.Series = field(default_factory=lambda: pd.Series(dtype=object))
    elf: pd.DataFrame = field(default_factory=pd.DataFrame)
    poses: pd.Series | None = None
    pesees: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["Semaine", "Flux", "Masse mesurée (kg)"]))
    audit: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["Date", "Type de FRU", "Pièce", "Pièces testées", "Pièces bonnes"]))

    @property
    def periode(self) -> str:
        if not self.couverts:
            return "aucun jour extrait"
        return f"du {min(self.couverts):%d/%m/%Y} au {max(self.couverts):%d/%m/%Y}, {len(self.couverts)} jours extraits"

    def etat_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.etat, columns=["Source", "Fichier", "État", "Lignes", "Détail", "Sert à"])

    def _note(self, source, fichier, etat, lignes=None, detail="", sert=""):
        self.etat.append({"Source": source, "Fichier": str(fichier), "État": etat, "Lignes": lignes, "Détail": detail, "Sert à": sert})


def _essayer(s: Sources, source: str, fichier: Path | None, sert: str, lecteur):
    """Exécute `lecteur()` et note l'état. Renvoie le résultat ou None."""
    if fichier is None or not Path(fichier).exists():
        s._note(source, fichier, "absent", sert=sert)
        return None
    try:
        res = lecteur()
        n = len(res) if hasattr(res, "__len__") else None
        s._note(source, Path(fichier).name, "chargé", n, sert=sert)
        return res
    except Exception as e:                                    # source illisible : notée, jamais bloquante
        s._note(source, Path(fichier).name, "erreur", detail=f"{type(e).__name__}: {e}"[:300], sert=sert)
        return None


def _csv(f, **kw):
    return pd.read_csv(f, sep=";", encoding="utf-8-sig", **kw)


def _num(s):
    return pd.to_numeric(pd.Series(s).astype(str).str.replace(",", ".", regex=False).str.replace(r"\s", "", regex=True), errors="coerce")


# --------------------------------------------------------------------------- extractions R26
def _lire_extractions(s: Sources):
    cfg = s.cfg
    fichiers = sorted(cfg.projet.glob(MOTIF_EXTRACTION), key=lambda p: p.stat().st_mtime, reverse=True) if cfg.projet else []
    morceaux, rebuts, couverts = [], [], set()
    for f in fichiers:
        try:
            m = re.search(r"(\d{8})_(\d{8})", f.stem)
            jours = set(pd.date_range(m.group(1), m.group(2)))
            x = pd.ExcelFile(f)
            if "Composants_jour" in x.sheet_names:
                d = x.parse("Composants_jour")
                d["Jour"] = pd.to_datetime(d["Jour"], errors="coerce").dt.normalize()
                morceaux.append(d[d["Jour"].isin(jours - couverts)])      # l'extraction la plus récente gagne pour chaque jour
            if "FRU_rebutees" in x.sheet_names:
                rebuts.append(x.parse("FRU_rebutees"))
            if "FRU_statut_cohorte" in x.sheet_names and not len(s.cohorte):
                s.cohorte = x.parse("FRU_statut_cohorte")
            couverts |= jours
            s._note("Extraction R26", f.name, "chargé", len(morceaux[-1]) if morceaux else 0, f"{m.group(1)} → {m.group(2)}", "consommations, FRU rebutées")
        except Exception as e:
            s._note("Extraction R26", f.name, "erreur", detail=f"{type(e).__name__}: {e}"[:300], sert="consommations, FRU rebutées")
    if not fichiers:
        s._note("Extraction R26", MOTIF_EXTRACTION, "absent", sert="consommations, FRU rebutées")
    if morceaux:
        ev = pd.concat(morceaux, ignore_index=True)
        for c in COLS_EV:
            if c not in ev:
                ev[c] = np.nan
        for c in ("Component ITEM", "FRU ITEM", "PO"):
            ev[c] = ev[c].map(ref)
        ev["Qte"] = pd.to_numeric(ev["Qte"], errors="coerce").fillna(0)
        if cfg.debut:
            ev = ev[ev["Jour"] >= pd.Timestamp(cfg.debut)]
            couverts = {j for j in couverts if j >= pd.Timestamp(cfg.debut)}
        if cfg.fin:
            ev = ev[ev["Jour"] < pd.Timestamp(cfg.fin)]
            couverts = {j for j in couverts if j < pd.Timestamp(cfg.fin)}
        s.ev = ev.dropna(subset=["Jour", "Component ITEM"]).reset_index(drop=True)
    s.couverts = couverts
    s.fru_rebutees, s.regle_date_rebut = _fru_rebutees(rebuts, cfg.col_date_rebut)
    if len(s.fru_rebutees) and couverts:
        s.fru_rebutees = s.fru_rebutees[s.fru_rebutees["Date rebut"].isin(couverts)].reset_index(drop=True)


def _fru_rebutees(morceaux: list, col_date: str | None):
    """Onglets FRU_rebutees réunis et dédoublonnés. Renvoie (lignes, règle de date utilisée).

    La colonne qui date le rebut n'est pas imposée : `col_date` si elle est donnée ; sinon la colonne de date dont le
    nom contient « scrap » ou « rebut » ; sinon la plus tardive des dates de la ligne. La règle est renvoyée pour
    être affichée et confirmée par le responsable du flux.
    """
    vide = pd.DataFrame(columns=["Date rebut", "FRU", "Unités"])
    if not morceaux:
        return vide, "aucun onglet FRU_rebutees dans les extractions"
    d = pd.concat(morceaux, ignore_index=True)
    cles = [c for c in ("PO", "FRU ITEM", "Numero de serie") if c in d]
    if cles:
        d = d.drop_duplicates(cles)
    col_fru = next((c for c in ("FRU ITEM", "ITEM", "Item") if c in d), None)
    if col_fru is None:
        return vide, "colonne FRU ITEM introuvable dans FRU_rebutees"
    dates = [c for c in d.columns if pd.api.types.is_datetime64_any_dtype(d[c])
             or (re.search(r"date|jour", str(c), re.I) and pd.to_datetime(d[c], errors="coerce").notna().any())]
    if col_date and col_date in d:
        jour, regle = pd.to_datetime(d[col_date], errors="coerce"), f"colonne « {col_date} » (choisie)"
    elif not dates:
        return vide, "aucune colonne de date dans FRU_rebutees : renseigner col_date_rebut"
    else:
        nommee = next((c for c in dates if re.search(r"scrap|rebut", str(c), re.I)), None)
        if nommee:
            jour, regle = pd.to_datetime(d[nommee], errors="coerce"), f"colonne « {nommee} » (trouvée par son nom)"
        else:
            jour = pd.concat([pd.to_datetime(d[c], errors="coerce") for c in dates], axis=1).max(axis=1)
            regle = "plus tardive des dates de la ligne (" + ", ".join(map(str, dates)) + ") : à confirmer"
    col_q = next((c for c in ("Unites", "Unités", "Qte", "Quantity") if c in d), None)
    out = pd.DataFrame({"Date rebut": jour.dt.normalize(), "FRU": d[col_fru].map(ref),
                        "Unités": pd.to_numeric(d[col_q], errors="coerce").fillna(1) if col_q else 1.0})
    for c in ("PO", "Numero de serie"):
        if c in d:
            out[c] = d[c].values
    return out.dropna(subset=["Date rebut", "FRU"]).reset_index(drop=True), regle


# --------------------------------------------------------------------------- fiabilité (fichier volumineux, cache)
def _lire_xlsb(fichier: Path, feuille: str, colonne_cle: str, garder: set) -> pd.DataFrame:
    from pyxlsb import open_workbook
    lignes, entete = [], None
    with open_workbook(str(fichier)) as wb:
        with wb.get_sheet(feuille) as sh:
            for row in sh.rows():
                v = [c.v for c in row]
                if entete is None:
                    if colonne_cle in v:
                        entete = v
                    continue
                d = dict(zip(entete, v))
                if any(base_ref(ref(d.get(c))) in garder for c in entete if c and str(c).endswith(("part_no", "PN", "UPN"))):
                    lignes.append(d)
    return pd.DataFrame(lignes)


def _lire_fiabilite(s: Sources):
    cfg = s.cfg
    d_sql = cfg.projet / "Extraction_R26"
    cache, cache_refs = d_sql / "fiabilite_ELF_references_ERC.csv", d_sql / "fiabilite_ELF_references_ERC.refs.txt"
    nos_refs = {base_ref(r) for r in set(s.ev["Component ITEM"].dropna()) | set(s.ev["FRU ITEM"].dropna()) | set(s.classification.index)}
    deja = set(cache_refs.read_text(encoding="utf-8").split()) if cache_refs.is_file() else None
    xlsb = cfg.racine / F_FIAB if cfg.racine else None
    a_jour = cache.is_file() and (deja is None or nos_refs <= deja)
    if cache.is_file() and (a_jour or xlsb is None or not xlsb.is_file()):
        elf = _essayer(s, "Fiabilité (cache)", cache, "défaillances précoces par référence", lambda: _csv(cache, dtype=str))
        if elf is not None and not a_jour:
            s.etat[-1]["Détail"] = "cache antérieur aux dernières références : le fichier .xlsb est absent, cache utilisé tel quel"
    elif xlsb is not None and xlsb.is_file():
        def lire():
            e = _lire_xlsb(xlsb, "Parts from ELF (2022, 23)", "failed_part_no", nos_refs)
            d_sql.mkdir(parents=True, exist_ok=True)
            e.to_csv(cache, sep=";", index=False, encoding="utf-8-sig")
            cache_refs.write_text(" ".join(sorted(nos_refs)), encoding="utf-8")
            return e
        elf = _essayer(s, "Fiabilité (.xlsb, première lecture longue)", xlsb, "défaillances précoces par référence", lire)
    else:
        s._note("Fiabilité", F_FIAB, "absent", sert="défaillances précoces par référence")
        elf = None
    if elf is not None and "replacement_part_no" in elf:
        s.elf = elf
    f = d_sql / "poses_2022_2023_par_reference.csv"

    def lire_poses():
        p = _csv(f, dtype={"Référence": str})
        p["Référence"] = p["Référence"].map(lambda r: base_ref(ref(r)))
        return _num(p["Pièces posées"]).groupby([p["Référence"], p["Origine"].astype(str)]).sum()
    s.poses = _essayer(s, "Pièces posées 2022-2023", f, "dénominateur du taux de défaillance", lire_poses)


# --------------------------------------------------------------------------- lecture complète
def charger(cfg: Config) -> Sources:
    s = Sources(cfg)
    _lire_extractions(s)
    p, r = cfg.projet, cfg.racine

    # FRU → atelier et famille
    f = r / F_FRU if r else None
    fi = _essayer(s, "FRU_info", f, "atelier et famille de chaque FRU", lambda: pd.read_excel(f))
    if fi is not None and "Item" in fi:
        fi["Item"] = fi["Item"].map(ref)
        fi = fi.dropna(subset=["Item"]).drop_duplicates("Item").set_index("Item")
        s.atelier_fru = fi["workshop"].dropna().to_dict() if "workshop" in fi else {}
        s.famille_fru = fi["category"].dropna().to_dict() if "category" in fi else {}

    # Classement matière : catégorie, benne, poids
    f = p / "Classification_matieres" / "ERC_Classification_Cartes_resultats.xlsx" if p else None
    cl = _essayer(s, "Classification matières", f, "type de déchet, benne, poids unitaire",
                  lambda: pd.read_excel(f, sheet_name="Classification", dtype={"Référence": str}))
    if cl is not None and "Référence" in cl:
        cl["Référence"] = cl["Référence"].map(ref)
        cl = cl.dropna(subset=["Référence"]).drop_duplicates("Référence").set_index("Référence")
        for c in s.classification.columns:
            if c not in cl:
                cl[c] = np.nan
        cl["Poids unitaire (kg)"] = pd.to_numeric(cl["Poids unitaire (kg)"], errors="coerce")
        cl.loc[cl["Poids unitaire (kg)"].le(0), "Poids unitaire (kg)"] = np.nan      # un poids nul est un poids inconnu
        s.classification = cl
    f = p / "Classification_matieres" / "ERC_Referentiel_Grades.xlsx" if p else None
    gr = _essayer(s, "Référentiel des grades", f, "prix recycleur par catégorie", lambda: pd.read_excel(f, sheet_name="Grades"))
    if gr is not None and {"Catégorie", "Prix recycleur (€/kg)"} <= set(gr.columns):
        s.prix_recycleur = pd.to_numeric(gr.set_index("Catégorie")["Prix recycleur (€/kg)"], errors="coerce").dropna()

    # Valorisation : nomenclature de consommation, MMICV de repli, poids et description des FRU
    f = r / F_VALO if r else None
    qc = _essayer(s, "QueryComponents", f, "nomenclature de consommation, MMICV de repli", lambda: pd.read_excel(f, sheet_name="QueryComponents"))
    mmicv_qc = pd.Series(dtype=float)
    if qc is not None and {"FRU ITEM", "Component ITEM"} <= set(qc.columns):
        for c in ("FRU ITEM", "Component ITEM"):
            qc[c] = qc[c].map(ref)
        qc = qc[qc["FRU ITEM"].notna() & qc["FRU ITEM"].astype(str).str.upper().ne("TOTAL")]
        for c in s.qc.columns:
            if c not in qc:
                qc[c] = np.nan
        s.qc = qc
        v = qc.groupby("Component ITEM").agg(v=("Total value", "sum"), q=("Total Consumption Quantity", "sum"))
        mmicv_qc = (v["v"] / v["q"].where(v["q"] > 0)).dropna()
        mmicv_qc = mmicv_qc[mmicv_qc.gt(0)]
        s.desc_fru = qc.drop_duplicates("FRU ITEM").set_index("FRU ITEM")["FRU Description"]
    fx = _essayer(s, "QueryERC_Flow_In_Out", f, "poids et description des FRU", lambda: pd.read_excel(f, sheet_name="QueryERC_Flow_In_Out"))
    if fx is not None and "ITEM" in fx:
        fx["ITEM"] = fx["ITEM"].map(ref)
        fx = fx.dropna(subset=["ITEM"]).drop_duplicates("ITEM").set_index("ITEM")
        if "Net weight" in fx:
            w = pd.to_numeric(fx["Net weight"], errors="coerce")
            s.poids_fru = w[w.gt(0)]
        if "ITEM Description" in fx:
            s.desc_fru = fx["ITEM Description"].dropna().combine_first(s.desc_fru)

    # MMICV : fiche article d'abord, QueryComponents sinon ; une valeur nulle est une valeur absente
    f = p / "Extraction_R26" / "poids_items_vwAllItems.csv" if p else None
    pi = _essayer(s, "Fiche article (vwAllItems)", f, "MMICV unitaire (coût standard)", lambda: _csv(f))
    mm = pd.Series(dtype=float)
    if pi is not None and {"ITEM", "MMICV USD"} <= set(pi.columns):
        mm = _num(pi["MMICV USD"]).groupby(pi["ITEM"].map(ref).values).first()
        mm = mm[mm.gt(0)]
    s.mmicv = mm.combine_first(mmicv_qc)
    s.mmicv_source = pd.Series(np.where(s.mmicv.index.isin(mm.index), "fiche article", "QueryComponents"), index=s.mmicv.index, dtype=object)

    # Descriptions des pièces, atelier et famille sur chaque consommation
    d1 = s.ev.dropna(subset=["Component Description"]).drop_duplicates("Component ITEM").set_index("Component ITEM")["Component Description"]
    d2 = s.qc.dropna(subset=["Component Description"]).drop_duplicates("Component ITEM").set_index("Component ITEM")["Component Description"]
    s.desc_piece = d1.combine_first(d2)
    s.ev["Atelier"] = s.ev["FRU ITEM"].map(s.atelier_fru).fillna("(non rattaché)")
    s.ev["Famille"] = s.ev["FRU ITEM"].map(s.famille_fru).fillna("")

    _lire_fiabilite(s)

    # Terrain : pesées hebdomadaires et audit de démontage
    f = p / "Acquisition" / "pesees_hebdo.csv" if p else None
    pe = _essayer(s, "Pesées hebdomadaires", f, "masse mesurée par semaine et par flux", lambda: _csv(f, dtype=str))
    if pe is not None and {"Semaine", "Flux", "Masse mesurée (kg)"} <= set(pe.columns):
        pe["Masse mesurée (kg)"] = _num(pe["Masse mesurée (kg)"]).values
        if "Incertitude mesure (kg)" in pe:
            pe["Incertitude mesure (kg)"] = _num(pe["Incertitude mesure (kg)"]).values
        pe["Semaine"] = pd.to_datetime(pe["Semaine"], dayfirst=True, errors="coerce")
        s.pesees = pe.dropna(subset=["Semaine", "Masse mesurée (kg)"])
    f = p / "Acquisition" / "audit_demontage.csv" if p else None
    au = _essayer(s, "Audit de démontage", f, "pièces testées et pièces bonnes (modèle de Rex)", lambda: _csv(f, dtype=str))
    if au is not None and set(s.audit.columns) <= set(au.columns):
        au["Date"] = pd.to_datetime(au["Date"], dayfirst=True, errors="coerce")
        for c in ("Pièces testées", "Pièces bonnes"):
            au[c] = _num(au[c]).values
        for c in ("Type de FRU", "Pièce"):
            au[c] = au[c].map(ref)
        au = au.dropna(subset=["Date", "Type de FRU", "Pièce", "Pièces testées", "Pièces bonnes"])
        s.audit = au[(au["Pièces testées"] > 0) & (au["Pièces bonnes"] >= 0) & (au["Pièces bonnes"] <= au["Pièces testées"])]
    return s
