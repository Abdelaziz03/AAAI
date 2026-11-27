"""Bancs d'essai synthétiques des papiers (erc/bancs.py), en taille réduite : chaque banc vérifie le résultat qu'il
illustre, et les comptes qu'il rend se recoupent."""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from erc import bancs as B, composition as C, cortex as K  # noqa: E402


def test_monde_les_sources_ont_la_justesse_annoncee_et_deux_politiques_voient_le_meme_monde():
    m = B.Monde(1, 20000)
    parle = m.regle >= 0
    assert abs(parle.mean() - 0.60) < 0.02 and abs((m.regle[parle] == m.verite[parle]).mean() - 0.80) < 0.02
    assert abs((m.description == m.verite).mean() - 0.70) < 0.02 and abs((m.lecture_document == m.verite).mean() - 0.85) < 0.02
    decl = m.declaration >= 0
    assert abs(decl.mean() - 0.15) < 0.01 and abs((m.declaration[decl] == m.verite[decl]).mean() - 0.95) < 0.02 and not (decl & m.document).any()
    autre = B.Monde(1, 20000)
    assert (m.verite == autre.verite).all() and (m.description == autre.description).all() and (m.masses == autre.masses).all()
    copieur = B.Monde(1, 20000, copie=1.0)                      # le modèle répète la règle chaque fois qu'elle parle
    assert (copieur.description[copieur.regle >= 0] == copieur.regle[copieur.regle >= 0]).all()


def test_politiques_les_comptes_se_recoupent_et_le_budget_ne_coute_pas_plus_que_sans():
    r = B.exp_politiques(pieces=60, graines=1)
    p = {x["politique"]: x for x in r["rangs"]}
    budget, sans, gratuit = p["Budgeted chain (this paper)"], p["Chain without the budget screen"], p["Free evidence only"]
    assert budget["appels"] <= sans["appels"] and budget["cout"] <= sans["cout"] + 1e-9
    assert gratuit["appels"] == 0 and gratuit["cout"] == 0 and gratuit["acceptees"] == 0     # une règle seule ne suffit pas à accepter
    assert p["Review every component"]["revues"] == 60 and p["Review every component"]["part"] < budget["part"] <= 1.0
    assert all(x["part_min"] <= x["part"] <= x["part_max"] for x in r["rangs"])


def test_fusion_ablation_ignorer_la_provenance_rend_trop_sur():
    r = B.exp_fusion_ablation(essai=300, validations=(0, 100))
    p = {x["methode"]: x for x in r["rangs"]}
    apprise, sans = [x for x in r["rangs"] if x["methode"] == "Fusion, learned reliabilities"][-1], p["Fusion, learned, provenance ignored"]
    assert sans["couverture"] > apprise["couverture"] and sans["justesse_acceptees"] < apprise["justesse_acceptees"]   # accepte plus, et plus souvent à tort
    assert all(0 <= x["ece"] <= 1 and 0 <= x["brier"] <= 1 for x in r["rangs"])
    assert apprise["justesse_acceptees"] >= r["seuil"]          # ce que la fusion accepte tient le seuil


def test_scores_de_calibration_a_la_main():
    s = B._scores([0.95, 0.95, 0.55, 0.55], [True, True, True, False], seuil=0.9)
    assert math.isclose(s["justesse"], 0.75) and math.isclose(s["couverture"], 0.5) and math.isclose(s["justesse_acceptees"], 1.0)
    assert math.isclose(s["brier"], (2 * 0.05 ** 2 + 0.45 ** 2 + 0.55 ** 2) / 4)
    assert math.isclose(s["ece"], 0.5 * abs(1.0 - 0.95) + 0.5 * abs(0.5 - 0.55))


def test_boucle_les_fiabilites_apprises_valent_mieux_que_les_declarees():
    r = B.exp_boucle(pieces=150, tours=2, graines=2)
    assert r["erreur_strates"] < r["erreur_declaree"] and r["erreur_ensemble"] < r["erreur_declaree"]
    assert [x["tour"] for x in r["suivi"]] == [1, 2] and r["suivi"][0]["validees"] == 0 and r["suivi"][1]["validees"] > 0
    assert r["suivi"][1]["appels"] < r["suivi"][0]["appels"]    # une action payée n'est pas refaite au tour suivant
    for x in r["rangs"]:
        assert 0 <= x["vraie"] <= 1 and 0 < x["strates"] < 1 and 0 < x["ensemble"] < 1


def test_boucle_une_piece_laissee_peut_etre_tiree_au_sondage():
    """Le sondage tire parmi tout ce que la chaîne ne montre à personne : sans cela les pièces laissées faute d'enjeu
    n'auraient jamais de validation, et la fiabilité des sources n'y serait jamais mesurée."""
    m = B.Monde(3, 80)
    with K.Cortex(":memory:") as cx:
        t = m.derouler(cx)
        assert set(t["sort"]) <= {"acceptée", "revue", "laissée"} and (t["sort"] == "laissée").any()
        statuts = cx.conclusions(B.D, B.A).set_index("sujet")["statut"]
        for _, x in t.iterrows():
            attendu = {"acceptée": "acceptée", "revue": "à valider", "laissée": C.LAISSEE}[x["sort"]]
            assert statuts[m.pn(int(x["i"]))] in (attendu, "inconnue")


def test_ancrage_aucune_fausse_alerte_et_les_nombres_inventes_sont_signales():
    r = B.exp_ancrage(notes=150)
    assert r["fausses_alertes"] == 0 and r["legitimes"] == 150 * 12
    assert r["rappel_retouches"] == 1.0                         # un chiffre changé dans un montant à deux décimales se voit toujours
    assert 0.9 <= r["rappel_inventes"] <= 1.0                   # un nombre inventé n'échappe que s'il tombe sur une valeur des preuves


def test_exactitude_contre_le_solveur_exact_et_un_seul_type_partage():
    r = B.exp_exactitude(instances=25, tailles=((8, 4), (40, 30)))
    if r["compares"]:
        assert r["ecart"] < 1e-8
    assert all(x["partages"] <= 1 for x in r["rangs"])          # proposition 3


def test_tampon_la_borne_fluide_n_est_jamais_depassee():
    r = B.exp_tampon(semaines=20)
    for x in r["rangs"]:
        assert x["depasse"] <= 1e-6                             # proposition 5, version trajectoire
        assert -1e-9 <= x["ecart"] <= 1 and x["stock"] <= 1 + 1e-9 and x["stock_borne"] <= x["stock"] + 1e-9
        assert x["stock"] >= -1e-9                              # garder les unités ne fait pas pire que les relâcher


def test_marge_vraie_du_plan_execute():
    """La marge d'un plan évaluée aux vrais rendements est celle que rend l'optimiseur quand il croit les vrais rendements."""
    rng = np.random.default_rng(5)
    frus = {f"T{i}": B.type_synthetique(rng, 4) for i in range(3)}
    ligne = B._ligne(0.6 * B._besoin(frus))
    from erc import ligne as L
    valeurs = {f: L.valeurs_options(dict(d, _c_trait=0.25), B.TAUX).set_index("Pièce") for f, d in frus.items()}
    res = L.optimiser_ligne(ligne, frus)
    assert math.isclose(B._marge_vraie(res["detail"], valeurs, frus), res["resume"]["Marge variable / an (€)"], rel_tol=1e-9)


def test_apprentissage_lp_le_tirage_a_posteriori_regrette_moins():
    r = B.exp_apprentissage_lp(periodes=12, graines=2)
    p = {x["politique"]: x for x in r["rangs"]}
    assert p["Prior mean, never updated"]["testees"] == 0
    assert p["Posterior sampling (TS-LP)"]["regret"] < p["Prior mean, never updated"]["regret"]
    for x in r["rangs"]:
        assert x["regret"] >= -1e-6 and all(b >= a - 1e-6 for a, b in zip(x["courbe"], x["courbe"][1:]))   # le regret ne décroît jamais


def test_confinement_rien_ne_s_execute_hors_de_la_liste():
    from erc import agent as AG
    avant = dict(AG.OUTILS)
    r = B.exp_confinement(episodes=25, pas_max=5)
    assert r["hors_liste"] > 0 and r["hors_liste_executees"] == 0 and r["exceptions"] == 0 and r["depassements"] == 0
    assert r["refus"] == r["hors_liste"]                        # chaque demande hors liste a reçu un refus, rien d'autre
    assert r["conclus"] + r["replis"] == r["episodes"]
    assert AG.OUTILS == avant                                   # la liste d'outils instrumentée pour la mesure est rendue telle quelle
