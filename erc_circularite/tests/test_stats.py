"""Modules statistiques : fiabilité (forme de Weibull sur défaillances précoces, taux, rapports), modèle de Rex,
suivi hebdomadaire du flux, risques. Données simulées à vérité connue, graines fixes."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from erc import fiabilite as F, flux as X, rex as R, risques as K  # noqa: E402


def precoces(rng, k, n, lam=400.0, fenetre=90):
    """Défaillances précoces seules : délais en jours entiers, observés uniquement dans la fenêtre (aucun survivant)."""
    out = []
    while len(out) < n:
        d = lam * rng.weibull(k, size=4 * n)
        out += list(np.floor(d[d < fenetre + 1]).astype(int))
    return np.array(out[:n])


# ------------------------------------------------------------------ fiabilité
@pytest.mark.parametrize("k", [0.6, 1.0, 2.0])
def test_forme_retrouvee_sur_grand_echantillon(k):
    r = F.weibull_tronque(precoces(np.random.default_rng(11), k, 3000), 90)
    assert abs(r["k"] - k) < 0.12 * k
    assert r["k bas (5 %)"] <= r["k"] <= r["k haut (95 %)"]
    assert not np.isfinite(r["lambda"]) or r["échelle"] != "identifiable"           # jamais de durée de vie tirée de ces données


@pytest.mark.parametrize("k, n", [(0.7, 20), (1.0, 40), (2.0, 40)])
def test_intervalle_couvre_la_vraie_forme(k, n):
    rng = np.random.default_rng(100 + int(10 * k) + n)
    reps, couverts, faux = 80, 0, 0
    for _ in range(reps):
        r = F.weibull_tronque(precoces(rng, k, n), 90)
        couverts += r["k bas (5 %)"] <= k <= r["k haut (95 %)"]
        lecture = F.lecture_forme(r["k"], r["k bas (5 %)"], r["k haut (95 %)"])
        faux += (k <= 1 and lecture.startswith("usure")) or (k >= 1 and lecture.startswith("mortalité"))
    assert couverts / reps >= 0.78                                                   # nominal 90 %, tolérance d'échantillonnage sur 80 répétitions
    assert faux / reps <= 0.10                                                       # une lecture affirmée et fausse reste rare


def test_trop_peu_de_defaillances_pas_de_forme():
    r = F.weibull_tronque(np.array([1, 5, 30]), 90)
    assert math.isnan(r["k"])
    assert F.lecture_forme(float("nan")).startswith("inconnu")


def test_lecture_de_la_forme_tient_compte_de_l_intervalle():
    assert F.lecture_forme(0.7, 0.5, 0.9).startswith("mortalité infantile")
    assert F.lecture_forme(2.0, 1.3, 2.8).startswith("usure")
    assert F.lecture_forme(1.2, 0.7, 1.9).startswith("indéterminé")
    assert F.lecture_forme(1.0, 0.9, 1.1).startswith("aléatoire")


def test_kaplan_meier_exemple_a_la_main():
    # durées 1, 2, 2 (censurée), 3 : S(1) = 3/4 ; S(2) = 3/4 x 2/3 = 1/2 ; S(3) = 0
    km = F.kaplan_meier([1, 2, 2, 3], [1, 1, 0, 1]).set_index("t")["S(t)"]
    assert math.isclose(km[1], 0.75) and math.isclose(km[2], 0.5) and math.isclose(km[3], 0.0)


def test_weibull_complet_et_censure():
    rng = np.random.default_rng(5)
    t = 1000 * rng.weibull(1.5, 4000)
    r = F.weibull_mle(np.minimum(t, 900), (t <= 900).astype(int))
    assert abs(r["k"] - 1.5) < 0.1 and abs(r["lambda"] - 1000) < 60


def test_survie_et_vie_residuelle():
    assert math.isclose(F.survie_conditionnelle(500, 365, 1.0, 1000), math.exp(-0.365), rel_tol=1e-9)
    assert math.isclose(F.vie_residuelle_moyenne(0, 1.0, 1000), 1000, rel_tol=2e-3)
    assert F.vie_residuelle_moyenne(800, 2.5, 1000) < F.vie_residuelle_moyenne(0, 2.5, 1000)       # usure : une pièce âgée a moins de vie devant elle
    assert F.vie_residuelle_moyenne(800, 0.7, 1000) > F.vie_residuelle_moyenne(0, 0.7, 1000)       # mortalité infantile : l'inverse


def test_taux_et_rapport():
    t = F.taux_bayes(5, 400)
    assert math.isclose(t["Taux ELF moyen"], 5.5 / 401) and t["IC90 bas"] < t["Taux ELF moyen"] < t["IC90 haut"]
    assert math.isnan(F.taux_bayes(5, None)["Taux ELF moyen"])                         # sans dénominateur : pas de taux
    r = F.rapport_taux(20, 400, 10, 500)
    assert r["Rapport bas (5 %)"] < r["Rapport au neuf (taux)"] < r["Rapport haut (95 %)"]
    assert r["Lecture du rapport"].startswith("moins fiable")
    assert F.rapport_taux(1, 30, 1, 30)["Lecture du rapport"].startswith("indéterminé")
    scipy = pytest.importorskip("scipy.stats")
    assert math.isclose(F.beta_quantile(0.05, 7, 3), scipy.beta.ppf(0.05, 7, 3), rel_tol=1e-9)


def test_fiabilite_par_reference_repetable():
    rng = np.random.default_rng(3)
    elf = pd.DataFrame({"replacement_part_no": ["P-1"] * 40 + ["P-1-R"] * 25, "elf_days": list(precoces(rng, 0.8, 65))})
    poses = pd.Series({("P-1", "Neuve"): 4000, ("P-1", "Réparée"): 1200})
    a, b = F.fiabilite_par_reference(elf, 90, poses), F.fiabilite_par_reference(elf, 90, poses)
    pd.testing.assert_frame_equal(a, b)
    assert set(a["Origine posée"]) == {"Neuve", "Réparée"}
    assert a.loc[a["Origine posée"].eq("Réparée"), "Rapport au neuf (taux)"].iloc[0] > 1


# ------------------------------------------------------------------ modèle de Rex
def _audit(q, lots=8, graine=1):
    rng = np.random.default_rng(graine)
    lignes = []
    for i in range(lots):
        for (f, p), v in q.items():
            n = int(rng.integers(4, 12))
            lignes.append({"Date": pd.Timestamp("2026-09-07") + pd.Timedelta(weeks=i), "Type de FRU": f, "Pièce": p,
                           "Pièces testées": n, "Pièces bonnes": int(rng.binomial(n, v))})
    return pd.DataFrame(lignes)


Q = {("A", "p1"): 0.55, ("A", "p2"): 0.2}
PRIOR = pd.DataFrame({"Type de FRU": ["A", "A"], "Pièce": ["p1", "p2"], "q0": [0.7, np.nan]})


def test_posterieur_algebre_et_repetabilite():
    p = R.posterieur(0.7, 6, 10, n0=10)
    assert math.isclose(p["q moyen"], (7 + 6) / (10 + 10)) and p["q bas (5 %)"] < p["q moyen"] < p["q haut (95 %)"]
    assert R.posterieur(0.7, 6, 10) == R.posterieur(0.7, 6, 10)                         # bornes exactes, sans tirage
    sans = R.posterieur(None, 0, 0)
    assert math.isclose(sans["q moyen"], 0.5) and sans["Poids des données"] == 0


def test_entrainement_converge_vers_la_verite():
    post = R.entrainer(_audit(Q, lots=60), PRIOR).set_index("Pièce")
    assert abs(post.at["p1", "q moyen"] - 0.55) < 0.06 and abs(post.at["p2", "q moyen"] - 0.2) < 0.05
    vide = R.entrainer(_audit(Q).iloc[:0], PRIOR)
    assert len(vide) == 2 and vide["Pièces testées"].eq(0).all()


def test_evaluation_sans_fuite():
    """Un lot ne doit pas influencer sa propre prédiction : changer son résultat ne change pas ce qui a été prédit pour lui."""
    a = _audit(Q)
    b = a.copy()
    dernier = b.index[-1]
    b.loc[dernier, "Pièces bonnes"] = b.loc[dernier, "Pièces testées"]                # résultat extrême sur le dernier lot
    da, db = R.evaluer(a, PRIOR)["detail"], R.evaluer(b, PRIOR)["detail"]
    cle = ["Modèle", "Date", "Type de FRU", "Pièce"]
    m = da.merge(db, on=cle, suffixes=("_a", "_b"))
    assert len(m) == len(da) and np.allclose(m["Prédit_a"], m["Prédit_b"])
    met = R.evaluer(a, PRIOR)["metriques"].set_index("Modèle")
    assert {"Bêta-binomial", "A priori seul", "Fréquence observée"} <= set(met.index)
    assert (met["Brier"] >= 0).all() and (met["Brier"] <= 1).all()
    pd.testing.assert_frame_equal(R.evaluer(a, PRIOR)["metriques"], R.evaluer(a, PRIOR)["metriques"])


def test_explorer_corrige_un_a_priori_pessimiste():
    t = R.simuler_politiques(q_vrai=0.6, q0=0.2, gain_bonne=40.0, gain_mauvaise=-12.0, gain_recyclage=2.0, n_pieces=300, n_sim=200)
    r = t.set_index("Politique")["Regret cumulé moyen (€)"]
    assert r["Thompson"] < 0.2 * r["Glouton"] and math.isclose(r["Glouton"], r["A priori seul"])
    assert math.isclose(t.attrs["Seuil q* (réemploi si q > q*)"], (2 + 12) / (40 + 12))


# ------------------------------------------------------------------ flux hebdomadaire
def _monde():
    jours = pd.date_range("2026-09-07", "2026-09-27")                                   # trois semaines complètes, lundi → dimanche
    ev = pd.DataFrame([{"Jour": j, "FRU ITEM": "F", "Component ITEM": p, "Qte": q}
                       for j in jours if j.weekday() < 5 for p, q in (("a", 4), ("b", 2), ("c", 1))])
    comp = pd.DataFrame({"Référence": ["a", "b", "c"], "Benne": ["DEEE", "DEEE", "DIB"], "Type de déchet": ["Carte", "Câble", "Plastique"],
                         "Poids unitaire (kg)": [0.5, np.nan, np.nan]})
    return ev, comp, set(jours)


def test_estimation_bornes_et_inconnu():
    ev, comp, couverts = _monde()
    est = X.estimation_hebdo(ev, comp, couverts).set_index(["Flux", "Semaine"])
    deee = est.loc["DEEE"].iloc[0]
    assert math.isclose(deee["Estimé bas (kg)"], 5 * 4 * 0.5)                           # seule la pièce au poids connu
    assert math.isclose(deee["Couverture poids"], 4 / 6)
    assert math.isclose(deee["Estimé haut (kg)"], 10 / (4 / 6))                         # les autres au poids moyen du flux
    assert deee["Estimé bas (kg)"] <= deee["Estimé central (kg)"] <= deee["Estimé haut (kg)"]
    dib = est.loc["DIB"].iloc[0]
    assert math.isnan(dib["Estimé bas (kg)"]) and math.isnan(dib["Estimé central (kg)"])   # aucun poids connu : masse inconnue, pas nulle


def test_rapprochement_marge_cause_et_cumul():
    ev, comp, couverts = _monde()
    est = X.estimation_hebdo(ev, comp, couverts)
    pes = pd.DataFrame({"Semaine": ["11/09/2026", "18/09/2026", "25/09/2026", "25/09/2026"], "Flux": ["DEEE", "DEEE", "DEEE", "Inconnue"],
                        "Masse mesurée (kg)": [12.0, 40.0, 9.8, 3.0], "Incertitude mesure (kg)": [0.5, 0.5, 0.5, 0.5],
                        "Cause constatée": ["", "benne vidée en retard", "", ""]})
    rap = X.rapprocher(est, pes)
    d = rap[rap["Flux"].eq("DEEE")].sort_values("Semaine").reset_index(drop=True)
    assert list(d["Dans la marge"]) == ["oui", "non", "oui"]                              # 12 dans [10 ; 15], 40 au-dessus, 9,8 à 0,5 kg près
    assert d.loc[1, "Écart (kg)"] > 0 and "mesuré > estimé" in d.loc[1, "Causes candidates de l'écart"]
    assert d.loc[1, "Cause constatée (à saisir)"] == "benne vidée en retard"            # la saisie de l'atelier est reportée
    assert rap["Flux"].eq("Inconnue").any()                                             # une pesée sans estimation n'est pas perdue
    assert rap.loc[rap["Flux"].eq("DIB"), "Dans la marge"].eq("non comparable").all()   # un flux jamais pesé reste visible


def test_fru_scrapees_par_semaine_et_scrap_annuel():
    couverts = set(pd.date_range("2026-09-07", "2026-10-06"))                           # 4 semaines complètes + 2 jours
    fr = pd.DataFrame({"Date scrap": pd.to_datetime(["2026-09-08", "2026-09-09", "2026-09-22", "2026-10-06", "2026-11-30"]),
                       "FRU": ["F"] * 5, "Unités": [1, 2, 4, 1, 9]})
    f = X.flux_fru_hebdo(fr, couverts, pd.Series({"F": 10.0})).sort_values("Semaine").reset_index(drop=True)
    assert list(f["FRU scrapées"]) == [3, 0, 4, 0, 1]                                    # semaines sans scrap = 0 ; scrap hors période écarté
    assert list(f["Semaine complète"]) == [True, True, True, True, False]
    assert (f["Semaine"].dt.weekday == 0).all() and math.isclose(f["Masse estimée (kg)"].sum(), 80.0)
    a, b = X.scrap_annuel(f), X.scrap_annuel(f)
    pd.testing.assert_frame_equal(a.drop(columns="scrap_an"), b.drop(columns="scrap_an"))
    r = a.iloc[0]
    assert r["Semaines complètes"] == 4 and math.isclose(r["Scrap annuel moyen"], (3 + 0 + 4 + 0) / 4 * 52)
    assert r["Scrap annuel bas (5 %)"] <= r["Scrap annuel moyen"] <= r["Scrap annuel haut (95 %)"]


# ------------------------------------------------------------------ risques
@pytest.mark.parametrize("description, attendu", [
    ("IGBT 400A 1200V", "IGBT / module de puissance"), ("Gate Driver Board", "Carte électronique"), ("Carte de commande", "Carte électronique"),
    ("AL Electrolytic Capacitor 450V 4700uF", "Condensateur électrolytique"), ("Protection fuse 100A", "Fusible"),
    ("Cable harness", "Câble / faisceau"), ("Cooling fan 120mm", "Ventilateur / moteur"), ("Coque boîtier gris", "Pièce plastique / mécanique"),
    ("Objet sans rapport", "(type non reconnu)"),
])
def test_type_de_piece(description, attendu):
    assert K.type_piece(description) == attendu


def test_tables_de_risque_coherentes():
    assert K.STRATEGIQUES_UE <= K.CRM_UE                                                # toute matière stratégique est aussi critique
    r = K.risque_matiere("Gate Driver Board")
    assert 0 <= r["Score risque matière (0-1)"] <= 1 and r["Métaux précieux"]
    assert math.isnan(K.risque_matiere("Objet sans rapport")["Score risque matière (0-1)"])
    assert math.isnan(K.risque_supply("X")["Score risque supply (0-1)"])                 # sans délai fourni : inconnu


def test_front_de_pareto_contre_definition():
    rng = np.random.default_rng(2)
    df = pd.DataFrame(rng.integers(0, 5, (40, 3)).astype(float), columns=list("abc"))
    df.loc[3, "a"] = np.nan
    X_ = df.fillna(-np.inf).to_numpy()
    attendu = [not any(np.all(X_[j] >= X_[i]) and np.any(X_[j] > X_[i]) for j in range(len(X_))) for i in range(len(X_))]
    assert list(K.front_pareto(df, list("abc"))) == attendu
