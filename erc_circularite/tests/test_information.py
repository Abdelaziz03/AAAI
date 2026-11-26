"""Valeur de l'information, et vérification numérique des propositions de docs/Formal_framework.md sur des cas tirés au hasard."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from erc import information as I, ligne as L  # noqa: E402

V = "Marge variable / an (€)"


def une_piece(prix=3.0, **plus):
    """Un type de FRU, une pièce, sans réemploi possible : seul le tri (6 min à 40 €/h = 4 €) est en jeu. 2 kg par pièce."""
    ligne = {"taux_horaire_eur": 40.0, "cout_traitement_eur_kg": 0.0, "heures_operateur_an": None,
             "cout_installation_eur": 0.0, "amortissement_ans": 5, "couts_fixes_annuels_eur": 0.0}
    frus = {"F": {"scrap_an": 100.0, "poids_fru_kg": 10.0, "ouverture_min": 0.0,
                  "pieces": {"p": dict({"n_par_fru": 1, "poids_kg": 2.0, "prix_recycleur_eur_kg": prix, "tri_min": 6.0}, **plus)}}}
    return ligne, frus


# ------------------------------------------------------------------ valeur de l'information
def test_evpi_exemple_a_la_main():
    """Prix 1 ou 5 €/kg à parts égales. À 1 € : 2 − 4 < 0, on laisse (0). À 5 € : 10 − 4 = 6 par pièce (600).
    Sans information, prix moyen 3 € : 6 − 4 = 2 par pièce (200). Avec : 0,5 × 0 + 0,5 × 600 = 300. Valeur : 100."""
    ligne, frus = une_piece()
    r = I.evpi(ligne, frus, "F", "p", "prix_recycleur_eur_kg", [1.0, 5.0])
    assert math.isclose(r["Valeur sans information (€/an)"], 200.0)
    assert math.isclose(r["Valeur avec information (€/an)"], 300.0)
    assert math.isclose(r["Valeur de l'information (€/an)"], 100.0)
    assert r["La décision change"] is True
    borne = I.borne_prix(100, 1, 2.0, [1.0, 5.0])
    assert math.isclose(borne, 100 * 1 * 2.0 * 2.0) and borne >= r["Valeur de l'information (€/an)"]


def test_evpi_nulle_quand_la_decision_ne_change_pas():
    ligne, frus = une_piece()
    r = I.evpi(ligne, frus, "F", "p", "prix_recycleur_eur_kg", [4.0, 6.0])              # on trie dans les deux cas
    assert math.isclose(r["Valeur de l'information (€/an)"], 0.0, abs_tol=1e-9) and r["La décision change"] is False


def test_inconnu_reste_inconnu():
    ligne, frus = une_piece()
    assert math.isnan(I.borne_prix(None, 1, 2.0, [1, 5])) and math.isnan(I.borne_prix(100, 1, None, [1, 5]))
    assert math.isnan(I.evpi(ligne, frus, "F", "absente", "prix_recycleur_eur_kg", [1, 5])["Valeur de l'information (€/an)"])
    ligne["taux_horaire_eur"] = None                                                     # modèle non calculable
    assert math.isnan(I.evpi(ligne, frus, "F", "p", "prix_recycleur_eur_kg", [1, 5])["Valeur de l'information (€/an)"])


def test_priorites_borne_puis_calcul():
    ligne, frus = une_piece()
    inc = pd.DataFrame([{"Type de FRU": "F", "Pièce": "p", "Paramètre": "prix_recycleur_eur_kg", "Valeurs": [1.0, 5.0], "Probabilités": None}])
    t = I.priorites(ligne, frus, inc, cout_information=50.0)
    assert t.loc[0, "Calcul exact"] == "oui" and bool(t.loc[0, "À acquérir"]) and math.isclose(t.loc[0, "Valeur de l'information (€/an)"], 100.0)
    t = I.priorites(ligne, frus, inc, cout_information=1000.0)                            # la borne (400) est sous le coût : pas de calcul
    assert t.loc[0, "Calcul exact"].startswith("non") and not bool(t.loc[0, "À acquérir"])


def test_scenarios_beta():
    x, p = I.scenarios_beta(7, 3, 9)
    assert len(x) == 9 and math.isclose(p.sum(), 1.0) and abs(float(p @ x) - 0.7) < 0.01 and (np.diff(x) > 0).all()


# ------------------------------------------------------------------ propositions, sur des cas tirés au hasard
def cas(rng, n_types=3, heures=None):
    ligne = {"taux_horaire_eur": float(rng.uniform(30, 60)), "cout_traitement_eur_kg": float(rng.uniform(0, 0.5)), "heures_operateur_an": heures,
             "cout_installation_eur": 0.0, "amortissement_ans": 5, "couts_fixes_annuels_eur": 0.0}
    frus = {}
    for i in range(n_types):
        pieces = {f"p{j}": {"n_par_fru": int(rng.integers(1, 4)), "extraction_min": float(rng.uniform(2, 15)), "test_min": float(rng.uniform(1, 20)),
                            "tri_min": float(rng.uniform(0.2, 3)), "p_reutilisable": float(rng.uniform(0.1, 0.9)), "valeur_eur": float(rng.uniform(5, 300)),
                            "poids_kg": float(rng.uniform(0.05, 1.0)), "prix_recycleur_eur_kg": float(rng.uniform(0.1, 10))}
                  for j in range(int(rng.integers(1, 5)))}
        frus[f"F{i}"] = {"scrap_an": float(rng.integers(10, 400)), "poids_fru_kg": float(rng.uniform(3, 80)),
                         "ouverture_min": float(rng.uniform(10, 60)), "ouverture_tri_min": float(rng.uniform(2, 10)), "pieces": pieces}
    return ligne, frus


def valeur(ligne, frus):
    return L.optimiser_ligne(ligne, frus)["resume"]


@pytest.mark.parametrize("graine", range(12))
def test_proposition_2_concavite_et_valeur_d_une_heure(graine):
    rng = np.random.default_rng(graine)
    ligne, frus = cas(rng)
    besoin = valeur(ligne, frus)["Heures utilisées / an"]
    grille = np.linspace(0, 1.3 * besoin, 14)
    v = np.array([valeur(dict(ligne, heures_operateur_an=float(h)), frus)[V] for h in grille])
    assert (np.diff(v) >= -1e-7).all()                                                   # croissante en heures
    assert (np.diff(v, 2) <= 1e-6 * max(1.0, v.max())).all()                             # concave
    for h in grille[1:-1]:                                                               # sur-gradient : V(H') ≤ V(H) + μ (H' − H)
        r = valeur(dict(ligne, heures_operateur_an=float(h)), frus)
        mu = r["Valeur d'une heure opérateur en plus (€ net)"]
        assert (v <= r[V] + mu * (grille - h) + 1e-6 * max(1.0, v.max())).all()


@pytest.mark.parametrize("graine", range(12))
def test_proposition_3_au_plus_un_type_partage(graine):
    rng = np.random.default_rng(100 + graine)
    ligne, frus = cas(rng, n_types=5)
    besoin = valeur(ligne, frus)["Heures utilisées / an"]
    d = L.optimiser_ligne(dict(ligne, heures_operateur_an=float(rng.uniform(0.1, 0.9)) * besoin), frus)["detail"]
    plans = d[d["FRU traitées / an"] > 1e-9].groupby("Type de FRU").size()
    partages = d.groupby("Type de FRU").size()
    assert (partages <= 2).all() and int((partages == 2).sum()) <= 1 and (plans <= 2).all()


@pytest.mark.parametrize("graine", range(30))
def test_proposition_4_seuil_de_reemploi(graine):
    """Un FRU ouvert sans coût, une pièce : le réemploi est retenu exactement quand q dépasse le seuil q† (heures libres, μ = 0)."""
    rng = np.random.default_rng(200 + graine)
    w, tau = float(rng.uniform(30, 60)), float(rng.uniform(0, 0.5))
    v, m, p = float(rng.uniform(20, 200)), float(rng.uniform(0.1, 2)), float(rng.uniform(0.1, 8))
    kappa, t_r, t_s = float(rng.uniform(0, 3)), float(rng.uniform(5, 30)) / 60, float(rng.uniform(0.2, 4)) / 60
    seuil = (kappa + w * t_r - min(w * t_s, m * (p + tau))) / (v - m * p)
    for q in (seuil - 0.03, seuil + 0.03):
        if not 0 < q < 1:
            continue
        ligne = {"taux_horaire_eur": w, "cout_traitement_eur_kg": tau, "heures_operateur_an": None}
        frus = {"F": {"scrap_an": 10.0, "ouverture_min": 0.0, "ouverture_tri_min": 0.0,
                      "pieces": {"p": {"n_par_fru": 1, "extraction_min": 0.0, "test_min": t_r * 60, "tri_min": t_s * 60, "p_reutilisable": q,
                                       "valeur_eur": v, "transport_eur": kappa, "poids_kg": m, "prix_recycleur_eur_kg": p}}}}
        d = L.optimiser_ligne(ligne, frus)["detail"].iloc[0]
        assert (d["1 Réemploi"] == "p") == (q > seuil), (q, seuil, d["1 Réemploi"], d["2 Recyclage"])


@pytest.mark.parametrize("graine", range(12))
def test_proposition_5_borne_fluide(graine):
    """La valeur au flux moyen majore la moyenne des valeurs semaine par semaine (inégalité de Jensen, V concave en N)."""
    rng = np.random.default_rng(300 + graine)
    ligne, frus = cas(rng)
    besoin = valeur(ligne, frus)["Heures utilisées / an"]
    ligne["heures_operateur_an"] = float(rng.uniform(0.3, 1.0)) * besoin / 52          # heures d'une semaine
    semaines = [{f: float(rng.poisson(d["scrap_an"] / 52) * rng.choice([0, 1, 2])) for f, d in frus.items()} for _ in range(40)]
    par_semaine = np.mean([valeur(ligne, {f: dict(d, scrap_an=s[f]) for f, d in frus.items()})[V] for s in semaines])
    moyen = {f: dict(d, scrap_an=float(np.mean([s[f] for s in semaines]))) for f, d in frus.items()}
    assert par_semaine <= valeur(ligne, moyen)[V] + 1e-6


@pytest.mark.parametrize("graine", range(12))
def test_proposition_6_convexite_et_borne(graine):
    rng = np.random.default_rng(400 + graine)
    ligne, frus = cas(rng)
    f = "F0"
    pc = next(iter(frus[f]["pieces"]))
    e = frus[f]["pieces"][pc]
    besoin = valeur(ligne, frus)["Heures utilisées / an"]
    ligne["heures_operateur_an"] = float(rng.uniform(0.3, 1.2)) * besoin
    prix = rng.uniform(0.0, 12.0, 4)
    probs = rng.dirichlet(np.ones(4))
    r = I.evpi(ligne, frus, f, pc, "prix_recycleur_eur_kg", prix, probs)
    borne = I.borne_prix(frus[f]["scrap_an"], e["n_par_fru"], e["poids_kg"], prix, probs)
    assert -1e-7 <= r["Valeur de l'information (€/an)"] <= borne + 1e-6
    assert r["Valeur avec information (€/an)"] >= r["Valeur sans information (€/an)"] - 1e-6        # V convexe en prix
    q, pq = I.scenarios_beta(2, 3, 7)
    r = I.evpi(ligne, frus, f, pc, "p_reutilisable", q, pq)
    borne = I.borne_rendement(frus[f]["scrap_an"], e["n_par_fru"], e["valeur_eur"], e["poids_kg"], e["prix_recycleur_eur_kg"], q, pq)
    assert -1e-7 <= r["Valeur de l'information (€/an)"] <= borne + 1e-6
