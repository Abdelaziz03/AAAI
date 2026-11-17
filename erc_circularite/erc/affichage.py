"""Affichage dans les notebooks : quelques fonctions courtes, pour que chaque cellule tienne en une à trois lignes.

    from erc import affichage as aff
    aff.etat(ctx)                                   bandeau : démonstration ou données réelles, période, anomalies
    aff.table(ctx, "flux", "Estimé contre pesé")    une table relue sur le disque, nombres au format français
    aff.figures(ctx, "flux")                        les figures enregistrées, chacune précédée de sa description
    aff.notes(ctx, "flux")                          les notes d'une étape (fichier JSON) en tableau lisible
    aff.manifeste(ctx)                              la liste de tous les artefacts
    aff.anomalies(ctx)                              les calculs qui ont échoué pendant l'exécution
    aff.classeur(ctx, "Lisez_moi")                  un onglet du classeur de paramètres
    aff.outil(ctx)                                  où se trouve l'outil des décideurs

Ce qui est affiché est ce qui est sur le disque : tables, notes et figures sont relues dans le dépôt des artefacts.
Une case vide est une valeur inconnue ; elle n'est jamais remplacée par zéro.
Le module ne dépend pas d'IPython : hors notebook, les fonctions renvoient des objets ordinaires (table, texte).
"""
from __future__ import annotations

import html
import json
import math
import os
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ESP = "\u00a0"                                        # espace insécable : milliers, avant % et €
LARGEUR_IMAGE = 900                                   # largeur d'affichage des figures dans un notebook (pixels)

# Colonnes qui contiennent une fraction (0,25) à lire comme un pourcentage (25 %). Liste explicite : les noms viennent
# des tables produites par erc/etapes.py ; une colonne absente de la liste est affichée comme un nombre ordinaire.
COLONNES_POURCENT = {
    "Part du MMICV total", "Part des réparations", "Part à J0 (DOA)", "Couverture poids", "Couverture poids moyenne",
    "Écart (%)", "Écart cumulé (%)", "Écart moyen (%)", "Écart cumulé final (%)", "Taux ELF moyen", "IC90 bas", "IC90 haut",
    "P(tenir la garantie)", "Taux d'occupation", "Part de pièces testées", "Couverture IC90", "Poids des données",
    "Écart absolu moyen", "Écart absolu",
}
# Colonnes de dates (dans les fichiers : AAAA-MM-JJ) affichées JJ/MM/AAAA.
COLONNES_DATE = {"Semaine", "Date", "Date rebut", "Jour"}
# Colonnes d'identifiants : gardées telles qu'elles sont écrites dans le fichier (pas de séparateur de milliers).
COLONNES_TEXTE = {"Référence", "Pièce", "FRU", "Type de FRU", "FRU ITEM", "Component ITEM", "Paramètre", "Mois"}
# Colonnes de texte qui contiennent une valeur ou une plage « bas | haut » : affichées avec la virgule décimale.
COLONNES_PLAGE = {"Valeur"}

LIBELLES_NOTES = {
    "mode": "Mode", "demo": "Démonstration", "periode": "Période", "jours_extraits": "Jours extraits", "debut": "Premier jour extrait",
    "fin": "Dernier jour extrait", "lignes_consommation": "Lignes de consommation lues", "pieces_consommees": "Pièces consommées",
    "fru_rebutees": "FRU rebutées", "regle_date_rebut": "Date retenue pour le rebut", "ateliers_prioritaires": "Ateliers prioritaires",
    "classeur_parametres": "Classeur de paramètres", "genere_le": "Généré le", "source_fru_rebutees": "Source des FRU rebutées",
    "classeur_parametres_cree": "Classeur de paramètres créé à cette exécution", "criteres_actifs": "Critères actifs",
    "criteres_inactifs": "Critères inactifs faute de données", "granularite": "Granularité du suivi", "semaines_pesees": "Semaines pesées",
    "lignes_elf": "Défaillances lues dans le fichier de fiabilité", "denominateur": "Pièces posées (dénominateur)",
    "fenetre_elf_jours": "Fenêtre d'observation (jours)", "garantie_jours": "Garantie (jours)", "lots_audit": "Lots d'audit",
    "pieces_testees": "Pièces testées", "N0": "N0 (force de l'a priori, en pièces)", "banc_essai": "Banc d'essai",
    "banc_essai_synthetique": "Banc d'essai synthétique", "resume": "Résumé", "actuel_contre_ligne": "Actuel contre ligne",
    "periode_par_periode": "Semaine par semaine", "monte_carlo": "Monte-Carlo", "types_de_fru": "Types de FRU dans le modèle",
    "types_incomplets": "Types de FRU incomplets", "chemin": "Chemin",
}
NOTES_POURCENT = {"Taux d'occupation", "P(ligne rentable)", "Part détournée"}      # fractions à lire en pourcentage dans les notes
LIBELLES_MANIFESTE = {"etape": "Étape", "type": "Type", "nom": "Nom", "fichier": "Fichier", "lignes": "Lignes", "description": "Description",
                      "genere_le": "Généré le", "donnees": "Données"}


# --------------------------------------------------------------------------- nombres
def nombre(x, decimales: int = 0, unite: str = "") -> str:
    """Nombre au format français (espace des milliers, virgule décimale) ; vide si la valeur est inconnue."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(x):
        return ""
    x = round(x, decimales)
    if x == 0:
        x = 0.0
    s = f"{abs(x):,.{decimales}f}".replace(",", ESP).replace(".", ",")
    return ("−" if x < 0 else "") + s + unite


def _decimales(s: pd.Series) -> int:
    """Nombre de décimales utile pour une colonne : aucune pour des entiers ou de grands montants, jusqu'à trois sous 1."""
    a = s.dropna().abs()
    a = a[np.isfinite(a)]
    if not len(a) or bool((a.round(0) == a).all()):
        return 0
    m = float(a.max())
    return 0 if m >= 1000 else 1 if m >= 100 else 2 if m >= 1 else 3


def _decimales_valeur(v: float) -> int:
    a = abs(float(v))
    return 0 if a >= 1000 or a == round(a) else 1 if a >= 100 else 2 if a >= 1 else 3


def _vide(v) -> bool:
    """Vrai pour une valeur inconnue (None, NaN, NaT). Une liste, même vide, n'est pas une valeur inconnue."""
    if v is None:
        return True
    if isinstance(v, (list, tuple, set, dict, np.ndarray, pd.Series, pd.DataFrame)):
        return False
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _texte(v) -> str:
    """Valeur isolée en texte lisible (notes, cellules de type mixte)."""
    if isinstance(v, (bool, np.bool_)):
        return "oui" if v else "non"
    if isinstance(v, (list, tuple, set)):
        return ", ".join(_texte(x) for x in v)
    if _vide(v):
        return ""
    if isinstance(v, (int, np.integer)):
        return nombre(v)
    if isinstance(v, (float, np.floating)):
        t = nombre(v, _decimales_valeur(v))
        return t.rstrip("0").rstrip(",") if "," in t else t
    return str(v)


_NOMBRE = re.compile(r"-?\d+(?:\.\d+)?(?:e[+-]?\d+)?")


def _plage_fr(v: str) -> str:
    """« 0.15 | 0.35 » → « 0,15 | 0,35 » : une valeur ou une plage écrite avec un point décimal, affichée avec une virgule.
    Tout autre texte est rendu tel quel."""
    morceaux = [m.strip() for m in v.split("|")]
    if not morceaux or not all(_NOMBRE.fullmatch(m) for m in morceaux):
        return v
    return " | ".join(m.replace(".", ",") for m in morceaux)


def _formater(d: pd.DataFrame, plages: bool = True):
    """Table → (table de textes prêts à afficher, colonnes numériques à aligner à droite).
    plages=False : les textes sont laissés exactement comme ils sont écrits (onglet du classeur de paramètres)."""
    out, numeriques = pd.DataFrame(index=d.index), []
    for c in d.columns:
        s, nom = d[c], str(c)
        if nom in COLONNES_DATE or pd.api.types.is_datetime64_any_dtype(s):
            with warnings.catch_warnings():                    # un texte qui n'est pas une date reste affiché tel quel, sans avertissement
                warnings.simplefilter("ignore")
                j = pd.to_datetime(s, errors="coerce")
            out[c] = [x.strftime("%d/%m/%Y") if pd.notna(x) else ("" if _vide(v) else str(v)) for x, v in zip(j, s)]
        elif pd.api.types.is_bool_dtype(s):
            out[c] = ["oui" if v else "non" for v in s]
        elif pd.api.types.is_numeric_dtype(s) and nom not in COLONNES_TEXTE:
            numeriques.append(c)
            if nom in COLONNES_POURCENT:
                f = s.astype(float)
                petits = bool(len(f.dropna())) and float(f.abs().max()) < 0.10        # tout est sous 10 % : deux décimales, sinon 0,5 % et 0,9 % se confondent
                out[c] = [nombre(v * 100, 2 if petits else 1, ESP + "%") if not _vide(v) else "" for v in f]
            else:
                f = s.astype(float)
                a = f.abs()[f.abs() > 0]
                if len(a) and a.max() >= 1000 and a.min() < 10:   # grandeurs très différentes dans la colonne : décimales valeur par valeur
                    out[c] = [nombre(v, _decimales_valeur(v)) if not _vide(v) else "" for v in f]
                else:
                    dec = _decimales(f)
                    out[c] = [nombre(v, dec) for v in f]
        elif plages and nom in COLONNES_PLAGE:
            out[c] = [_plage_fr(v) if isinstance(v, str) else _texte(v) for v in s]
        else:
            out[c] = [_texte(v) if not isinstance(v, str) else v for v in s]
    return out, numeriques


# --------------------------------------------------------------------------- table affichable
class Tableau(pd.DataFrame):
    """Table prête à afficher : dans un notebook, sans numéro de ligne, textes entiers, nombres alignés à droite,
    suivie d'une ligne qui dit combien de lignes sont montrées et de quel fichier elles viennent."""
    _metadata = ["legende", "numeriques"]

    @property
    def _constructor(self):
        return Tableau

    def _repr_html_(self):
        num = set(getattr(self, "numeriques", None) or [])
        cellule = "padding:3px 9px; vertical-align:top; "
        lignes = ['<div style="max-width:100%; overflow-x:auto">', '<table border="0" class="dataframe" style="border-collapse:collapse">', "<thead><tr>"]
        for c in self.columns:
            lignes.append(f'<th style="{cellule}text-align:{"right" if c in num else "left"}; white-space:normal; min-width:4em">{html.escape(str(c))}</th>')
        lignes.append("</tr></thead><tbody>")
        taille = {c: (max(len(str(v)) for v in self[c]) if len(self) else 0) for c in self.columns if c not in num}
        longues = {c: ("34em" if n > 160 else "18em") for c, n in taille.items() if n > 48}     # textes longs : repliés, colonne assez large
        for _, r in self.iterrows():
            lignes.append("<tr>")
            for c in self.columns:
                style = (cellule + "text-align:right; white-space:nowrap") if c in num else \
                        (cellule + f"text-align:left; white-space:normal; min-width:{longues[c]}") if c in longues else (cellule + "text-align:left; white-space:nowrap")
                lignes.append(f'<td style="{style}">{html.escape(str(r[c]))}</td>')
            lignes.append("</tr>")
        lignes.append("</tbody></table>")
        if getattr(self, "legende", None):
            lignes.append(f'<p style="font-size:85%; color:#666; margin:4px 0 10px 2px">{html.escape(str(self.legende))}</p>')
        lignes.append("</div>")
        return "\n".join(lignes)


def _tableau(d: pd.DataFrame, legende: str = "", numeriques=()) -> Tableau:
    t = Tableau(d.reset_index(drop=True))
    t.legende, t.numeriques = legende, list(numeriques)
    return t


def _relatif(ctx, chemin) -> str:
    """Chemin tel qu'on l'affiche : relatif au dossier quand le fichier s'y trouve, sinon seulement son dernier élément
    (un chemin complet peut contenir un nom de personne ou d'organisation)."""
    try:
        p = Path(str(chemin))
        base = getattr(getattr(ctx, "cfg", None), "dossier", None)
        if base is not None:
            try:
                return (Path(Path(base).name) / p.resolve().relative_to(Path(base).resolve())).as_posix()
            except ValueError:
                pass
        return "…/" + p.name if p.is_absolute() else p.as_posix()
    except Exception:
        return str(chemin)


def _est_chemin(v) -> bool:
    """Vrai pour un texte qui a la forme d'un chemin complet (« /… », « C:\\… », « \\\\serveur\\… »)."""
    return (isinstance(v, str) and len(v) > 2 and (v.startswith(("/", "\\\\")) or v[1:3] in (":\\", ":/"))
            and ("/" in v[1:] or "\\" in v[2:]) and "\n" not in v)


def _debut_execution(ctx):
    """Date et heure du début de cette exécution (texte AAAA-MM-JJTHH:MM:SS), ou None si elle n'est pas connue."""
    p = (getattr(ctx, "res", None) or {}).get("sources", {})
    p = p.get("Périmètre") if isinstance(p, dict) else None
    v = p.get("genere_le") if isinstance(p, dict) else None
    return v if isinstance(v, str) and len(v) >= 19 else None


def _perime(ctx, genere_le) -> bool:
    """Vrai si un artefact a été écrit avant le début de cette exécution : il vient d'une exécution précédente."""
    debut = _debut_execution(ctx)
    return bool(debut) and isinstance(genere_le, str) and len(genere_le) >= 19 and genere_le[:19] < debut[:19]


# --------------------------------------------------------------------------- tables
def _lire_csv(chemin: Path) -> pd.DataFrame:
    """Relit une table du dépôt (CSV « ; », virgule décimale, UTF-8 avec BOM) ; les identifiants restent du texte."""
    kw = {"sep": ";", "decimal": ",", "encoding": "utf-8-sig"}
    entetes = list(pd.read_csv(chemin, nrows=0, **kw).columns)
    return pd.read_csv(chemin, dtype={c: str for c in entetes if c in COLONNES_TEXTE}, **kw)


def table(ctx, etape: str, nom: str, n=None, colonnes=None, ou=None) -> Tableau:
    """Une table du dépôt des artefacts, relue sur le disque : ce qui s'affiche est ce qui est dans le fichier.
    Seule la présentation change : nombres et dates au format français, fractions en pourcentages, case vide pour une
    valeur inconnue, et un chemin complet réduit à son dernier élément (il peut contenir un nom de personne).

    n        : nombre de lignes affichées (défaut : option n_top de la configuration, 30) ; 0 = toutes
    colonnes : colonnes à montrer, dans cet ordre (défaut : toutes)
    ou       : filtre des lignes, {colonne: valeur ou liste de valeurs} ; exemple ou={"Flux": "DEEE"}
    """
    chemin, origine = None, ""
    try:
        chemin = ctx.depot.chemin(etape, nom)
        if chemin is not None and Path(chemin).is_file():
            d = _lire_csv(Path(chemin))
            origine = "fichier : " + _relatif(ctx, chemin)
        else:
            d = ctx.depot.lire_table(etape, nom)
            origine = "table en mémoire (fichier introuvable)"
    except PermissionError:                                   # fichier ouvert dans Excel : on montre la table en mémoire
        try:
            d = ctx.depot.lire_table(etape, nom)
            origine = "table en mémoire (fichier verrouillé, sans doute ouvert dans Excel)"
        except Exception:
            return _tableau(pd.DataFrame(), f"Table « {nom} » illisible : fichier verrouillé. Fermer le fichier puis relancer la cellule.")
    except Exception:
        return _tableau(pd.DataFrame(), f"Table « {nom} » absente de l'étape « {etape} » : relancer la première cellule du notebook, puis regarder la table des anomalies (notebook 00).")
    total, filtre = len(d), ""
    for c, v in (ou or {}).items():
        if c in d.columns:
            valeurs = list(v) if isinstance(v, (list, tuple, set)) else [v]
            d = d[d[c].astype(str).isin([str(x) for x in valeurs])]
            filtre += f" · filtre : {c} = {', '.join(str(x) for x in valeurs)}"
    retenues = len(d)
    if colonnes is not None:
        d = d[[c for c in colonnes if c in d.columns]]
    if n is None:
        n = getattr(getattr(ctx, "cfg", None), "n_top", 30) or 30
    if n and retenues > n:
        d = d.head(int(n))
        legende = f"{nombre(len(d))} premières lignes sur {nombre(retenues)}"
    else:
        legende = f"{nombre(retenues)} ligne{'s' if retenues > 1 else ''}" if retenues else "Aucune ligne"
    if filtre:
        legende += f" (table complète : {nombre(total)})" + filtre
    legende += " · " + origine
    textes, numeriques = _formater(d)
    if len(textes) and len(textes.columns) and all(str(v) == "" for c in textes.columns for v in textes[c]):
        legende += " · toutes les cases sont vides : aucune de ces valeurs n'a pu être calculée"
    for c in textes.columns:                                  # un chemin complet peut contenir un nom de personne : seul le nom du fichier est affiché
        if c not in numeriques and any(_est_chemin(v) for v in textes[c]):
            textes[c] = [_relatif(ctx, v) if _est_chemin(v) else v for v in textes[c]]
    return _tableau(textes, legende, numeriques)


def manifeste(ctx, etape: str | None = None) -> Tableau:
    """Le manifeste des artefacts, relu sur le disque : étape, type, nom, fichier, nombre de lignes, description."""
    try:
        f = Path(ctx.depot.racine) / "manifeste.json"
        contenu = json.loads(f.read_text(encoding="utf-8"))
        entrees = contenu.get("artefacts", [])
    except Exception:
        return _tableau(pd.DataFrame(), "Liste des artefacts absente : relancer la première cellule du notebook.")
    d = pd.DataFrame(entrees)
    if not len(d):
        return _tableau(pd.DataFrame(), "Manifeste vide.")
    d = d.reindex(columns=list(LIBELLES_MANIFESTE))
    present = [(Path(ctx.depot.racine) / str(x)).is_file() for x in d["fichier"]]
    absents = int(len(d) - sum(present))
    d = d[present]
    if etape:
        d = d[d["etape"].eq(etape)]
    try:
        from .config import ETAPES
        rang = {e: i for i, e in enumerate(ETAPES)}
    except Exception:
        rang = {}
    anciens = [str(n) for n, g in zip(d["nom"], d["genere_le"]) if _perime(ctx, g)]
    d = d.assign(_r=d["etape"].map(rang).fillna(99)).sort_values(["_r", "type", "nom"]).drop(columns=["_r", "genere_le", "donnees"])
    d["lignes"] = [nombre(v) for v in d["lignes"]]
    d["description"] = [_premiere_phrase(v) for v in d["description"].fillna("")]
    legende = f"{nombre(len(d))} artefacts · données : {contenu.get('donnees', 'inconnu')} · fichier : {_relatif(ctx, f)}"
    if absents:
        legende += f" · {nombre(absents)} entrée{'s' if absents > 1 else ''} d'anciennes exécutions sans fichier, non affichée{'s' if absents > 1 else ''}"
    if anciens:
        legende += (f" · {nombre(len(anciens))} fichier{'s' if len(anciens) > 1 else ''} d'une exécution précédente, non recalculé{'s' if len(anciens) > 1 else ''} cette fois : "
                    + ", ".join(anciens[:8]) + ("…" if len(anciens) > 8 else ""))
    return _tableau(d.rename(columns=LIBELLES_MANIFESTE), legende, ["Lignes"])


def _premiere_phrase(texte, maxi: int = 130) -> str:
    """Première phrase d'une description, pour une liste qui doit tenir dans la page (la description complète est affichée avec la figure)."""
    t = " ".join(str(texte).split())
    if ". " in t and len(t) > maxi:
        t = t.split(". ")[0] + "."
    return t if len(t) <= maxi else t[: maxi - 1].rstrip(" ,;:") + "…"


def _aplatir(objet, prefixe: str = "") -> list:
    lignes = []
    if isinstance(objet, dict):
        for k, v in objet.items():
            nom = LIBELLES_NOTES.get(str(k), str(k).replace("_", " "))
            cle = f"{prefixe} › {nom}" if prefixe else nom
            if isinstance(v, dict) and v:
                lignes += _aplatir(v, cle)
            elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                lignes.append((cle, f"{nombre(len(v))} lignes (voir la table du même nom)"))
            else:
                lignes.append((cle, v))
    else:
        lignes.append((prefixe or "Valeur", objet))
    return lignes


def notes(ctx, etape: str, nom: str = "Notes") -> Tableau:
    """Un objet JSON du dépôt (par défaut les « Notes » de l'étape) présenté en tableau : élément, valeur."""
    try:
        objet = ctx.depot.lire_json(etape, nom)
        chemin = ctx.depot.chemin(etape, nom, "json")
    except Exception:
        return _tableau(pd.DataFrame(), f"« {nom} » absent de l'étape « {etape} » : relancer la première cellule du notebook.")
    lignes, vues = [], set()
    for cle, v in _aplatir(objet):
        fin = cle.split(" › ")[-1]
        if _est_chemin(v):
            v = _relatif(ctx, v)                              # chemin : jamais affiché en entier hors du dossier
        elif isinstance(v, str) and len(v) >= 19 and v[4:5] == "-" and v[10:11] == "T":
            j = pd.to_datetime(v, errors="coerce")
            v = v if pd.isna(j) else j.strftime("%d/%m/%Y") if v[11:19] == "00:00:00" else j.strftime("%d/%m/%Y à %H:%M")
        elif isinstance(v, (int, float)) and not isinstance(v, bool) and (fin in NOTES_POURCENT or " › Fréquence de traitement" in cle):
            v = nombre(v * 100, 1, ESP + "%")
        valeur = "inconnu" if _vide(v) and not isinstance(v, (list, tuple)) else _texte(v)
        if (cle, valeur) not in vues and (cle.lower(), valeur) not in {(c.lower(), x) for c, x in vues}:
            vues.add((cle, valeur))
            lignes.append({"Élément": cle, "Valeur": valeur})
    return _tableau(pd.DataFrame(lignes, columns=["Élément", "Valeur"]), "fichier : " + _relatif(ctx, chemin))


def anomalies(ctx) -> Tableau:
    """Les calculs qui ont échoué pendant cette exécution (étape, calcul, erreur). Table vide = tout a été calculé."""
    liste = list(getattr(ctx, "anomalies", None) or [])
    d = pd.DataFrame(liste, columns=["Étape", "Calcul", "Erreur", "Détail"]).drop(columns="Détail")
    return _tableau(d, f"{nombre(len(d))} anomalie{'s' if len(d) > 1 else ''} pendant cette exécution" if len(d)
                    else "Aucune anomalie : tous les calculs de cette exécution ont abouti.")


def classeur(ctx, onglet: str = "Lisez_moi", n=None) -> Tableau:
    """Un onglet du classeur de paramètres (parametres/ERC_Parametres.xlsx), tel qu'il est sur le disque."""
    try:
        f = Path(ctx.cfg.classeur)
        if not f.is_file():
            return _tableau(pd.DataFrame(), "Classeur de paramètres absent : il est créé à la première exécution de l'étape « classement ».")
        d = pd.read_excel(f, sheet_name=onglet, dtype=object)
    except Exception as e:
        return _tableau(pd.DataFrame(), f"Onglet « {onglet} » illisible ({type(e).__name__}) : fermer le classeur s'il est ouvert, vérifier le nom de l'onglet.")
    total = len(d)
    d = d.head(int(n)) if n else d
    textes, _ = _formater(d.astype(object).where(d.notna(), None), plages=False)
    return _tableau(textes, f"{nombre(len(d))} ligne{'s' if len(d) > 1 else ''}" + (f" sur {nombre(total)}" if total > len(d) else "")
                    + f" · onglet « {onglet} » de {_relatif(ctx, f)}")


# --------------------------------------------------------------------------- bandeaux
class Bandeau:
    """Message d'une ligne : encadré coloré dans un notebook, texte simple ailleurs."""

    def __init__(self, texte: str, couleur: str = "#2a78d6", fond: str = "#eef4fc", lien: str | None = None, libelle_lien: str = ""):
        self.texte, self.couleur, self.fond, self.lien, self.libelle_lien = texte, couleur, fond, lien, libelle_lien

    def __repr__(self):
        return self.texte + (f" [{self.lien}]" if self.lien else "")

    def _repr_html_(self):
        lien = f' <a href="{html.escape(self.lien, quote=True)}" target="_blank">{html.escape(self.libelle_lien or self.lien)}</a>' if self.lien else ""
        return (f'<div style="border-left:6px solid {self.couleur}; background:{self.fond}; color:#1a1a19; padding:8px 12px; margin:4px 0">'
                f"{html.escape(self.texte)}{lien}</div>")


def etat(ctx) -> Bandeau:
    """Bandeau d'une ligne : démonstration ou données réelles, période couverte, anomalies de l'exécution."""
    demo = bool(getattr(ctx.cfg, "demo", False))
    periode = getattr(getattr(ctx, "src", None), "periode", None) or "période inconnue"
    n = len(getattr(ctx, "anomalies", None) or [])
    suite = f"Période : {periode}. " + ("Aucune anomalie de calcul." if not n else f"{n} anomalie{'s' if n > 1 else ''} de calcul : voir la table des anomalies (notebook 00 ou 06) avant de lire les résultats.")
    if demo:
        return Bandeau("DÉMONSTRATION : toutes les données affichées sont fictives. " + suite, "#eda100", "#fff7e0")
    return Bandeau("Données réelles. " + suite + " Le dépôt du code est public : ne pas y enregistrer ce notebook une fois exécuté.", "#2a78d6", "#eef4fc")


def outil(ctx) -> Bandeau:
    """Où se trouve l'outil des décideurs produit par l'étape « synthese » (une phrase s'il n'a pas été produit)."""
    chemin = ((getattr(ctx, "res", None) or {}).get("synthese", {}).get("Outil") or {}).get("chemin")
    if not chemin or not Path(str(chemin)).is_file():
        return Bandeau("L'outil des décideurs n'a pas été produit à cette exécution : voir la table des anomalies ci-dessous. "
                       "Les tables et les figures de ce notebook restent valables.", "#898781", "#f3f2ee")
    try:
        lien = Path(os.path.relpath(str(chemin), os.getcwd())).as_posix()
    except ValueError:                                        # autre lecteur sous Windows
        lien = Path(str(chemin)).as_uri()
    return Bandeau(f"Outil des décideurs : {_relatif(ctx, chemin)}. Page autonome, à ouvrir dans un navigateur (double-clic sur le fichier).",
                   "#1baf7a", "#eaf7f1", lien, "Ouvrir l'outil")


# --------------------------------------------------------------------------- figures
def _ipython():
    """Le module d'affichage d'IPython quand on est dans un notebook (ou une console IPython) ; None dans un script ordinaire."""
    try:
        from IPython import display, get_ipython
        return display if get_ipython() is not None else None
    except Exception:
        return None


def _trace_possible() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("matplotlib") is not None
    except Exception:
        return False


ECART_COULEUR_MAX = 16                                # sur 255, par canal : au-delà, l'image d'origine est gardée


def _png(chemin: Path) -> bytes:
    """Octets de l'image à insérer dans le notebook. Si Pillow est installé, l'image est ramenée à 256 couleurs pour
    alléger le notebook (environ quatre fois), à condition qu'aucun point ne change de couleur de plus de
    ECART_COULEUR_MAX sur 255 : sinon, ou au moindre doute, ce sont les octets du fichier qui sont insérés tels quels.
    Le PNG du dépôt n'est jamais modifié."""
    brut = Path(chemin).read_bytes()
    try:
        import io

        from PIL import Image
        image = Image.open(io.BytesIO(brut)).convert("RGB")
        methode = getattr(getattr(Image, "Quantize", Image), "FASTOCTREE", 2)      # regroupe les couleurs voisines, sans en déplacer aucune loin
        reduite = image.quantize(colors=256, method=methode, dither=0)
        ecart = np.abs(np.asarray(image, dtype=np.int16) - np.asarray(reduite.convert("RGB"), dtype=np.int16)).max()
        if int(ecart) > ECART_COULEUR_MAX:
            return brut
        tampon = io.BytesIO()
        reduite.save(tampon, format="PNG", optimize=True)
        allege = tampon.getvalue()
        return allege if len(allege) < len(brut) else brut
    except Exception:
        return brut


def figures(ctx, etape: str, noms=None, largeur: int = LARGEUR_IMAGE):
    """Affiche les figures enregistrées d'une étape (PNG du dépôt), chacune précédée de sa description.

    noms : une figure ou une liste de figures, dans l'ordre voulu (défaut : toutes celles de l'étape, dans l'ordre de lecture).
    Hors notebook, renvoie la liste des fichiers.
    """
    try:
        m = ctx.depot.manifeste()
        m = m[m["etape"].eq(etape) & m["type"].eq("figure")]
        connues = {r["nom"]: (Path(ctx.depot.racine) / r["fichier"], r["description"], r.get("genere_le")) for _, r in m.iterrows()}
    except Exception:
        connues = {}
    if isinstance(noms, str):
        noms = [noms]
    if noms is None:
        try:
            from . import figures as _figures
            noms = [n for n in _figures.NOMS.get(etape, []) if n in connues] + sorted(n for n in connues if n not in _figures.NOMS.get(etape, []))
        except Exception:                                      # matplotlib absent : ordre alphabétique des figures présentes
            noms = sorted(connues)
    vue = _ipython()
    chemins = []
    for nom in noms:
        chemin, description, genere_le = connues.get(nom, (None, "", None))
        ancienne = chemin is not None and Path(chemin).is_file() and _perime(ctx, genere_le)
        if chemin is None or not Path(chemin).is_file() or ancienne:
            message = (f"Figure « {nom} » non produite à cette exécution : " + ("le module de tracé (matplotlib) n'est pas installé sur ce poste."
                       if not _trace_possible() else "les valeurs qu'elle représente manquent ou n'ont pas pu être calculées (voir la table correspondante)."))
            if ancienne:                                       # ne jamais montrer une image qui ne correspond plus aux tables affichées
                message += " Un fichier du même nom existe, mais il date d'une exécution précédente : il n'est pas affiché."
            vue.display(Bandeau(message, "#898781", "#f3f2ee")) if vue else print(message)
            continue
        chemins.append(Path(chemin))
        if vue:
            vue.display(vue.Markdown(f"**{nom}.** {description}" if isinstance(description, str) and description else f"**{nom}**"))
            try:                                               # texte de remplacement de l'image (lecteurs d'écran)
                image = vue.Image(data=_png(Path(chemin)), format="png", width=largeur, alt=f"Figure : {nom}")
            except TypeError:                                  # version d'IPython sans texte de remplacement
                image = vue.Image(data=_png(Path(chemin)), format="png", width=largeur)
            vue.display(image)
        else:
            print(f"{nom} : {description}\n  {chemin}")
    if not noms and not chemins:
        message = f"Aucune figure enregistrée pour l'étape « {etape} »."
        vue.display(Bandeau(message, "#898781", "#f3f2ee")) if vue else print(message)
    return None if vue else chemins
