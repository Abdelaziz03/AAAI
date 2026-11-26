"""Valeur de l'information : combien vaut le fait de connaître un paramètre incertain avant de décider.

Cadre : docs/Formal_framework.md, propositions 6 et 7. Tout est exprimé par an, dans la monnaie du modèle ; le coût
d'une acquisition lui est comparé sur un an. Une entrée inconnue donne NaN, jamais 0.

1. PARAMÈTRE SUR LEQUEL ON PEUT AGIR À SA MOYENNE (proposition 6) : probabilité de réemploi, valeur d'une pièce, prix
   d'une classe connue mais mal cotée. À flux et heures fixés, la valeur V du modèle de ligne est convexe en un tel
   paramètre θ, de moyenne θ̄ :

       valeur de l'information parfaite  =  E[V(θ)] − V(θ̄)  ≥ 0

   nulle quand la décision ne change pas quelle que soit la valeur de θ. Bornes, sans résoudre le modèle :

       prix d'une pièce          ≤ ½ × exemplaires par an × poids × E|p − p̄|
       probabilité de réemploi   ≤ ½ × exemplaires par an × |ce que rapporte un exemplaire bon de plus| × E|q − q̄|

   « Ce que rapporte un exemplaire bon de plus » est le coefficient de q dans la valeur du réemploi telle que
   erc/ligne.py la calcule : (valeur + délai évité) − poids × prix si le poids et le prix sont connus ;
   (valeur + délai évité) + poids × coût de traitement si seul le prix manque (l'exemplaire refusé retourne à la
   benne) ; (valeur + délai évité) si le poids manque.

2. CLASSE MATIÈRE D'UNE PIÈCE (proposition 7). Sans classe, pas de bac, donc pas de prix : la pièce ne peut pas être
   triée, et on ne peut pas « agir au prix moyen ». Ce que vaut d'établir la classe :

       E[V(prix de la classe)] − V(pièce non triable)  ≤  exemplaires par an × poids × E[(prix + coût de traitement)⁺]

Usage : ne chercher la composition d'une pièce (recherche de documents, appel à un modèle de langage, expert) ou
n'auditer son état que si l'information peut rapporter plus qu'elle ne coûte. La borne écarte sans calcul les pièces
légères ou rares ; le calcul exact classe les autres.
"""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd

from . import ligne as mod_ligne

V = "Marge variable / an (€)"
PRIX, RENDEMENT = "prix_recycleur_eur_kg", "p_reutilisable"


def _centre(ligne: dict, frus: dict) -> tuple[dict, dict]:
    return mod_ligne._milieu(ligne or {}), mod_ligne._milieu(frus or {})


def valeur(ligne: dict, frus: dict) -> tuple[float, dict]:
    """Valeur V du modèle de ligne au centre des plages, et le plan retenu par type de FRU (pièces réemployées, recyclées)."""
    r = mod_ligne.optimiser_ligne(*_centre(ligne, frus))
    d = r["detail"]
    plan = {}
    if len(d):
        for f, g in d[d["Décision"].ne("incomplet")].groupby("Type de FRU", sort=False):
            plan[f] = tuple(sorted((str(a), str(b)) for a, b in zip(g["1 Réemploi"].fillna(""), g["2 Recyclage"].fillna(""))))
    return float(r["resume"][V]), plan


def types_de(frus: dict, piece: str, fru: str | None = None) -> list:
    """Types de FRU concernés par un paramètre de la pièce : celui qui est nommé, ou tous ceux qui la contiennent."""
    if fru is not None:
        return [fru] if fru in frus and piece in (frus[fru].get("pieces") or {}) else []
    return [f for f, d in frus.items() if piece in ((d or {}).get("pieces") or {})]


def _poser(frus: dict, types: list, piece: str, champ: str, v) -> dict:
    f = copy.deepcopy(frus)
    for t in types:
        f[t]["pieces"][piece][champ] = v
    return f


def _lois(valeurs, probabilites):
    x = np.asarray(list(valeurs), float)
    p = np.full(len(x), 1.0 / max(len(x), 1)) if probabilites is None else np.asarray(list(probabilites), float)
    if not len(x) or len(p) != len(x) or not np.isfinite(x).all() or not np.isfinite(p).all() or (p < 0).any() or p.sum() <= 0:
        return None, None
    return x, p / p.sum()


VIDE = {"Valeur avec information (€/an)": np.nan, "Valeur sans information (€/an)": np.nan, "Valeur de l'information (€/an)": np.nan,
        "La décision change": None}


def evpi(ligne: dict, frus: dict, fru: str | None, piece: str, champ: str, valeurs, probabilites=None) -> dict:
    """Valeur de l'information parfaite sur un paramètre d'une pièce, par scénarios (proposition 6).

    fru          : type de FRU ; None = le paramètre est le même dans tous les types qui contiennent la pièce
    champ        : « prix_recycleur_eur_kg », « p_reutilisable », « valeur_eur »… (paramètre qui entre linéairement)
    valeurs      : valeurs possibles du paramètre (une par scénario)
    probabilites : leur probabilité (défaut : équiprobables) ; normalisées si leur somme n'est pas 1
    Renvoie la valeur avec information E[V(θ)], sans information V(θ̄), leur différence, et si la décision change.
    """
    lg, fr = _centre(ligne, frus)
    x, p = _lois(valeurs, probabilites)
    vide = dict(VIDE, Scénarios=0 if x is None else len(x))
    types = types_de(fr, piece, fru)
    if x is None or not types:
        return vide
    v_sans, plan_sans = valeur(lg, _poser(fr, types, piece, champ, float(p @ x)))
    par_scenario = [valeur(lg, _poser(fr, types, piece, champ, float(v))) for v in x]
    v_avec = float(sum(pi * v for pi, (v, _) in zip(p, par_scenario)))
    if not np.isfinite(v_sans) or not np.isfinite(v_avec):
        return vide
    return {"Valeur avec information (€/an)": v_avec, "Valeur sans information (€/an)": v_sans,
            # V est convexe en θ : la différence est positive ou nulle, à l'arrondi près
            "Valeur de l'information (€/an)": max(v_avec - v_sans, 0.0),
            "La décision change": any(plan != plan_sans for pi, (_, plan) in zip(p, par_scenario) if pi > 0),
            "Scénarios": len(x)}


def resolution(ligne: dict, frus: dict, piece: str, prix, probabilites=None, fru: str | None = None) -> dict:
    """Ce que vaut d'établir la classe matière d'une pièce (proposition 7) : E[V(prix de la classe)] − V(pièce non triable).

    prix, probabilites : prix du recycleur pour chaque classe possible, et probabilité de chaque classe.
    Sans classe, la pièce n'a pas de prix : elle ne peut pas être triée et ses exemplaires refusés au test retournent à
    la benne. La différence peut être négative si une classe possible coûte plus à recycler que la benne actuelle.
    """
    lg, fr = _centre(ligne, frus)
    x, p = _lois(prix, probabilites)
    vide = dict(VIDE, Scénarios=0 if x is None else len(x))
    types = types_de(fr, piece, fru)
    if x is None or not types:
        return vide
    v_sans, plan_sans = valeur(lg, _poser(fr, types, piece, PRIX, None))
    par_scenario = [valeur(lg, _poser(fr, types, piece, PRIX, float(v))) for v in x]
    v_avec = float(sum(pi * v for pi, (v, _) in zip(p, par_scenario)))
    if not np.isfinite(v_avec):
        return vide
    if not np.isfinite(v_sans):                                # sans prix, plus aucune option n'est calculable : rien n'est gagné
        v_sans = 0.0
    return {"Valeur avec information (€/an)": v_avec, "Valeur sans information (€/an)": v_sans,
            "Valeur de l'information (€/an)": v_avec - v_sans,
            "La décision change": any(plan != plan_sans for pi, (_, plan) in zip(p, par_scenario) if pi > 0),
            "Scénarios": len(x)}


# --------------------------------------------------------------------------- bornes, sans résoudre le modèle
def _ecart_absolu_moyen(valeurs, probabilites=None) -> float:
    x, p = _lois(valeurs, probabilites)
    return np.nan if x is None else float(p @ np.abs(x - p @ x))


def borne_prix(scrap_an, n_par_fru, poids_kg, prix, probabilites=None) -> float:
    """Borne de la valeur de l'information sur le prix d'une pièce : ½ × exemplaires par an × poids × E|p − p̄|.
    Entrée inconnue → NaN (on ne peut pas écarter la pièce sans connaître son enjeu)."""
    if any(mod_ligne._inconnu(v) for v in (scrap_an, n_par_fru, poids_kg)):
        return np.nan
    return 0.5 * float(scrap_an) * float(n_par_fru) * float(poids_kg) * _ecart_absolu_moyen(prix, probabilites)


def gain_par_exemplaire_bon(valeur_eur, delai_semaines=None, valeur_semaine_eur=None, poids_kg=None, prix=None, cout_traitement=None) -> float:
    """Coefficient de la probabilité de réemploi dans la valeur d'un exemplaire, tel que erc/ligne.py le calcule."""
    if mod_ligne._inconnu(valeur_eur):
        return np.nan
    pleine = float(valeur_eur) + mod_ligne._facultatif(delai_semaines) * mod_ligne._facultatif(valeur_semaine_eur)
    if mod_ligne._inconnu(poids_kg):
        return pleine                                           # ni revente au kilo ni traitement évité
    if mod_ligne._inconnu(prix):
        return pleine + float(poids_kg) * mod_ligne._facultatif(cout_traitement)     # l'exemplaire refusé retourne à la benne
    return pleine - float(poids_kg) * float(prix)               # l'exemplaire refusé est vendu au kilo


def borne_rendement(scrap_an, n_par_fru, gain_bon, q, probabilites=None) -> float:
    """Borne de la valeur de l'information sur la probabilité de réemploi d'une pièce :
    ½ × exemplaires par an × |gain par exemplaire bon de plus| × E|q − q̄| (voir `gain_par_exemplaire_bon`)."""
    if any(mod_ligne._inconnu(v) for v in (scrap_an, n_par_fru, gain_bon)):
        return np.nan
    return 0.5 * float(scrap_an) * float(n_par_fru) * abs(float(gain_bon)) * _ecart_absolu_moyen(q, probabilites)


def borne_resolution(exemplaires_an, poids_kg, prix, probabilites=None, cout_traitement=0.0) -> float:
    """Borne de ce que vaut d'établir la classe d'une pièce : exemplaires par an × poids × E[(prix + coût de traitement)⁺]."""
    x, p = _lois(prix, probabilites)
    if x is None or any(mod_ligne._inconnu(v) for v in (exemplaires_an, poids_kg)):
        return np.nan
    return float(exemplaires_an) * float(poids_kg) * float(p @ np.maximum(x + mod_ligne._facultatif(cout_traitement), 0.0))


def scenarios_beta(a: float, b: float, n: int = 9) -> tuple[np.ndarray, np.ndarray]:
    """n scénarios équiprobables d'une loi Bêta(a, b) : ses quantiles aux milieux de n tranches égales."""
    from .fiabilite import beta_quantile
    niveaux = (np.arange(n) + 0.5) / n
    return np.array([beta_quantile(float(u), a, b) for u in niveaux]), np.full(n, 1.0 / n)


# --------------------------------------------------------------------------- classement des paramètres incertains
COLS_PRIORITES = ["Type de FRU", "Pièce", "Paramètre", "Borne (€/an)", "Valeur de l'information (€/an)", "La décision change", "Calcul exact", "À acquérir"]


def _borne(lg: dict, fr: dict, types: list, piece: str, champ: str, vals, probs) -> float:
    """Borne de la proposition 6, sommée sur les types de FRU qui partagent le paramètre."""
    total = 0.0
    for f in types:
        d, e = fr[f], fr[f]["pieces"][piece] or {}
        if champ == PRIX:
            b = borne_prix(d.get("scrap_an"), e.get("n_par_fru"), e.get("poids_kg"), vals, probs)
        elif champ == RENDEMENT:
            gain = gain_par_exemplaire_bon(e.get("valeur_eur"), e.get("delai_semaines"), e.get("valeur_semaine_eur"), e.get("poids_kg"),
                                           e.get(PRIX), lg.get("cout_traitement_eur_kg"))
            b = borne_rendement(d.get("scrap_an"), e.get("n_par_fru"), gain, vals, probs)
        else:
            b = np.nan
        total += b
    return float(total) if types else np.nan


def priorites(ligne: dict, frus: dict, incertitudes: pd.DataFrame, cout_information: float | None = None) -> pd.DataFrame:
    """Classe des paramètres incertains par valeur de l'information (proposition 6).

    incertitudes : une ligne par paramètre, colonnes « Type de FRU » (vide = tous les types qui contiennent la pièce),
                   « Pièce », « Paramètre » (champ du modèle), « Valeurs » (liste) et « Probabilités » (liste, facultative).
    cout_information : coût de la moins chère des façons d'apprendre le paramètre ; s'il est donné, la colonne
                   « À acquérir » dit si un an d'information peut le rembourser.
    La borne est calculée d'abord ; le calcul exact (plusieurs résolutions du modèle) n'est fait que si la borne
    atteint le coût, ou si le coût n'est pas donné.
    """
    lg, fr = _centre(ligne, frus)
    lignes = []
    for _, r in incertitudes.iterrows():
        f, pc, champ = r.get("Type de FRU"), r["Pièce"], r["Paramètre"]
        f = None if f is None or (isinstance(f, float) and np.isnan(f)) or f == "" else f
        vals, probs = list(r["Valeurs"]), (list(r["Probabilités"]) if "Probabilités" in r and r["Probabilités"] is not None else None)
        borne = _borne(lg, fr, types_de(fr, pc, f), pc, champ, vals, probs)
        ecarte = cout_information is not None and np.isfinite(borne) and borne < cout_information
        res = VIDE if ecarte else evpi(lg, fr, f, pc, champ, vals, probs)
        v = res["Valeur de l'information (€/an)"]
        lignes.append({"Type de FRU": f if f is not None else "tous", "Pièce": pc, "Paramètre": champ, "Borne (€/an)": borne,
                       "Valeur de l'information (€/an)": v, "La décision change": res["La décision change"],
                       "Calcul exact": "non : la borne est sous le coût" if ecarte else "oui",
                       "À acquérir": (None if cout_information is None else bool(np.isfinite(v) and v >= cout_information))})
    t = pd.DataFrame(lignes, columns=COLS_PRIORITES)
    return t.sort_values("Valeur de l'information (€/an)", ascending=False, na_position="last").reset_index(drop=True)


COLS_CLASSES = ["Pièce", "Types de FRU", "Classes possibles", "Borne (€/an)", "Valeur d'établir la classe (€/an)", "La décision change",
                "Calcul exact", "À acquérir"]


def priorites_classes(ligne: dict, frus: dict, croyances: dict, prix_par_classe: dict, cout_information: float | None = None,
                      seuil: float = 0.01) -> pd.DataFrame:
    """Pièces du modèle de ligne dont la classe matière n'est pas établie, par valeur de l'établir (proposition 7).

    croyances       : {pièce: {classe: probabilité}} ; les classes de probabilité inférieure à `seuil` sont ignorées
    prix_par_classe : {classe: prix du recycleur en €/kg}
    Une pièce dont une classe plausible n'a pas de prix a une borne inconnue : elle n'est pas écartée, et son calcul
    exact n'est pas possible.
    """
    lg, fr = _centre(ligne, frus)
    tau = lg.get("cout_traitement_eur_kg")
    lignes = []
    for pc, croyance in croyances.items():
        types = types_de(fr, pc)
        if not types:
            continue
        plausibles = {c: q for c, q in (croyance or {}).items() if q is not None and q >= seuil}
        sans_prix = [c for c in plausibles if mod_ligne._inconnu(prix_par_classe.get(c))]
        vals, probs = [prix_par_classe[c] for c in plausibles if c not in sans_prix], [q for c, q in plausibles.items() if c not in sans_prix]
        if sans_prix or not vals:
            borne, res, exact = np.nan, VIDE, "non : une classe possible n'a pas de prix (" + ", ".join(sans_prix) + ")" if sans_prix else "non : aucune classe possible"
        else:
            borne = 0.0
            for f in types:
                e = fr[f]["pieces"][pc] or {}
                ex = np.nan if any(mod_ligne._inconnu(v) for v in (fr[f].get("scrap_an"), e.get("n_par_fru"))) else float(fr[f]["scrap_an"]) * float(e["n_par_fru"])
                borne += borne_resolution(ex, e.get("poids_kg"), vals, probs, tau)
            ecarte = cout_information is not None and np.isfinite(borne) and borne < cout_information
            res = VIDE if ecarte else resolution(lg, fr, pc, vals, probs)
            exact = "non : la borne est sous le coût" if ecarte else "oui"
        v = res["Valeur de l'information (€/an)"]
        lignes.append({"Pièce": pc, "Types de FRU": ", ".join(map(str, types)),
                       "Classes possibles": ", ".join(f"{c} {q:.0%}" for c, q in sorted(plausibles.items(), key=lambda x: -x[1])),
                       "Borne (€/an)": borne, "Valeur d'établir la classe (€/an)": v, "La décision change": res["La décision change"],
                       "Calcul exact": exact, "À acquérir": (None if cout_information is None else bool(np.isfinite(v) and v >= cout_information))})
    t = pd.DataFrame(lignes, columns=COLS_CLASSES)
    return t.sort_values("Valeur d'établir la classe (€/an)", ascending=False, na_position="last").reset_index(drop=True)
