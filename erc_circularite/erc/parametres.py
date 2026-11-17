"""Classeur des paramètres saisis (parametres/ERC_Parametres.xlsx) : gabarit, lecture, résolution.

Le pipeline crée le gabarit au premier lancement, pré-rempli avec les FRU rebutées et leurs pièces trouvées dans
les données. Il ne le réécrit jamais ensuite : ce que l'utilisateur saisit est à lui.

Une cellule de paramètre accepte :
    un nombre                  45        ou  0,35
    une plage                  30|70     (bas|haut, tirage uniforme)
    un triangle                30|45|70  (bas|mode|haut)
    vide                       inconnu ; le pipeline cherche une valeur dans les données, sinon la laisse inconnue

`resoudre` assemble les paramètres effectifs du modèle de ligne et garde la provenance de chaque valeur :
« saisi », « auto : <source> » ou « manquant ». Une valeur manquante n'est jamais remplacée par zéro.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import ligne as mod_ligne
from .config import Config
from .risques import type_piece
from .sources import Sources, ref

CARCASSE = "CARCASSE"

# paramètre : (libellé, unité, à demander à)
P_LIGNE = {
    "cout_installation_eur": ("Investissement d'installation de la ligne (postes, outillage antistatique, banc de test)", "€", "Méthodes, devis fournisseurs"),
    "amortissement_ans": ("Durée d'amortissement de l'installation", "ans", "Finance"),
    "couts_fixes_annuels_eur": ("Coûts fixes annuels de la ligne (place, encadrement, étalonnage)", "€/an", "Responsables d'atelier, finance"),
    "heures_operateur_an": ("Heures opérateur disponibles par an, hors plan de charge", "h/an", "Responsables d'atelier"),
    "taux_horaire_eur": ("Coût horaire d'un opérateur hors plan de charge (défaut de tous les FRU)", "€/h", "Responsables d'atelier"),
    "cout_traitement_eur_kg": ("Coût de traitement du recycleur actuel (0 si gratuit, négatif s'il paie)", "€/kg", "Responsable déchets, contrat actuel"),
    "valeur_reemploi_frac": ("Valeur d'une pièce réemployée, en fraction du MMICV (défaut des pièces sans valeur saisie)", "0 à 1", "Finance supply chain"),
    "valeur_semaine_eur": ("Valeur d'une semaine de délai d'approvisionnement évitée (défaut de toutes les pièces)", "€/semaine", "Achats, service"),
    "taux_change_mmicv": ("Conversion du MMICV vers l'euro (1 si le MMICV est déjà en euros)", "€ par unité de MMICV", "Finance"),
}
P_FRU = {
    "rebut_an": ("FRU rebutées par an (vide = tiré du suivi hebdomadaire)", "Suivi hebdomadaire du flux"),
    "poids_fru_kg": ("Poids du FRU (vide = fiche du FRU)", "Pesée"),
    "ouverture_min": ("Ouverture soignée du FRU, pour extraire des pièces à réemployer (minutes)", "Audit de démontage chronométré"),
    "ouverture_tri_min": ("Ouverture sommaire du FRU, pour trier seulement (minutes)", "Audit de démontage chronométré"),
    "taux_horaire_eur": ("Coût horaire propre à ce FRU (vide = défaut de la ligne)", "Responsables d'atelier"),
    "facteur_rebut": ("Facteur ≥ 1 : pièces plus souvent défectueuses dans un FRU rebuté que dans un FRU réparé", "Audit de démontage"),
}
P_PIECE = {
    "n_par_fru": ("Exemplaires de la pièce dans un FRU (vide = maximum observé sur un même PO)", "Audit de démontage, nomenclature"),
    "extraction_min": ("Extraction d'un exemplaire (minutes)", "Audit de démontage chronométré"),
    "test_min": ("Test d'un exemplaire (minutes)", "Audit de démontage chronométré, qualité"),
    "tri_min": ("Tri d'un exemplaire vers son flux de recyclage (minutes)", "Audit de démontage chronométré"),
    "poids_kg": ("Poids d'un exemplaire (vide = classement matière)", "Pesée"),
    "prix_recycleur_eur_kg": ("Prix payé par le recycleur acheteur (vide = référentiel des grades)", "Consultation des recycleurs"),
    "valeur_eur": ("Valeur d'une pièce réemployée (vide = MMICV × fraction de la ligne)", "Finance supply chain"),
    "delai_semaines": ("Délai d'approvisionnement de la pièce neuve (vide = onglet Supply)", "Achats"),
    "valeur_semaine_eur": ("Valeur d'une semaine de délai évitée (vide = défaut de la ligne)", "Achats, service"),
    "transport_eur": ("Transport par pièce réemployée", "Logistique, registre des partenaires"),
    "part_preventive": ("Part des remplacements faits par précaution sur une pièce saine (0 à 1)", "Techniciens, audit"),
    "casse_demontage": ("Part des pièces cassées au démontage (0 à 1)", "Audit de démontage"),
    "rendement_test": ("Part des pièces saines qui passent le test (0 à 1)", "Audit de démontage, qualité"),
    "p_reutilisable": ("Probabilité qu'un exemplaire extrait soit réutilisable (vide = modèle de Rex)", "Audit de démontage"),
}
INFO_FRU = ["FRU", "Description", "Atelier", "FRU rebutées (période)", "Réparations (période)"]
INFO_PIECE = ["FRU", "Pièce", "Description", "Type de pièce", "Pièces consommées (période)", "Max par PO"]


def plage(x):
    """Cellule → None, nombre, (bas, haut) ou (bas, mode, haut)."""
    if x is None or (not isinstance(x, (str, tuple, list)) and pd.isna(x)):
        return None
    if isinstance(x, (tuple, list)):
        v = [float(a) for a in x]
    elif isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    else:
        t = str(x).strip().replace(",", ".").replace(" ", "").replace(" ", "")
        if not t:
            return None
        try:
            v = [float(a) for a in t.split("|")]
        except ValueError:
            return None
    if len(v) == 1:
        return v[0]
    if len(v) not in (2, 3):
        return None
    v = sorted(v) if len(v) == 2 else [min(v), v[1], max(v)]
    if len(v) == 3 and not (v[0] <= v[1] <= v[2]):
        v[1] = float(np.clip(v[1], v[0], v[2]))
    return v[0] if v[0] == v[-1] else tuple(v)


def nul(v):
    """Inconnu : None ou NaN (une cellule vide relue par pandas)."""
    return v is None or (isinstance(v, (float, np.floating)) and np.isnan(v))


def milieu(v):
    if nul(v):
        return None
    if isinstance(v, tuple):
        return float(np.mean(v)) if len(v) == 2 else float(v[1])
    return v


def milieu_ou_plage(v):
    """La valeur telle qu'elle a été saisie (nombre ou plage), ou None si la cellule est vide."""
    return None if nul(v) else v


def bornes(v):
    """(bas, central, haut) d'une valeur ou d'une plage ; None si inconnue."""
    if nul(v):
        return None
    if isinstance(v, tuple):
        return (float(v[0]), float(milieu(v)), float(v[-1]))
    return (float(v), float(v), float(v))


def produit(a, b):
    """Produit de deux grandeurs positives, plages comprises (bas×bas, mode×mode, haut×haut)."""
    if nul(a) or nul(b):
        return None
    if not isinstance(a, tuple) and not isinstance(b, tuple):
        return float(a) * float(b)
    ba, bb = bornes(a), bornes(b)
    v = tuple(x * y for x, y in zip(ba, bb))
    return v[0] if v[0] == v[2] else v


def texte(v) -> str:
    if nul(v):
        return ""
    if isinstance(v, tuple):
        return " | ".join(f"{x:g}" for x in v)
    return f"{v:g}"


@dataclass
class Parametres:
    existe: bool = False
    ligne: dict = field(default_factory=dict)                      # paramètre → valeur ou plage
    ligne_source: dict = field(default_factory=dict)
    fru: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=INFO_FRU + list(P_FRU) + ["Source"]))
    pieces: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=INFO_PIECE + list(P_PIECE) + ["Source"]))
    supply: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["Référence", "Délai (semaines)", "Source"]))
    ateliers: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["FRU", "Atelier"]))
    chiffres: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["Libellé", "Motif", "Atelier", "Valeur par mois"]))


# --------------------------------------------------------------------------- gabarit
def tables_gabarit(cfg: Config, src: Sources, rebut: pd.DataFrame, couples: pd.DataFrame, cl_tous: pd.DataFrame) -> dict:
    """Contenu du gabarit : les FRU rebutées des ateliers prioritaires et, pour chacun, ses pièces de plus forte valeur."""
    r = rebut[rebut["Atelier"].isin(cfg.ateliers_prioritaires)] if len(rebut) else rebut
    if not len(r):
        r = rebut
    r = r.sort_values("FRU rebutées", ascending=False).head(cfg.n_fru_gabarit)
    n_po = couples.drop_duplicates("FRU").set_index("FRU")["Réparations du FRU"] if len(couples) else pd.Series(dtype=float)
    fru = pd.DataFrame({"FRU": r["FRU"].values, "Description": r["Description FRU"].values, "Atelier": r["Atelier"].values,
                        "FRU rebutées (période)": r["FRU rebutées"].values, "Réparations (période)": r["FRU"].map(n_po).values})
    for c in list(P_FRU) + ["Source"]:
        fru[c] = None
    lignes = []
    for f in fru["FRU"]:
        c = couples[couples["FRU"].eq(f)].copy()
        c["v"] = c["Pièces consommées"] * c["Pièce"].map(src.mmicv).fillna(0)
        for _, p in c.sort_values(["v", "Pièces consommées"], ascending=False).head(cfg.n_pieces_gabarit).iterrows():
            lignes.append({"FRU": f, "Pièce": p["Pièce"], "Description": p["Description"], "Type de pièce": type_piece(p["Description"]),
                           "Pièces consommées (période)": p["Pièces consommées"], "Max par PO": p["Max par PO"]})
        lignes.append({"FRU": f, "Pièce": CARCASSE, "Description": "Châssis et reste du FRU : recyclage seulement", "Type de pièce": "Carcasse"})
    pieces = pd.DataFrame(lignes, columns=INFO_PIECE)
    for c in list(P_PIECE) + ["Source"]:
        pieces[c] = None
    ligne = pd.DataFrame([{"Paramètre": k, "Libellé": v[0], "Unité": v[1], "Valeur": 5 if k == "amortissement_ans" else None,
                           "Source": "défaut modifiable" if k == "amortissement_ans" else None, "À demander à": v[2]} for k, v in P_LIGNE.items()])
    refs = pieces.loc[pieces["Pièce"].ne(CARCASSE), ["Pièce", "Description"]].drop_duplicates("Pièce").rename(columns={"Pièce": "Référence"})
    supply = refs.assign(**{"Délai (semaines)": None, "Source": None})
    non_ratt = sorted(set(src.ev.loc[src.ev["Atelier"].eq("(non rattaché)"), "FRU ITEM"].dropna())) if len(src.ev) else []
    lisez = pd.DataFrame([
        ("Rôle", "Paramètres que les données ne contiennent pas : temps, coûts, prix, délais. Le calcul lit ce classeur à chaque exécution et ne le réécrit jamais."),
        ("Cellule", "Un nombre (45), une plage bas|haut (30|70) ou un triangle bas|mode|haut (30|45|70). Vide = inconnu."),
        ("Colonnes grises", "Informations tirées des données, pour repère. Ne pas modifier FRU, Pièce, Paramètre ni Référence : ce sont les clés qui relient chaque ligne aux données."),
        ("Colonnes jaunes", "À saisir. Une cellule vide est cherchée dans les données (poids, prix du référentiel, MMICV) puis laissée inconnue."),
        ("Source", "Notez d'où vient chaque valeur (devis, audit du JJ/MM, personne). Elle suit la valeur jusqu'à l'outil des décideurs."),
        ("Ligne", "Paramètres de la ligne de démontage et de tri, et valeurs par défaut."),
        ("FRU", "Un FRU rebuté par ligne. Retirer une ligne l'exclut du modèle ; en ajouter une l'y fait entrer."),
        ("Pieces", f"Les pièces de chaque FRU. La ligne {CARCASSE} représente le châssis : poids, prix au kilo et temps de tri seulement."),
        ("Supply", "Délai d'approvisionnement par référence (achats)."),
        ("Ateliers", "Rattachement manuel d'un FRU à un atelier quand FRU_info ne le donne pas."),
        ("Chiffres_a_verifier", "Chiffres annoncés à comparer aux extractions : libellé, motif cherché dans la description, atelier, valeur par mois."),
    ], columns=["Élément", "Mode d'emploi"])
    return {"Lisez_moi": lisez, "Ligne": ligne, "FRU": fru, "Pieces": pieces, "Supply": supply,
            "Ateliers": pd.DataFrame({"FRU": non_ratt, "Atelier": [None] * len(non_ratt)}),
            "Chiffres_a_verifier": pd.DataFrame(columns=["Libellé", "Motif", "Atelier", "Valeur par mois"])}


def ecrire_classeur(chemin, tables: dict) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    chemin.parent.mkdir(parents=True, exist_ok=True)
    saisie = {"Ligne": ["Valeur", "Source"], "FRU": list(P_FRU) + ["Source"], "Pieces": list(P_PIECE) + ["Source"],
              "Supply": ["Délai (semaines)", "Source"], "Ateliers": ["Atelier"], "Chiffres_a_verifier": ["Libellé", "Motif", "Atelier", "Valeur par mois"]}
    aide = {**{k: v[0] for k, v in P_FRU.items()}, **{k: v[0] for k, v in P_PIECE.items()}}
    with pd.ExcelWriter(chemin, engine="openpyxl") as w:
        for nom, d in tables.items():
            d.to_excel(w, sheet_name=nom, index=False)
            ws = w.sheets[nom]
            ws.freeze_panes = "C2" if nom in ("FRU", "Pieces") else "A2"
            for i, c in enumerate(d.columns, 1):
                cel = ws.cell(1, i)
                a_saisir = c in saisie.get(nom, [])
                cel.font = Font(bold=True, color="FFFFFF")
                cel.fill = PatternFill("solid", fgColor="1F4E79" if a_saisir else "7F7F7F")
                cel.alignment = Alignment(wrap_text=True, vertical="top")
                largeur = max([len(str(c))] + [len(str(v)) for v in d[c].head(300) if v is not None]) + 2
                ws.column_dimensions[cel.column_letter].width = min(max(largeur, 12), 70)
                if nom != "Lisez_moi":
                    for r in range(2, len(d) + 2):
                        ws.cell(r, i).fill = PatternFill("solid", fgColor="FFF8DC" if a_saisir else "EDEDED")
                if c in aide:
                    from openpyxl.comments import Comment
                    cel.comment = Comment(aide[c], "ERC")


def creer_gabarit(cfg: Config, src: Sources, rebut, couples, cl_tous) -> bool:
    """Crée le classeur s'il n'existe pas. Renvoie True s'il vient d'être créé."""
    if cfg.classeur.is_file():
        return False
    ecrire_classeur(cfg.classeur, tables_gabarit(cfg, src, rebut, couples, cl_tous))
    return True


# --------------------------------------------------------------------------- lecture
def lire(cfg: Config) -> Parametres:
    p = Parametres()
    if not cfg.classeur.is_file():
        return p
    try:
        x = pd.read_excel(cfg.classeur, sheet_name=None, dtype=object)
    except Exception:
        return p
    p.existe = True
    if "Ligne" in x and {"Paramètre", "Valeur"} <= set(x["Ligne"].columns):
        for _, r in x["Ligne"].iterrows():
            if isinstance(r["Paramètre"], str) and r["Paramètre"] in P_LIGNE:
                p.ligne[r["Paramètre"]] = plage(r["Valeur"])
                p.ligne_source[r["Paramètre"]] = r.get("Source") if isinstance(r.get("Source"), str) else ""
    for nom, attr, cles, params in (("FRU", "fru", ["FRU"], P_FRU), ("Pieces", "pieces", ["FRU", "Pièce"], P_PIECE)):
        if nom in x and set(cles) <= set(x[nom].columns):
            d = x[nom].copy()
            for c in cles:
                d[c] = d[c].map(ref)
            d = d.dropna(subset=cles).drop_duplicates(cles)
            for c in getattr(p, attr).columns:
                if c not in d:
                    d[c] = None
            for c in params:                                   # colonne « object » : une cellule vide reste None, jamais NaN
                d[c] = pd.Series([plage(v) for v in d[c]], index=d.index, dtype=object)
            setattr(p, attr, d.reset_index(drop=True))
    if "Supply" in x and "Référence" in x["Supply"]:
        d = x["Supply"].copy()
        d["Référence"] = d["Référence"].map(ref)
        d["Délai (semaines)"] = d.get("Délai (semaines)", pd.Series(dtype=object)).map(plage).map(milieu)
        p.supply = d.dropna(subset=["Référence"])
    if "Ateliers" in x and {"FRU", "Atelier"} <= set(x["Ateliers"].columns):
        d = x["Ateliers"].copy()
        d["FRU"] = d["FRU"].map(ref)
        p.ateliers = d.dropna(subset=["FRU", "Atelier"])
    if "Chiffres_a_verifier" in x:
        p.chiffres = x["Chiffres_a_verifier"].dropna(how="all")
    return p


def appliquer_aux_sources(p: Parametres, src: Sources) -> None:
    """Rattachements manuels d'atelier et délais d'approvisionnement, avant le classement."""
    from . import risques
    if len(p.ateliers):
        src.atelier_fru.update(dict(zip(p.ateliers["FRU"], p.ateliers["Atelier"].astype(str))))
        if len(src.ev):
            src.ev["Atelier"] = src.ev["FRU ITEM"].map(src.atelier_fru).fillna("(non rattaché)")
    risques.SUPPLY.clear()
    for _, r in p.supply.iterrows():
        if r.get("Délai (semaines)") is not None and pd.notna(r.get("Délai (semaines)")):
            risques.SUPPLY[str(r["Référence"])] = {"Délai (semaines)": float(r["Délai (semaines)"]),
                                                   "Source": r.get("Source") if isinstance(r.get("Source"), str) else "classeur de paramètres"}


# --------------------------------------------------------------------------- a priori du modèle de Rex
def a_priori_rex(p: Parametres, couples: pd.DataFrame) -> pd.DataFrame:
    """q0 par (FRU, pièce) tiré de la consommation :
        p_défaut = pièces consommées × (1 − part préventive) / (réparations du FRU × pièces par FRU)
        q0 = (1 − facteur_rebut × p_défaut) × (1 − casse) × rendement du test
    Valeurs neutres quand un correctif n'est pas saisi (part préventive 0, facteur 1, casse 0, rendement 1) : signalées."""
    cols = ["Type de FRU", "Pièce", "Pièces consommées", "Réparations du FRU", "n_par_fru", "Source n_par_fru", "p_défaut", "Correctifs", "q0"]
    c = couples.set_index(["FRU", "Pièce"]) if len(couples) else pd.DataFrame()
    fac = p.fru.set_index("FRU")["facteur_rebut"].map(milieu) if len(p.fru) else pd.Series(dtype=float)
    lignes = []
    for _, r in p.pieces.iterrows():
        if r["Pièce"] == CARCASSE:
            continue
        cle = (r["FRU"], r["Pièce"])
        conso = c.at[cle, "Pièces consommées"] if len(c) and cle in c.index else np.nan
        rep = c.at[cle, "Réparations du FRU"] if len(c) and cle in c.index else np.nan
        n, src_n = milieu(r["n_par_fru"]), "saisi"
        if n is None:
            n = c.at[cle, "Max par PO"] if len(c) and cle in c.index and pd.notna(c.at[cle, "Max par PO"]) else None
            src_n = "minimum observé sur un PO, à confirmer" if n is not None else "inconnu"
        pp, ca, rt = (milieu(r[k]) for k in ("part_preventive", "casse_demontage", "rendement_test"))
        fr = fac.get(r["FRU"]) if len(fac) else None
        fr = None if fr is None or pd.isna(fr) else fr
        d = mod_ligne.p_defaut_depuis_conso(conso if pd.notna(conso) else None, rep if pd.notna(rep) else None, n, pp or 0.0)
        q0 = mod_ligne.p_reutilisable(d, fr or 1.0, ca or 0.0, 1.0 if rt is None else rt)
        neutres = [nom for nom, v in (("part préventive", pp), ("facteur rebut", fr), ("casse", ca), ("rendement du test", rt)) if v is None]
        lignes.append({"Type de FRU": r["FRU"], "Pièce": r["Pièce"], "Pièces consommées": conso, "Réparations du FRU": rep, "n_par_fru": n,
                       "Source n_par_fru": src_n, "p_défaut": d, "Correctifs": "neutres : " + ", ".join(neutres) if neutres else "tous saisis", "q0": q0})
    return pd.DataFrame(lignes, columns=cols)


# --------------------------------------------------------------------------- résolution
def resoudre(cfg: Config, p: Parametres, src: Sources, couples: pd.DataFrame, rebut_annuel: pd.DataFrame, rex_post: pd.DataFrame,
             rebut: pd.DataFrame | None = None) -> tuple[dict, dict, pd.DataFrame]:
    """Paramètres effectifs du modèle : (LIGNE, FRU_TYPES, provenance). Voir l'en-tête du module."""
    prov = []

    def note(fru, piece, param, valeur, origine_):
        valeur = None if nul(valeur) else valeur
        prov.append({"FRU": fru, "Pièce": piece, "Paramètre": param, "Valeur": texte(valeur),
                     "Provenance": origine_ if valeur is not None else "manquant"})
        return valeur

    ligne = {}
    for k in P_LIGNE:
        v = milieu_ou_plage(p.ligne.get(k))
        ligne[k] = note("(ligne)", "", k, v, "saisi" + (f" : {p.ligne_source.get(k)}" if p.ligne_source.get(k) else ""))
    change = ligne.get("taux_change_mmicv")
    frac = ligne.get("valeur_reemploi_frac")
    ra = rebut_annuel.set_index("FRU") if rebut_annuel is not None and len(rebut_annuel) else pd.DataFrame()
    post = rex_post.set_index(["Type de FRU", "Pièce"]) if rex_post is not None and len(rex_post) else pd.DataFrame()
    c = couples.set_index(["FRU", "Pièce"]) if len(couples) else pd.DataFrame()
    delais = p.supply.set_index("Référence")["Délai (semaines)"] if len(p.supply) else pd.Series(dtype=float)
    jours = len(src.couverts)
    frus = {}
    for _, f in p.fru.iterrows():
        nom = f["FRU"]
        src_f = f.get("Source") if isinstance(f.get("Source"), str) and f.get("Source").strip() else ""
        saisi_f = "saisi" + (f" : {src_f}" if src_f else "")
        d = {"description": f.get("Description") if isinstance(f.get("Description"), str) else src.desc_fru.get(nom, ""),
             "atelier": src.atelier_fru.get(nom, f.get("Atelier") if isinstance(f.get("Atelier"), str) else "")}
        # FRU rebutées par an
        v, o = milieu_ou_plage(f["rebut_an"]), saisi_f
        if v is None and len(ra) and nom in ra.index and not nul(ra.at[nom, "rebut_an"]):
            v, o = ra.at[nom, "rebut_an"], f"auto : suivi hebdomadaire ({int(ra.at[nom, 'Semaines complètes'])} semaines complètes)"
        if v is None and rebut is not None and len(rebut) and jours and nom in set(rebut["FRU"]):
            n = float(rebut.loc[rebut["FRU"].eq(nom), "FRU rebutées"].sum())
            v, o = n * 365.0 / jours, f"auto : {n:g} FRU rebutées sur {jours} jours, annualisé"
        d["rebut_an"] = note(nom, "", "rebut_an", v, o)
        v, o = milieu_ou_plage(f["poids_fru_kg"]), saisi_f
        if v is None and nom in src.poids_fru.index:
            v, o = float(src.poids_fru[nom]), "auto : fiche du FRU (Net weight)"
        d["poids_fru_kg"] = note(nom, "", "poids_fru_kg", v, o)
        for k in ("ouverture_min", "ouverture_tri_min"):
            d[k] = note(nom, "", k, milieu_ou_plage(f[k]), saisi_f)
        if d["ouverture_tri_min"] is None:
            del d["ouverture_tri_min"]                          # le modèle retombe sur l'ouverture soignée
        if not nul(f["taux_horaire_eur"]):
            d["taux_horaire_eur"] = note(nom, "", "taux_horaire_eur", f["taux_horaire_eur"], saisi_f)
        pieces, masse_pieces = {}, 0.0
        for _, r in p.pieces[p.pieces["FRU"].eq(nom)].iterrows():
            pc = r["Pièce"]
            if pc == CARCASSE:
                continue
            src_p = r.get("Source") if isinstance(r.get("Source"), str) and r.get("Source").strip() else ""
            saisi_p = "saisi" + (f" : {src_p}" if src_p else "")
            e = {"description": r.get("Description") if isinstance(r.get("Description"), str) else src.desc_piece.get(pc, "")}
            v, o = milieu_ou_plage(r["n_par_fru"]), saisi_p
            if v is None and len(c) and (nom, pc) in c.index and pd.notna(c.at[(nom, pc), "Max par PO"]):
                v, o = float(c.at[(nom, pc), "Max par PO"]), "auto : maximum observé sur un même PO (minimum, à confirmer par l'audit)"
            e["n_par_fru"] = note(nom, pc, "n_par_fru", v, o)
            for k in ("extraction_min", "test_min", "tri_min", "transport_eur"):
                e[k] = note(nom, pc, k, milieu_ou_plage(r[k]), saisi_p)
            v, o = milieu_ou_plage(r["poids_kg"]), saisi_p
            if v is None and pc in src.classification.index and pd.notna(src.classification.at[pc, "Poids unitaire (kg)"]):
                v, o = float(src.classification.at[pc, "Poids unitaire (kg)"]), f"auto : classement matière ({src.classification.at[pc, 'Source poids']})"
            e["poids_kg"] = note(nom, pc, "poids_kg", v, o)
            if e["poids_kg"] is not None and e["n_par_fru"] is not None:
                masse_pieces += milieu(e["poids_kg"]) * milieu(e["n_par_fru"])
            v, o = milieu_ou_plage(r["prix_recycleur_eur_kg"]), saisi_p
            cat = src.classification.at[pc, "Catégorie proposée"] if pc in src.classification.index else None
            if v is None and isinstance(cat, str) and cat in src.prix_recycleur.index:
                v, o = float(src.prix_recycleur[cat]), f"auto : référentiel des grades ({cat})"
            e["prix_recycleur_eur_kg"] = note(nom, pc, "prix_recycleur_eur_kg", v, o)
            v, o = milieu_ou_plage(r["valeur_eur"]), saisi_p
            if v is None and frac is not None and pc in src.mmicv.index:
                v = produit(produit(float(src.mmicv[pc]), change if change is not None else 1.0), frac)
                o = "auto : MMICV × fraction de réemploi" + ("" if change is not None else " (devise du MMICV non convertie : taux_change_mmicv à saisir)")
            e["valeur_eur"] = note(nom, pc, "valeur_eur", v, o)
            v, o = milieu_ou_plage(r["delai_semaines"]), saisi_p
            if v is None and pc in delais.index and pd.notna(delais[pc]):
                v, o = float(delais[pc]), "auto : onglet Supply"
            e["delai_semaines"] = note(nom, pc, "delai_semaines", v, o)
            v, o = milieu_ou_plage(r["valeur_semaine_eur"]), saisi_p
            if v is None and ligne.get("valeur_semaine_eur") is not None:
                v, o = ligne["valeur_semaine_eur"], "auto : défaut de la ligne"
            e["valeur_semaine_eur"] = note(nom, pc, "valeur_semaine_eur", v, o)
            v, o = milieu_ou_plage(r["p_reutilisable"]), saisi_p
            if v is None and len(post) and (nom, pc) in post.index:
                q = post.loc[(nom, pc)]
                if q["Pièces testées"] > 0 or pd.notna(q.get("q0")):
                    v = (float(q["q bas (5 %)"]), float(np.clip(q["q moyen"], q["q bas (5 %)"], q["q haut (95 %)"])), float(q["q haut (95 %)"]))
                    o = f"auto : modèle de Rex ({int(q['Pièces testées'])} pièces testées" + (", a priori de consommation)" if pd.notna(q.get("q0")) else ", sans a priori)")
            e["p_reutilisable"] = note(nom, pc, "p_reutilisable", v, o)
            pieces[pc] = e
        car = p.pieces[p.pieces["FRU"].eq(nom) & p.pieces["Pièce"].eq(CARCASSE)]
        if len(car):
            r = car.iloc[0]
            src_c = r.get("Source") if isinstance(r.get("Source"), str) and r.get("Source").strip() else ""
            saisi_c = "saisi" + (f" : {src_c}" if src_c else "")
            e = {"description": "Châssis et reste du FRU", "n_par_fru": 1.0}
            v, o = milieu_ou_plage(r["poids_kg"]), saisi_c
            if v is None and d["poids_fru_kg"] is not None and milieu(d["poids_fru_kg"]) > masse_pieces:
                v, o = milieu(d["poids_fru_kg"]) - masse_pieces, "auto : poids du FRU moins les pièces listées au poids connu"
            e["poids_kg"] = note(nom, CARCASSE, "poids_kg", v, o)
            e["prix_recycleur_eur_kg"] = note(nom, CARCASSE, "prix_recycleur_eur_kg", milieu_ou_plage(r["prix_recycleur_eur_kg"]), saisi_c)
            e["tri_min"] = note(nom, CARCASSE, "tri_min", milieu_ou_plage(r["tri_min"]), saisi_c)
            pieces[CARCASSE] = e
        d["pieces"] = pieces
        frus[nom] = d
    prov = pd.DataFrame(prov, columns=["FRU", "Pièce", "Paramètre", "Valeur", "Provenance"])
    prov["État"] = np.where(prov["Provenance"].eq("manquant"), "manquant", np.where(prov["Provenance"].astype(str).str.startswith("auto"), "tiré des données", "saisi"))
    return ligne, frus, prov


def a_obtenir(prov: pd.DataFrame, frus: dict) -> pd.DataFrame:
    """Liste de ce qu'il reste à obtenir, par paramètre, avec l'interlocuteur. Ne compte que ce qui bloque un calcul :
    les paramètres facultatifs (transport, délai, valeur d'une semaine, taux propre au FRU) ne sont pas listés."""
    facultatifs = {"transport_eur", "delai_semaines", "valeur_semaine_eur", "ouverture_tri_min", "taux_change_mmicv", "valeur_reemploi_frac"}
    qui = {**{k: v[2] for k, v in P_LIGNE.items()}, **{k: v[1] for k, v in P_FRU.items()}, **{k: v[1] for k, v in P_PIECE.items()}}
    lib = {**{k: v[0] for k, v in P_LIGNE.items()}, **{k: v[0] for k, v in P_FRU.items()}, **{k: v[0] for k, v in P_PIECE.items()}}
    m = prov[prov["État"].eq("manquant") & ~prov["Paramètre"].isin(facultatifs)]
    if not len(m):
        return pd.DataFrame(columns=["Paramètre", "Donnée", "Valeurs manquantes", "FRU concernés", "À demander à"])
    g = m.groupby("Paramètre").agg(**{"Valeurs manquantes": ("Paramètre", "size"), "FRU concernés": ("FRU", lambda s: s.nunique())}).reset_index()
    g["Donnée"] = g["Paramètre"].map(lib)
    g["À demander à"] = g["Paramètre"].map(qui)
    # Un paramètre qui existe pour la ligne et pour un FRU (taux horaire) : libellé de la ligne s'il manque à la ligne.
    de_ligne = set(m.loc[m["FRU"].eq("(ligne)"), "Paramètre"])
    for k in de_ligne & set(P_LIGNE):
        g.loc[g["Paramètre"].eq(k), "Donnée"] = P_LIGNE[k][0]
        g.loc[g["Paramètre"].eq(k), "À demander à"] = P_LIGNE[k][2]
    return g[["Paramètre", "Donnée", "Valeurs manquantes", "FRU concernés", "À demander à"]].sort_values("Valeurs manquantes", ascending=False).reset_index(drop=True)
