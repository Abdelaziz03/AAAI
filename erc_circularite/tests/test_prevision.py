"""Prévision du flux hebdomadaire de FRU scrapées : méthodes pour séries intermittentes, lois prédictives, évaluation."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from erc import prevision as PV  # noqa: E402


def semaines(n):
    return list(pd.date_range("2026-01-05", periods=n, freq="W-MON"))


def test_croston_a_la_main():
    y = [0, 0, 5, 0, 0, 5]                                    # arrivées de 5 tous les 3 semaines
    assert math.isclose(PV.croston(y), 5 / 3)
    assert math.isclose(PV.croston(y, variante="sba"), 0.95 * 5 / 3)
    assert PV.croston([0, 0, 0]) == 0.0 and PV.croston([]) == 0.0
    actif, eteint = PV.croston([4, 4, 4, 4], variante="tsb"), PV.croston([4, 4, 4, 4] + [0] * 30, variante="tsb")
    assert math.isclose(actif, 4.0) and eteint < 0.3          # TSB suit une extinction ; Croston resterait à 4
    assert math.isclose(PV.croston([4, 4, 4, 4] + [0] * 30), 4.0)


def test_previsions_repetables_et_coherentes():
    rng = np.random.default_rng(1)
    Y = pd.DataFrame(rng.poisson([[3.0], [0.4], [0.0]], (3, 26)), index=["A", "B", "C"], columns=semaines(26))
    p1, p2 = PV.prevoir(Y), PV.prevoir(Y)
    pd.testing.assert_frame_equal(p1, p2)
    assert set(p1["Méthode"]) == set(PV.METHODES) - {"structurel"}                       # sans série d'arrivées, pas de modèle structurel
    q = p1[["q10", "q25", "q50", "q75", "q90"]].to_numpy()
    assert (np.diff(q, axis=1) >= 0).all() and (p1["Moyenne"] >= 0).all()
    gp = p1[p1["Méthode"].eq("gamma_poisson")].set_index("FRU")["Moyenne"]
    assert 0 < gp["C"] < gp["B"] < gp["A"]                    # le type sans historique est tiré vers les autres, sans les rejoindre
    assert p1[p1["Méthode"].eq("moyenne")].set_index("FRU")["Moyenne"]["C"] == 0.0


def test_evaluation_sans_fuite_et_couverture():
    rng = np.random.default_rng(2)
    Y = pd.DataFrame(rng.poisson(2.5, (4, 40)), index=list("ABCD"), columns=semaines(40))
    ev = PV.evaluer(Y, methodes=("moyenne", "gamma_poisson"))
    r = ev["resume"].set_index("Méthode")
    assert math.isclose(r.at["moyenne", "Écart quadratique relatif"], 1.0)
    assert 0.7 <= r.at["moyenne", "Couverture 80 %"] <= 1.0 and r.at["moyenne", "Prévisions"] == 4 * 32
    Z = Y.copy()
    Z.iloc[:, -1] = 99                                        # une valeur extrême la dernière semaine
    a, b = ev["detail"], PV.evaluer(Z, methodes=("moyenne", "gamma_poisson"))["detail"]
    derniere = a["Semaine"].eq(Y.columns[-1])
    assert np.allclose(a.loc[derniere, "Moyenne"].to_numpy(), b.loc[b["Semaine"].eq(Y.columns[-1]), "Moyenne"].to_numpy())
    assert len(PV.evaluer(Y.iloc[:, :6])["resume"]) == 0      # trop peu de semaines : pas d'évaluation, pas de faux chiffre


def test_structurel_suit_un_changement_de_niveau():
    """Les arrivées doublent à mi-parcours : le modèle structurel, qui lit les arrivées récentes, s'adapte ; la moyenne non."""
    rng = np.random.default_rng(3)
    arrivees = np.r_[np.full(30, 20), np.full(30, 60)]
    E = pd.DataFrame(rng.poisson(arrivees, (5, 60)), index=list("ABCDE"), columns=semaines(60))
    Y = pd.DataFrame(rng.binomial(E.to_numpy(), 0.2), index=E.index, columns=E.columns)
    r = PV.evaluer(Y, E, methodes=("moyenne", "structurel"), depart=35)["resume"].set_index("Méthode")
    assert r.at["structurel", "Écart quadratique relatif"] < 0.9
    assert r.at["structurel", "Perte de quantile"] < r.at["moyenne", "Perte de quantile"]


def test_modele_externe_et_series():
    PV.enregistrer_modele("test", lambda h, q: (float(h[-1]), {u: float(h[-1]) for u in q}))
    try:
        Y = pd.DataFrame([[1, 2, 3, 4]], index=["A"], columns=semaines(4))
        p = PV.prevoir(Y, methodes=("test",))
        assert p.loc[0, "Moyenne"] == 4.0
        with pytest.raises(ValueError):
            PV.prevoir(Y, methodes=("inconnue",))
    finally:
        PV.MODELES_EXTERNES.pop("test")
    s = semaines(3)
    flux = pd.DataFrame({"Semaine": s * 2, "FRU": ["A"] * 3 + ["B"] * 3, "FRU scrapées": [1, 0, 2, 0, 0, 1], "Semaine complète": [True, True, False] * 2})
    ev = pd.DataFrame({"Jour": [s[0], s[0], s[1]], "PO": ["1", "2", "3"], "FRU ITEM": ["A", "A", "B"]})
    Y, E = PV.series_hebdo(flux, ev)
    assert list(Y.columns) == s[:2] and Y.loc["A"].tolist() == [1, 0]                    # la semaine incomplète est écartée
    assert E.loc["A"].tolist() == [3, 0] and E.loc["B"].tolist() == [0, 1]               # arrivées = réparations + FRU scrapées


def test_methodes_notees_sur_les_memes_previsions():
    """Un type sans arrivées n'est pas prévu par le modèle structurel : il ne compte alors pour aucune méthode."""
    rng = np.random.default_rng(4)
    E = pd.DataFrame(rng.poisson(30, (5, 30)), index=list("ABCDE"), columns=semaines(30))
    Y = pd.DataFrame(rng.binomial(E.to_numpy(), 0.2), index=E.index, columns=E.columns)
    E.loc["E"] = 0                                             # arrivées inconnues pour ce type
    Y.loc["E"] = rng.poisson(50, 30)                          # et un flux très différent : il fausserait la référence
    r = PV.evaluer(Y, E, methodes=("moyenne", "structurel"), depart=8)["resume"].set_index("Méthode")
    assert r.at["moyenne", "Prévisions de la méthode"] == 5 * 22 and r.at["structurel", "Prévisions de la méthode"] == 4 * 22
    assert r.at["moyenne", "Prévisions"] == r.at["structurel", "Prévisions"] == 4 * 22
    seuls = PV.evaluer(Y.drop("E"), E.drop("E"), methodes=("moyenne", "structurel"), depart=8)["resume"].set_index("Méthode")
    assert math.isclose(r.at["structurel", "Écart quadratique relatif"], seuls.at["structurel", "Écart quadratique relatif"], rel_tol=0.02)
    # une série d'arrivées plus longue que celle des FRU scrapées est alignée par ses semaines, pas par sa position
    plus_long = pd.concat([pd.DataFrame(7, index=E.index, columns=[pd.Timestamp("2025-12-29")]), E], axis=1)
    r2 = PV.evaluer(Y, plus_long, methodes=("moyenne", "structurel"), depart=8)["resume"].set_index("Méthode")
    assert math.isclose(r2.at["structurel", "Perte de quantile"], r.at["structurel", "Perte de quantile"])


def test_a_priori_entre_types():
    """La loi a priori d'un type vient des autres types, hasard de comptage retiré. Vingt types de même taux : mise en
    commun presque complète. Moins de deux autres types : a priori faible, les données du type ne servent pas deux fois."""
    rng = np.random.default_rng(5)
    forces = []
    for _ in range(100):
        arrivees = np.full(19, 30.0)
        a, b = PV._moments_beta(rng.binomial(30, 0.2, 19).astype(float), arrivees)
        forces.append(a + b)
    assert np.median(forces) > 200                             # sans retirer la variance binomiale, la force restait vers 30
    assert PV._moments_beta(np.array([5.0]), np.array([26.0])) == (0.5, 0.5) and PV._moments_beta(np.array([]), np.array([])) == (0.5, 0.5)
    a, b = PV._moments_beta(np.array([2.0, 30.0, 12.0]), np.array([40.0, 40.0, 40.0]))      # types qui diffèrent vraiment : a priori large
    assert a + b < 10 and math.isclose(a / (a + b), 44 / 120)
    assert PV._moments_gamma(np.array([12.0]), 26) == (0.5, 0.0)
    a, b = PV._moments_gamma(np.array([26.0, 27.0, 25.0]), 26)                              # même taux : taux commun, précision des données réunies
    assert math.isclose(a, 78.5) and math.isclose(b, 78.0)
    Y = pd.DataFrame([[2, 0, 1, 3, 0, 2, 1, 1]], index=["A"], columns=semaines(8))          # un seul type : sa moyenne, à un demi près
    seul = PV.prevoir(Y, methodes=("gamma_poisson",))
    assert math.isclose(seul.loc[0, "Moyenne"], (0.5 + 10) / 8)


def test_moyennes_exactes_graines_par_methode_et_valeurs_manquantes():
    rng = np.random.default_rng(6)
    Y = pd.DataFrame(rng.poisson([[3.0], [0.4], [1.2]], (3, 26)), index=["A", "B", "C"], columns=semaines(26))
    tout, seule = PV.prevoir(Y), PV.prevoir(Y, methodes=("gamma_poisson",))
    pd.testing.assert_frame_equal(tout[tout["Méthode"].eq("gamma_poisson")].reset_index(drop=True), seule)   # ne dépend pas des autres méthodes
    m = tout[tout["Méthode"].eq("moyenne")].set_index("FRU")["Moyenne"]
    assert np.allclose(m.to_numpy(), Y.mean(axis=1).to_numpy())                            # moyenne exacte, pas celle d'un tirage
    c = tout[tout["Méthode"].eq("croston")].set_index("FRU")["Moyenne"]
    assert math.isclose(c["B"], PV.croston(Y.loc["B"]))
    Z = Y.astype(float)
    Z.iloc[0, 3] = np.nan
    with pytest.raises(ValueError, match="sans valeur"):
        PV.prevoir(Z)
