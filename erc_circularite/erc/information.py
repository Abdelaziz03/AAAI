"""Valeur de l'information : combien vaut le fait de connaître un paramètre incertain avant de décider.

Cadre (docs/Formal_framework.md, proposition 6). À flux et heures fixés, la valeur V du modèle de ligne est une
fonction convexe de tout paramètre qui entre linéairement dans les valeurs : prix du recycleur, probabilité qu'une
pièce soit réutilisable, valeur de réemploi. Pour un paramètre incertain θ de moyenne θ̄ :

    valeur de l'information parfaite  =  E[V(θ)] − V(θ̄)  ≥ 0

Elle est nulle quand la décision ne change pas quelle que soit la valeur de θ : apprendre θ ne sert alors à rien.
Une borne se calcule sans résoudre le modèle :

    prix d'une pièce        EVPI ≤ FRU scrapées × pièces par FRU × poids × E|p − p̄|
    probabilité de réemploi EVPI ≤ FRU scrapées × pièces par FRU × |valeur de réemploi − poids × prix| × E|q − q̄|

Usage : ne chercher la composition d'une pièce (recherche web, appel à un modèle de langage, expert) ou n'auditer
son état que si l'information peut rapporter plus qu'elle ne coûte. La borne écarte sans calcul les pièces légères
ou rares ; le calcul exact classe les autres.

Tout est exprimé par an, dans la monnaie du modèle. Une entrée inconnue donne NaN, jamais 0.
"""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd

from . import ligne as mod_ligne

V = "Marge variable / an (€)"


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


def _poser(frus: dict, fru: str, piece: str, champ: str, v) -> dict:
    f = copy.deepcopy(frus)
    f[fru]["pieces"][piece][champ] = v
    return f


def evpi(ligne: dict, frus: dict, fru: str, piece: str, champ: str, valeurs, probabilites=None) -> dict:
    """Valeur de l'information parfaite sur un paramètre d'une pièce, par scénarios.

    champ        : « prix_recycleur_eur_kg », « p_reutilisable », « valeur_eur »… (paramètre qui entre linéairement)
    valeurs      : valeurs possibles du paramètre (une par scénario)
    probabilites : leur probabilité (défaut : équiprobables) ; normalisées si leur somme n'est pas 1
    Renvoie la valeur avec information E[V(θ)], sans information V(θ̄), leur différence, et si la décision change.
    """
    lg, fr = _centre(ligne, frus)
    valeurs = np.asarray(list(valeurs), float)
    p = np.full(len(valeurs), 1.0 / max(len(valeurs), 1)) if probabilites is None else np.asarray(list(probabilites), float)
    vide = {"Valeur avec information (€/an)": np.nan, "Valeur sans information (€/an)": np.nan, "Valeur de l'information (€/an)": np.nan,
            "La décision change": None, "Scénarios": len(valeurs)}
    if not len(valeurs) or fru not in fr or piece not in fr[fru].get("pieces", {}) or not np.isfinite(valeurs).all() or p.sum() <= 0:
        return vide
    p = p / p.sum()
    moyenne = float(p @ valeurs)
    v_sans, plan_sans = valeur(lg, _poser(fr, fru, piece, champ, moyenne))
    par_scenario = [valeur(lg, _poser(fr, fru, piece, champ, float(x))) for x in valeurs]
    v_avec = float(sum(pi * v for pi, (v, _) in zip(p, par_scenario)))
    if not np.isfinite(v_sans) or not np.isfinite(v_avec):
        return vide
    return {"Valeur avec information (€/an)": v_avec, "Valeur sans information (€/an)": v_sans,
            # V est convexe : la différence est positive ou nulle ; un écart négatif ne peut venir que de l'arrondi
            "Valeur de l'information (€/an)": max(v_avec - v_sans, 0.0),
            "La décision change": any(plan != plan_sans for pi, (_, plan) in zip(p, par_scenario) if pi > 0),
            "Scénarios": len(valeurs)}


def _ecart_absolu_moyen(valeurs, probabilites=None) -> float:
    x = np.asarray(list(valeurs), float)
    p = np.full(len(x), 1.0 / max(len(x), 1)) if probabilites is None else np.asarray(list(probabilites), float)
    if not len(x) or p.sum() <= 0 or not np.isfinite(x).all():
        return np.nan
    p = p / p.sum()
    return float(p @ np.abs(x - p @ x))


def borne_prix(scrap_an, n_par_fru, poids_kg, prix, probabilites=None) -> float:
    """Borne de la valeur de l'information sur le prix d'une pièce : masse annuelle concernée × E|p − p̄|.
    Sans résoudre le modèle. Entrée inconnue → NaN (on ne peut pas écarter la pièce sans connaître son enjeu)."""
    if any(mod_ligne._inconnu(v) for v in (scrap_an, n_par_fru, poids_kg)):
        return np.nan
    return float(scrap_an) * float(n_par_fru) * float(poids_kg) * _ecart_absolu_moyen(prix, probabilites)


def borne_rendement(scrap_an, n_par_fru, valeur_reemploi, poids_kg, prix, q, probabilites=None) -> float:
    """Borne de la valeur de l'information sur la probabilité de réemploi d'une pièce :
    pièces par an × |valeur de réemploi − poids × prix| × E|q − q̄|. Poids ou prix inconnu : la revente au kilo vaut 0."""
    if any(mod_ligne._inconnu(v) for v in (scrap_an, n_par_fru, valeur_reemploi)):
        return np.nan
    matiere = 0.0 if mod_ligne._inconnu(poids_kg) or mod_ligne._inconnu(prix) else float(poids_kg) * float(prix)
    return float(scrap_an) * float(n_par_fru) * abs(float(valeur_reemploi) - matiere) * _ecart_absolu_moyen(q, probabilites)


def scenarios_beta(a: float, b: float, n: int = 9) -> tuple[np.ndarray, np.ndarray]:
    """n scénarios équiprobables d'une loi Bêta(a, b) : ses quantiles aux milieux de n tranches égales."""
    from .fiabilite import beta_quantile
    niveaux = (np.arange(n) + 0.5) / n
    return np.array([beta_quantile(float(u), a, b) for u in niveaux]), np.full(n, 1.0 / n)


def priorites(ligne: dict, frus: dict, incertitudes: pd.DataFrame, cout_information: float | None = None) -> pd.DataFrame:
    """Classe des paramètres incertains par valeur de l'information.

    incertitudes : une ligne par paramètre, colonnes « Type de FRU », « Pièce », « Paramètre » (champ du modèle),
                   « Valeurs » (liste) et « Probabilités » (liste, facultative).
    cout_information : coût de la moins chère des façons d'apprendre le paramètre ; s'il est donné, la colonne
                   « À acquérir » dit si l'information peut le rembourser.
    La borne est calculée d'abord ; le calcul exact (plusieurs résolutions du modèle) n'est fait que si la borne
    dépasse le coût, ou si le coût n'est pas donné.
    """
    lg, fr = _centre(ligne, frus)
    lignes = []
    for _, r in incertitudes.iterrows():
        f, pc, champ = r["Type de FRU"], r["Pièce"], r["Paramètre"]
        vals, probs = list(r["Valeurs"]), (list(r["Probabilités"]) if "Probabilités" in r and r["Probabilités"] is not None else None)
        d = fr.get(f, {})
        e = d.get("pieces", {}).get(pc, {})
        if champ == "prix_recycleur_eur_kg":
            borne = borne_prix(d.get("scrap_an"), e.get("n_par_fru"), e.get("poids_kg"), vals, probs)
        elif champ == "p_reutilisable":
            borne = borne_rendement(d.get("scrap_an"), e.get("n_par_fru"), e.get("valeur_eur"), e.get("poids_kg"), e.get("prix_recycleur_eur_kg"), vals, probs)
        else:
            borne = np.nan
        ecarte = cout_information is not None and np.isfinite(borne) and borne < cout_information
        res = {"Valeur de l'information (€/an)": np.nan, "La décision change": None} if ecarte else evpi(lg, fr, f, pc, champ, vals, probs)
        v = res["Valeur de l'information (€/an)"]
        lignes.append({"Type de FRU": f, "Pièce": pc, "Paramètre": champ, "Borne (€/an)": borne, "Valeur de l'information (€/an)": v,
                       "La décision change": res["La décision change"],
                       "Calcul exact": "non : la borne est sous le coût" if ecarte else "oui",
                       "À acquérir": (None if cout_information is None else bool(np.isfinite(v) and v >= cout_information))})
    t = pd.DataFrame(lignes, columns=["Type de FRU", "Pièce", "Paramètre", "Borne (€/an)", "Valeur de l'information (€/an)",
                                      "La décision change", "Calcul exact", "À acquérir"])
    return t.sort_values("Valeur de l'information (€/an)", ascending=False, na_position="last").reset_index(drop=True)
