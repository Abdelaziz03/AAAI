"""Page de revue de la composition : la personne qui connaît les pièces y valide ou corrige les classes proposées.

    donnees(cx, tables, classes, prix, bom, ...)   ce que la page affiche, lu dans le cortex
    construire(donnees, chemin)                    page HTML autonome (aucune connexion, aucune ressource extérieure)

La page ferme la boucle du cortex. Elle montre, pour chaque pièce, la classe proposée, sa probabilité, qui dit quoi,
et ce que rapporterait de trancher. La personne choisit une classe ; la page produit le fichier
« validations_composition.csv » à déposer dans <projet>/Acquisition/. Au passage suivant, ces validations deviennent la
vérité de terrain : elles fixent la classe des pièces validées, servent d'exemples à l'analogie et mesurent ce que
vaut chaque type de source.

Deux files de travail :
    à valider   les pièces que la chaîne n'a pas su trancher, par enjeu décroissant ;
    sondage     des pièces tirées au hasard parmi celles que la chaîne ne montre à personne (acceptées ou laissées). Sans ce sondage, la fiabilité des sources ne serait mesurée que
                sur les pièces douteuses, donc sous-estimée ; c'est lui qui donne une mesure sans biais.

La page contient des références et des descriptions internes : elle reste dans le dossier, comme les autres tables.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import outil as mod_outil

ICI = Path(__file__).resolve().parent
GABARIT = ICI / "composition_gabarit.html"
MARQUE_JETONS = "/*__ERC_JETONS__*/"
MARQUE_DONNEES = "__ERC_COMPOSITION__"
FICHIER_VALIDATIONS = "validations_composition.csv"
NOM_PAGE = "ERC_Composition_Revue.html"
TAILLE_SONDAGE = 20


def _jetons() -> str:
    """Couleurs de l'outil des décideurs (clair et sombre), reprises telles quelles : une seule palette pour le dossier."""
    css = mod_outil.GABARIT.read_text(encoding="utf-8")
    debut, fin = css.index("/* Jetons de couleur"), css.index("/* Base */")
    return css[debut:fin].strip()


def _nombre(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _texte(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


def hors_file(resultat: pd.DataFrame) -> pd.Series:
    """Pièces que la chaîne ne montre à personne : acceptées, ou ni acceptées ni envoyées en revue (laissées faute d'enjeu)."""
    from .composition import REVUE
    statut = resultat["Statut"]
    if "Prochaine action" not in resultat:                     # sans la prochaine action, on ne sait pas ce qui part en revue : acceptées seules
        return statut.eq("acceptée")
    return statut.eq("acceptée") | (statut.eq("à valider") & ~resultat["Prochaine action"].astype(str).str.startswith(REVUE))


def sondage(resultat: pd.DataFrame, n: int = TAILLE_SONDAGE, graine: int = 0) -> list:
    """Pièces tirées au hasard (tirage répétable) parmi celles que la chaîne ne montre à personne : la file du contrôle
    par sondage. C'est ce tirage, et lui seul, qui mesure les sources sans biais là où personne ne regarde."""
    candidates = sorted(resultat.loc[hors_file(resultat), "PN"].astype(str))
    if len(candidates) <= n:
        return candidates
    return sorted(np.random.default_rng(graine).choice(candidates, size=n, replace=False).tolist())


def donnees(cx, tables: dict, classes, prix: dict, bom: pd.DataFrame, reglages=None, croyances: dict | None = None,
            fiabilites: pd.DataFrame | None = None, demo: bool = False, graine: int = 0) -> dict:
    """Contrat de la page. `croyances` : {PN: {classe: probabilité}} telles que la chaîne les a calculées ; à défaut,
    la probabilité de la classe retenue est la seule affichée."""
    from . import composition as C
    from . import cortex as K
    g = reglages or C.Reglages()
    res = tables.get("Composition proposée", pd.DataFrame(columns=C.COLS_RESULTAT))
    notes = dict(tables.get("Notes") or {})
    f = fiabilites if fiabilites is not None else cx.fiabilites(C.DOMAINE, C.ATTRIBUT)
    r_type = dict(zip(f["Type de source"], f["Fiabilité"])) if len(f) else {}
    preuves = {}
    for _, a in cx.affirmations(C.DOMAINE, C.ATTRIBUT).iterrows():
        try:
            detail = json.loads(a["detail"]) if isinstance(a["detail"], str) else None
        except ValueError:
            detail = None
        preuves.setdefault(str(a["sujet"]), []).append({
            "type": a["type_source"], "origine": a["origine"], "classe": a["valeur"], "affirme": bool(a["polarite"] >= 0),
            "fiabilite": _nombre(r_type.get(a["type_source"], K.FIABILITE_PAR_DEFAUT)),
            "detail": {k: v for k, v in (detail or {}).items() if isinstance(v, (str, int, float))} or None})
    validations = cx.verites(C.DOMAINE, C.ATTRIBUT)
    b = bom.drop_duplicates("PN").set_index("PN") if len(bom) else pd.DataFrame()
    pieces = []
    for _, r in res.iterrows():
        pn = str(r["PN"])
        ligne = b.loc[pn] if len(b) and pn in b.index else {}
        probas = {c: _nombre(p) for c, p in (croyances or {}).get(pn, {}).items() if _nombre(p) is not None and p > 0.005}
        pieces.append({
            "pn": pn, "description": _texte(r.get("Description")), "fabricant": _texte(ligne.get("Fabricant")),
            "reference_fabricant": _texte(ligne.get("Référence fabricant")), "fru": _texte(ligne.get("FRU")),
            "interne": bool(ligne.get("Interne")) if len(b) and pn in b.index else False,
            "classe": _texte(r.get("Classe retenue")), "probabilite": _nombre(r.get("Probabilité")), "statut": r.get("Statut"),
            "probabilites": probas or None, "enjeu": _nombre(r.get("Enjeu (€/an, borne)")), "suite": _texte(r.get("Prochaine action")),
            "appels": int(r.get("Appels au modèle") or 0), "cout": _nombre(r.get("Coût des acquisitions (€)")) or 0.0,
            "validee": validations.get(pn), "preuves": preuves.get(pn, [])})
    fiab = [{"type": x["Type de source"], "a_priori": _nombre(x["A priori (hypothèse)"]), "verifiees": int(x["Affirmations vérifiées"]),
             "justes": int(x["Justes"]), "fausses": int(x["Fausses"]), "fiabilite": _nombre(x["Fiabilité"])} for _, x in f.iterrows()]
    j = tables.get("Journal des acquisitions", pd.DataFrame())
    actions = ([{"action": k, "nombre": int(len(t)), "cout": float(t["cout"].sum())} for k, t in j.groupby("action", sort=True)]
               if len(j) else [])
    return {
        "genere_le": datetime.now().isoformat(timespec="minutes"), "demo": bool(demo),
        "fournisseurs_fictifs": bool(notes.get("fournisseurs_fictifs")),
        "nomenclature": notes.get("nomenclature"), "classes": list(classes), "prix": {c: _nombre(prix.get(c)) for c in classes},
        "seuils": {"acceptation": g.seuil_acceptation, "revue": g.cout_revue},
        "couts": {"collecte": g.cout_collecte, "lecture par le modèle": g.cout_extraction, "contrôle par le modèle": g.cout_validation,
                  "revue humaine": g.cout_revue},
        "collecteur": notes.get("collecteur"), "modele": notes.get("modele"),
        "fichier_validations": FICHIER_VALIDATIONS, "pieces": pieces, "sondage": sondage(res, graine=graine),
        "fiabilites": fiab, "actions": actions}


def construire(contenu: dict, chemin: Path, fragment: bool = False) -> Path:
    """Écrit la page de revue dans `chemin`. fragment=True : contenu seul, pour un hébergeur qui ajoute <html> et <body>."""
    chemin = Path(chemin)
    gabarit = GABARIT.read_text(encoding="utf-8")
    for marque in (MARQUE_JETONS, MARQUE_DONNEES):
        if gabarit.count(marque) != 1:
            raise ValueError(f"Gabarit de la page de revue invalide : repère {marque} attendu une fois")
    tete, corps = mod_outil._decouper(gabarit)
    tete = tete.replace(MARQUE_JETONS, _jetons())
    corps = corps.replace(MARQUE_DONNEES, mod_outil.json_integre(contenu))
    if fragment:
        titre, reste = tete.split("</title>", 1)
        page = f"{titre.strip()}</title>\n{mod_outil.TETE_FRAGMENT}\n{reste.strip()}\n{corps}\n"
    else:
        page = f"{mod_outil.TETE_COMPLETE}\n{tete}\n</head><body>\n{corps}\n</body></html>\n"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)
    return chemin
