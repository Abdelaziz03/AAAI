"""Outil des décideurs : page HTML autonome construite à partir des données de la synthèse.

    construire(donnees, chemin)                  page complète, à ouvrir dans un navigateur (aucune connexion nécessaire)
    construire(donnees, chemin, fragment=True)   même contenu sans <html>/<head>/<body>, pour un hébergeur qui les ajoute

La page est faite de trois morceaux réunis en un seul fichier :
    outil_gabarit.html   la mise en page, les styles et le code d'affichage
    outil_modele.js      le modèle de la ligne (portage de erc/ligne.py), qui recalcule dans le navigateur
    les données          le contrat produit par erc.etapes.donnees_outil, inséré en JSON

Aucune ressource extérieure : ni police, ni script, ni image distante. Bibliothèque standard seulement.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ICI = Path(__file__).resolve().parent
GABARIT = ICI / "outil_gabarit.html"
MODELE = ICI / "outil_modele.js"
MARQUE_MODELE = "/*__ERC_MODELE__*/"
MARQUE_DONNEES = "__ERC_DONNEES__"
TETE_COMPLETE = ('<!doctype html><html lang="fr"><head><meta charset="utf-8">'
                 '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">')
TETE_FRAGMENT = '<meta name="claude:viewport-fit-sides" content="cover">'


def _propre(o):
    """Rend l'objet écrivable en JSON strict : NaN et infini deviennent null (inconnu), tuples et ensembles des listes."""
    if o is None or isinstance(o, (str, bool, int)):
        return o
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {str(k): _propre(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_propre(v) for v in o]
    valeur = getattr(o, "item", None)                          # scalaire numpy : sa valeur Python
    if callable(valeur):
        try:
            v = valeur()
            if v is None or isinstance(v, (str, bool, int, float)):
                return _propre(v)
        except (TypeError, ValueError):
            pass
    return str(o)                                              # date, chemin : son texte


def json_integre(donnees) -> str:
    """JSON des données, sûr à l'intérieur d'une balise <script> : « </ » et « <!-- » ne peuvent pas la refermer."""
    texte = json.dumps(_propre(donnees), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return (texte.replace("</", "<\\/").replace("<!--", "<\\u0021--")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _decouper(gabarit: str) -> tuple[str, str]:
    """(contenu de <head> sans les balises meta de base, contenu de <body>) du gabarit."""
    for balise in ("<head>", "</head>", "<body>", "</body>"):
        if gabarit.count(balise) != 1:
            raise ValueError(f"Gabarit de l'outil invalide : {balise} attendu une fois, trouvé {gabarit.count(balise)}")
    tete = gabarit.split("<head>", 1)[1].split("</head>", 1)[0]
    corps = gabarit.split("<body>", 1)[1].split("</body>", 1)[0]
    lignes = [ligne for ligne in tete.splitlines() if not ligne.strip().startswith("<meta ")]
    return "\n".join(lignes).strip(), corps.strip()


def construire(donnees: dict, chemin: Path, fragment: bool = False) -> Path:
    """Écrit l'outil des décideurs dans `chemin` et renvoie ce chemin.

    donnees  : contrat de erc.etapes.donnees_outil (dictionnaire écrivable en JSON)
    fragment : False = document complet ; True = contenu seul, commençant par <title>, pour un hébergeur
    """
    chemin = Path(chemin)
    gabarit = GABARIT.read_text(encoding="utf-8")
    modele = MODELE.read_text(encoding="utf-8")
    for marque in (MARQUE_MODELE, MARQUE_DONNEES):
        if gabarit.count(marque) != 1:
            raise ValueError(f"Gabarit de l'outil invalide : repère {marque} attendu une fois")
    if "</script" in modele.lower():
        raise ValueError("outil_modele.js ne doit pas contenir « </script »")
    tete, corps = _decouper(gabarit)
    corps = corps.replace(MARQUE_MODELE, modele.strip()).replace(MARQUE_DONNEES, json_integre(donnees))
    if fragment:
        titre, reste = tete.split("</title>", 1)
        page = f"{titre.strip()}</title>\n{TETE_FRAGMENT}\n{reste.strip()}\n{corps}\n"
    else:
        page = f"{TETE_COMPLETE}\n{tete}\n</head><body>\n{corps}\n</body></html>\n"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", encoding="utf-8", newline="\n") as f:       # mêmes octets sous Windows et ailleurs
        f.write(page)
    return chemin
