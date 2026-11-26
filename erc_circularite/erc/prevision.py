"""Prévision du flux hebdomadaire de FRU scrapées, par type.

Ces séries sont courtes (quelques dizaines de semaines), à faibles effectifs et intermittentes (beaucoup de zéros).
Le module fournit des méthodes adaptées à ce cas, une évaluation honnête, et un point d'entrée pour comparer avec des
modèles de fondation de séries temporelles (Chronos, TimesFM, Moirai, Toto, Timestral…), qui s'exécutent sur un poste
disposant de leurs poids et ne font pas partie du dossier.

Méthodes (chacune rend, pour la semaine suivante et par type, une moyenne et des quantiles)
  moyenne        moyenne de l'historique ; loi de Poisson
  croston        méthode de Croston : taille des arrivées et intervalle entre arrivées lissés séparément
  sba            Croston corrigé du biais (Syntetos et Boylan)
  tsb            variante Teunter-Syntetos-Babai : probabilité d'arrivée lissée à chaque semaine (suit une extinction)
  gamma_poisson  taux propre à chaque type, tiré vers le taux moyen des autres types ; loi binomiale négative
  structurel     FRU scrapées = FRU arrivées à une décision × taux de scrap ; taux Bêta partagé entre types,
                 arrivées prévues par leur moyenne récente ; loi bêta-binomiale. Demande la série des arrivées.

Évaluation à origine glissante, une semaine à l'avance : chaque semaine est prévue avec les seules semaines précédentes.
  Écart quadratique relatif  racine de l'erreur quadratique moyenne, rapportée à celle de la méthode « moyenne »
                             (< 1 = meilleure). L'erreur absolue n'est pas utilisée : sur une série intermittente,
                             elle récompense la prévision « zéro ».
  Perte de quantile          moyenne des pertes de quantile (pinball) sur la grille : note la loi entière, pas un point
  Couverture 80 %            part des semaines dont la valeur tombe entre les quantiles 10 % et 90 % (cible ≈ 80 %,
                             au-dessus pour des comptages, les quantiles étant des entiers)

Toutes les lois prédictives sont obtenues par simulation à graine fixe : deux exécutions donnent les mêmes nombres.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)
METHODES = ("moyenne", "croston", "sba", "tsb", "gamma_poisson", "structurel")
N_SIM = 4000
MODELES_EXTERNES: dict = {}


def enregistrer_modele(nom: str, fonction) -> None:
    """Ajoute un modèle externe à la comparaison, par exemple un modèle de fondation de séries temporelles.

    fonction(historique: np.ndarray, quantiles: tuple) -> (moyenne, {quantile: valeur}) pour la semaine suivante.
    Exemple d'enveloppe, à écrire sur le poste qui a le modèle :

        def chronos(historique, quantiles):
            q, moyenne = pipeline.predict_quantiles(torch.tensor(historique), prediction_length=1, quantile_levels=list(quantiles))
            return float(moyenne[0, 0]), {u: float(q[0, 0, i]) for i, u in enumerate(quantiles)}
        prevision.enregistrer_modele("Chronos", chronos)
    """
    MODELES_EXTERNES[nom] = fonction


# --------------------------------------------------------------------------- méthodes ponctuelles pour séries intermittentes
def croston(y, alpha: float = 0.1, variante: str = "croston", beta: float = 0.1) -> float:
    """Taux moyen prévu par semaine. variante : « croston », « sba » ou « tsb ». Historique sans arrivée → 0."""
    y = np.asarray(y, float)
    y = y[np.isfinite(y)]
    if not len(y) or not (y > 0).any():
        return 0.0
    if variante == "tsb":
        premier = int(np.argmax(y > 0))
        taille, proba = y[premier], 1.0 / (premier + 1)
        for v in y[premier + 1:]:
            proba += beta * ((v > 0) - proba)
            if v > 0:
                taille += alpha * (v - taille)
        return float(proba * taille)
    premier = int(np.argmax(y > 0))
    taille, intervalle, depuis = y[premier], float(premier + 1), 0
    for v in y[premier + 1:]:
        depuis += 1
        if v > 0:
            taille += alpha * (v - taille)
            intervalle += alpha * (depuis - intervalle)
            depuis = 0
    taux = taille / intervalle
    return float(taux * (1 - alpha / 2)) if variante == "sba" else float(taux)


# --------------------------------------------------------------------------- lois prédictives
def _resume(tirages: np.ndarray, quantiles=QUANTILES) -> tuple[float, dict]:
    return float(np.mean(tirages)), {u: float(np.quantile(tirages, u)) for u in quantiles}


def _poisson(taux: float, rng, quantiles=QUANTILES):
    return _resume(rng.poisson(max(taux, 0.0), N_SIM), quantiles)


def _moments_gamma(taux: np.ndarray, semaines: int) -> tuple[float, float]:
    """Loi Gamma des taux entre types, par les moments ; la variance d'échantillonnage (m / semaines) est retirée."""
    m, v = float(np.mean(taux)), float(np.var(taux, ddof=1)) if len(taux) > 1 else 0.0
    exces = v - m / max(semaines, 1)
    if m <= 0:
        return 1.0, 1e9                              # aucun FRU scrapé nulle part : taux tiré vers 0
    if exces <= 1e-12:
        return 1e6, 1e6 / m                          # les types ne diffèrent pas plus que le hasard : taux commun
    a = m * m / exces
    return a, a / m


def _moments_beta(p: np.ndarray, poids: np.ndarray) -> tuple[float, float]:
    """Loi Bêta des taux de scrap entre types, par les moments pondérés par les effectifs."""
    if not len(p) or poids.sum() <= 0:
        return 1.0, 1.0
    m = float(np.average(p, weights=poids))
    v = float(np.average((p - m) ** 2, weights=poids))
    if not 0 < m < 1:
        return (0.5, 50.0) if m <= 0 else (50.0, 0.5)
    v = min(max(v, 1e-6), m * (1 - m) * 0.99)
    force = m * (1 - m) / v - 1
    return m * force, (1 - m) * force


def prevoir(Y: pd.DataFrame, E: pd.DataFrame | None = None, methodes=METHODES, quantiles=QUANTILES, graine: int = 2026, recent: int = 8) -> pd.DataFrame:
    """Prévision de la semaine suivante pour chaque type.

    Y : comptages hebdomadaires, une ligne par type, une colonne par semaine (dans l'ordre du temps).
    E : mêmes dimensions, FRU arrivées à une décision (réparées + scrapées) ; requis par « structurel ».
    """
    lignes = []
    y = Y.to_numpy(float)
    n_types, T = y.shape if y.ndim == 2 else (0, 0)
    if not n_types or not T:
        return pd.DataFrame(columns=["FRU", "Méthode", "Moyenne", *[f"q{int(100 * u)}" for u in quantiles]])
    a, b = _moments_gamma(y.sum(axis=1) / T, T)
    e = E.reindex(index=Y.index, columns=Y.columns).to_numpy(float) if E is not None else None
    if e is not None:
        ok = np.isfinite(e).all(axis=1) & (e.sum(axis=1) > 0)
        tot_e, tot_y = e.sum(axis=1), np.minimum(y.sum(axis=1), e.sum(axis=1))
        al, be = _moments_beta(tot_y[ok] / tot_e[ok], tot_e[ok]) if ok.any() else (1.0, 1.0)
    for i, fru in enumerate(Y.index):
        rng = np.random.default_rng([graine, i])                 # une suite par type : ajouter un type ne change pas les autres
        h = y[i]
        for m in methodes:
            if m == "moyenne":
                moy, q = _poisson(h.mean(), rng, quantiles)
            elif m in ("croston", "sba", "tsb"):
                moy, q = _poisson(croston(h, variante=m), rng, quantiles)
            elif m == "gamma_poisson":
                moy, q = _resume(rng.poisson(rng.gamma(a + h.sum(), 1.0 / (b + T), N_SIM)), quantiles)
            elif m == "structurel":
                if e is None or not ok[i]:
                    continue                                      # sans série d'arrivées : la méthode n'est pas calculée
                taux = rng.beta(al + tot_y[i], be + tot_e[i] - tot_y[i], N_SIM)
                arrivees = rng.poisson(max(e[i, -recent:].mean(), 0.0), N_SIM)
                moy, q = _resume(rng.binomial(arrivees, taux), quantiles)
            elif m in MODELES_EXTERNES:
                moy, q = MODELES_EXTERNES[m](h.copy(), tuple(quantiles))
            else:
                raise ValueError(f"Méthode de prévision inconnue : {m}")
            lignes.append({"FRU": fru, "Méthode": m, "Moyenne": moy, **{f"q{int(100 * u)}": q[u] for u in quantiles}})
    return pd.DataFrame(lignes)


# --------------------------------------------------------------------------- évaluation à origine glissante
def evaluer(Y: pd.DataFrame, E: pd.DataFrame | None = None, methodes=METHODES, depart: int = 8, quantiles=QUANTILES, graine: int = 2026) -> dict:
    """Chaque semaine à partir de `depart` est prévue avec les semaines précédentes seulement.
    Renvoie {"resume": une ligne par méthode, "detail": une ligne par (méthode, type, semaine)}."""
    cols_q = [f"q{int(100 * u)}" for u in quantiles]
    vide = {"resume": pd.DataFrame(columns=["Méthode", "Prévisions", "Écart quadratique relatif", "Perte de quantile", "Couverture 80 %", "Biais"]),
            "detail": pd.DataFrame(columns=["Méthode", "FRU", "Semaine", "Observé", "Moyenne", *cols_q])}
    T = Y.shape[1]
    if T <= depart or not len(Y):
        return vide
    morceaux = []
    for t in range(depart, T):
        p = prevoir(Y.iloc[:, :t], None if E is None else E.iloc[:, :t], methodes, quantiles, graine)
        if not len(p):
            continue
        p["Semaine"], p["Observé"] = Y.columns[t], p["FRU"].map(Y.iloc[:, t])
        morceaux.append(p)
    if not morceaux:
        return vide
    d = pd.concat(morceaux, ignore_index=True)
    d["Erreur"] = d["Moyenne"] - d["Observé"]
    d["Perte de quantile"] = np.mean([np.maximum(u * (d["Observé"] - d[c]), (u - 1) * (d["Observé"] - d[c])) for u, c in zip(quantiles, cols_q)], axis=0)
    d["Dans 10-90"] = (d["Observé"] >= d["q10"]) & (d["Observé"] <= d["q90"]) if {"q10", "q90"} <= set(d.columns) else np.nan
    reference = float(np.sqrt((d.loc[d["Méthode"].eq("moyenne"), "Erreur"] ** 2).mean())) if d["Méthode"].eq("moyenne").any() else np.nan
    lignes = []
    for m, g in d.groupby("Méthode", sort=False):
        rmse = float(np.sqrt((g["Erreur"] ** 2).mean()))
        lignes.append({"Méthode": m, "Prévisions": len(g), "Écart quadratique relatif": rmse / reference if reference and np.isfinite(reference) else np.nan,
                       "Perte de quantile": float(g["Perte de quantile"].mean()), "Couverture 80 %": float(g["Dans 10-90"].astype(float).mean()),
                       "Biais": float(g["Erreur"].mean())})
    resume = pd.DataFrame(lignes).sort_values("Perte de quantile").reset_index(drop=True)
    return {"resume": resume, "detail": d[["Méthode", "FRU", "Semaine", "Observé", "Moyenne", *cols_q, "Perte de quantile"]]}


# --------------------------------------------------------------------------- mise en forme des séries
def series_hebdo(flux_fru: pd.DataFrame, ev: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Du suivi hebdomadaire aux séries : Y (FRU scrapées) et E (FRU arrivées à une décision), semaines complètes seulement.

    flux_fru : table « FRU scrapées par semaine » (Semaine, FRU, FRU scrapées, Semaine complète).
    ev       : consommations (Jour, PO, FRU ITEM) ; les réparations d'une semaine sont ses PO distincts. Une réparation
               qui n'a consommé aucune pièce n'y figure pas : E est un minorant des arrivées, donc le taux de scrap un majorant.
    """
    if flux_fru is None or not len(flux_fru):
        return pd.DataFrame(), None
    f = flux_fru[flux_fru["Semaine complète"].astype(bool)] if "Semaine complète" in flux_fru else flux_fru
    Y = f.pivot_table(index="FRU", columns="Semaine", values="FRU scrapées", aggfunc="sum", fill_value=0).sort_index(axis=1)
    if ev is None or not len(ev) or not {"Jour", "PO", "FRU ITEM"} <= set(ev.columns):
        return Y, None
    j = pd.to_datetime(ev["Jour"])
    sem = (j - pd.to_timedelta(j.dt.weekday, unit="D")).dt.normalize()
    rep = ev.assign(Semaine=sem).groupby(["FRU ITEM", "Semaine"])["PO"].nunique().unstack(fill_value=0)
    rep = rep.reindex(index=Y.index, columns=Y.columns, fill_value=0)
    return Y, rep + Y
