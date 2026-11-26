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
  gamma_poisson  taux propre à chaque type, tiré vers le taux des AUTRES types ; loi binomiale négative
  structurel     FRU scrapées = FRU arrivées à une décision × taux de scrap ; taux tiré vers celui des AUTRES types,
                 arrivées prévues par leur moyenne récente ; loi bêta-binomiale. Demande la série des arrivées.
Pour ces deux méthodes, la loi a priori d'un type est estimée sur les autres types seulement (ses propres données ne
servent qu'une fois), et la variance due au hasard de comptage est retirée de la dispersion observée entre types. Avec
moins de deux autres types utilisables, l'a priori est faible et non informatif.

Évaluation à origine glissante, une semaine à l'avance : chaque semaine est prévue avec les seules semaines précédentes.
  Écart quadratique relatif  racine de l'erreur quadratique moyenne, rapportée à celle de la méthode « moyenne »
                             (< 1 = meilleure). L'erreur absolue n'est pas utilisée : elle est minimisée par la
                             médiane, qui vaut zéro dès que plus d'une semaine sur deux est vide.
  Perte de quantile          moyenne des pertes de quantile (pinball) sur la grille : note la loi entière, pas un point
  Couverture 80 %            part des semaines dont la valeur tombe entre les quantiles 10 % et 90 % (cible ≈ 80 %,
                             au-dessus pour des comptages, les quantiles étant des entiers)

Les méthodes sont notées sur les mêmes prévisions : seules comptent les (type, semaine) que toutes ont su prévoir.
La moyenne prévue est calculée exactement ; les quantiles par simulation à graine fixe, propre à chaque type et à
chaque méthode : deux exécutions donnent les mêmes nombres, quelles que soient les autres méthodes demandées.
"""
from __future__ import annotations

import zlib

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
def _quantiles(tirages: np.ndarray, quantiles=QUANTILES) -> dict:
    return {u: float(np.quantile(tirages, u)) for u in quantiles}


def _moments_gamma(comptes: np.ndarray, semaines: int) -> tuple[float, float]:
    """Loi Gamma(forme, cadence) du taux hebdomadaire d'un type, estimée sur les comptes totaux d'AUTRES types observés
    `semaines` semaines. La variance d'échantillonnage (m / semaines) est retirée de la dispersion entre types.
    Moins de deux types : a priori faible. Types qui ne diffèrent pas plus que le hasard : leur taux commun, connu
    avec la précision que donnent leurs données réunies."""
    comptes = np.asarray(comptes, float)
    if len(comptes) < 2 or semaines <= 0:
        return 0.5, 0.0
    taux = comptes / semaines
    m, v = float(taux.mean()), float(taux.var(ddof=1))
    exces = v - m / semaines
    if m <= 0 or exces <= 1e-12:
        return float(comptes.sum()) + 0.5, float(len(comptes) * semaines)
    a = m * m / exces
    return a, a / m


def _moments_beta(scrapes: np.ndarray, arrivees: np.ndarray) -> tuple[float, float]:
    """Loi Bêta du taux de scrap d'un type, estimée sur d'AUTRES types (FRU scrapées, FRU arrivées à une décision).
    Moments pondérés par les effectifs ; la variance binomiale attendue est retirée de la dispersion entre types.
    Moins de deux types : a priori faible. Types qui ne diffèrent pas plus que le hasard : leur taux commun."""
    scrapes, arrivees = np.asarray(scrapes, float), np.asarray(arrivees, float)
    if len(arrivees) < 2 or arrivees.sum() <= 0:
        return 0.5, 0.5
    p, total = scrapes / arrivees, float(arrivees.sum())
    m = float(scrapes.sum() / total)
    commun = (float(scrapes.sum()) + 0.5, total - float(scrapes.sum()) + 0.5)
    if not 0 < m < 1:
        return commun
    v = float(np.average((p - m) ** 2, weights=arrivees)) - len(arrivees) * m * (1 - m) / total
    if v <= 1e-12:
        return commun
    force = m * (1 - m) / min(v, m * (1 - m) * 0.99) - 1
    return m * force, (1 - m) * force


def _suite(graine: int, i: int, methode: str):
    """Suite aléatoire propre à un type et à une méthode : demander une méthode de plus ne change pas les autres."""
    return np.random.default_rng([graine, i, zlib.crc32(methode.encode("utf-8"))])


def prevoir(Y: pd.DataFrame, E: pd.DataFrame | None = None, methodes=METHODES, quantiles=QUANTILES, graine: int = 2026, recent: int = 8) -> pd.DataFrame:
    """Prévision de la semaine suivante pour chaque type.

    Y : comptages hebdomadaires, une ligne par type, une colonne par semaine (dans l'ordre du temps), sans valeur manquante.
    E : FRU arrivées à une décision (réparées + scrapées), alignées sur Y par leurs étiquettes ; requis par « structurel ».
    """
    lignes = []
    y = Y.to_numpy(float)
    n_types, T = y.shape if y.ndim == 2 else (0, 0)
    if not n_types or not T:
        return pd.DataFrame(columns=["FRU", "Méthode", "Moyenne", *[f"q{int(100 * u)}" for u in quantiles]])
    if not np.isfinite(y).all():
        raise ValueError("Prévision : la série contient des semaines sans valeur. Les retirer, ou les mettre à zéro si aucun FRU n'a été scrapé.")
    totaux = y.sum(axis=1)
    e = E.reindex(index=Y.index, columns=Y.columns).to_numpy(float) if E is not None else None
    if e is not None:
        ok = np.isfinite(e).all(axis=1) & (e.sum(axis=1) > 0)
        tot_e, tot_y = np.where(ok, e.sum(axis=1), 0.0), np.where(ok, np.minimum(totaux, e.sum(axis=1)), 0.0)
    for i, fru in enumerate(Y.index):
        h = y[i]
        autres = np.arange(n_types) != i
        for m in methodes:
            rng = _suite(graine, i, m)
            if m == "moyenne":
                moy = float(h.mean())
                q = _quantiles(rng.poisson(max(moy, 0.0), N_SIM), quantiles)
            elif m in ("croston", "sba", "tsb"):
                moy = croston(h, variante=m)
                q = _quantiles(rng.poisson(max(moy, 0.0), N_SIM), quantiles)
            elif m == "gamma_poisson":
                a, b = _moments_gamma(totaux[autres], T)
                moy = float((a + h.sum()) / (b + T))
                q = _quantiles(rng.poisson(rng.gamma(a + h.sum(), 1.0 / (b + T), N_SIM)), quantiles)
            elif m == "structurel":
                if e is None or not ok[i]:
                    continue                                      # sans série d'arrivées : la méthode n'est pas calculée
                al, be = _moments_beta(tot_y[autres & ok], tot_e[autres & ok])
                arrivees_prevues = max(float(e[i, -recent:].mean()), 0.0)
                moy = arrivees_prevues * float((al + tot_y[i]) / (al + be + tot_e[i]))
                taux = rng.beta(al + tot_y[i], be + tot_e[i] - tot_y[i], N_SIM)
                q = _quantiles(rng.binomial(rng.poisson(arrivees_prevues, N_SIM), taux), quantiles)
            elif m in MODELES_EXTERNES:
                moy, q = MODELES_EXTERNES[m](h.copy(), tuple(quantiles))
            else:
                raise ValueError(f"Méthode de prévision inconnue : {m}")
            lignes.append({"FRU": fru, "Méthode": m, "Moyenne": moy, **{f"q{int(100 * u)}": q[u] for u in quantiles}})
    return pd.DataFrame(lignes)


# --------------------------------------------------------------------------- évaluation à origine glissante
def evaluer(Y: pd.DataFrame, E: pd.DataFrame | None = None, methodes=METHODES, depart: int = 8, quantiles=QUANTILES, graine: int = 2026) -> dict:
    """Chaque semaine à partir de `depart` est prévue avec les semaines précédentes seulement.
    Renvoie {"resume": une ligne par méthode, "detail": une ligne par (méthode, type, semaine)}.
    Les notes du résumé portent sur les (type, semaine) prévus par TOUTES les méthodes : une méthode qui ne sait pas
    prévoir certains types (« structurel » sans arrivées) n'est pas comparée sur un autre jeu que les autres.
    « Prévisions » est ce nombre commun ; « Prévisions de la méthode » dit ce que chacune a su prévoir."""
    cols_q = [f"q{int(100 * u)}" for u in quantiles]
    vide = {"resume": pd.DataFrame(columns=["Méthode", "Prévisions", "Prévisions de la méthode", "Écart quadratique relatif", "Perte de quantile", "Couverture 80 %", "Biais"]),
            "detail": pd.DataFrame(columns=["Méthode", "FRU", "Semaine", "Observé", "Moyenne", *cols_q])}
    T = Y.shape[1]
    if T <= depart or not len(Y):
        return vide
    morceaux = []
    for t in range(depart, T):
        p = prevoir(Y.iloc[:, :t], None if E is None else E.reindex(columns=Y.columns[:t]), methodes, quantiles, graine)
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
    # mêmes prévisions pour toutes : les (type, semaine) que chaque méthode a su prévoir
    propres = d.groupby("Méthode", sort=False).size()
    nb = d.groupby(["FRU", "Semaine"])["Méthode"].nunique()
    communs = nb[nb == d["Méthode"].nunique()].index
    c = d[pd.MultiIndex.from_frame(d[["FRU", "Semaine"]]).isin(communs)]
    reference = float(np.sqrt((c.loc[c["Méthode"].eq("moyenne"), "Erreur"] ** 2).mean())) if c["Méthode"].eq("moyenne").any() else np.nan
    lignes = []
    for m in propres.index:
        g = c[c["Méthode"].eq(m)]
        rmse = float(np.sqrt((g["Erreur"] ** 2).mean())) if len(g) else np.nan
        lignes.append({"Méthode": m, "Prévisions": len(g), "Prévisions de la méthode": int(propres[m]),
                       "Écart quadratique relatif": rmse / reference if reference and np.isfinite(reference) else np.nan,
                       "Perte de quantile": float(g["Perte de quantile"].mean()) if len(g) else np.nan,
                       "Couverture 80 %": float(g["Dans 10-90"].astype(float).mean()) if len(g) else np.nan,
                       "Biais": float(g["Erreur"].mean()) if len(g) else np.nan})
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
