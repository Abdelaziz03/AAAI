"""GEPA en local : la boucle d'amélioration des consignes, ses garde-fous, et la mesure sur des pièces jamais vues.
Les modèles sont des doublures dont le comportement dépend de la consigne ; aucun vrai modèle n'est appelé."""
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import erc  # noqa: E402
from erc import composition as C, cortex as K, gepa as G, modele as M  # noqa: E402

D, A = C.DOMAINE, C.ATTRIBUT
CLASSES = ["Carte", "Câble", "Métal", "Plastique"]
# Le « monde » des doublures : le mot de la désignation qui décide de la classe.
MONDE = {"board": "Carte", "pcb": "Carte", "harness": "Câble", "cable": "Câble", "bracket": "Métal", "screw": "Métal", "cover": "Plastique", "bezel": "Plastique"}


# ------------------------------------------------------------------ sélection de Pareto
def test_selection_de_pareto():
    rng = np.random.default_rng(0)
    # candidat 0 en tête sur 3 exemples, candidat 1 sur 1, candidat 2 nulle part, candidat 3 en tête là où 0 l'est déjà (écarté)
    scores = [[1, 1, 1, 0], [0, 0, 0, 1], [0.5, 0.5, 0.5, 0.5], [1, 1, 0, 0]]
    tirages = [G.choisir(scores, rng) for _ in range(2000)]
    assert set(tirages) == {0, 1} and 0.70 < tirages.count(0) / 2000 < 0.80                                   # 3 exemples contre 1
    assert G.choisir([[0.2, 0.9]], rng) == 0 and G.choisir([], rng) == 0
    # deux candidats identiques : un seul reste, le plus récent ; le meilleur en moyenne n'est pas seul à être choisi
    assert {G.choisir([[1, 0], [1, 0], [0, 1]], rng) for _ in range(200)} == {1, 2}


# ------------------------------------------------------------------ la boucle, sur un problème jouet
def probleme(n=40, graine=0):
    rng = np.random.default_rng(graine)
    mots = list(MONDE)
    return [G.Exemple(f"PN-{i:04d}", (f"{mots[rng.integers(len(mots))]} assy {i}", ""), "") for i in range(n)]


def executer_jouet(journal):
    """Le « modèle » ne connaît que les règles écrites dans la consigne, sous la forme « mot => Classe »."""
    def executer(consigne, e):
        journal.append((consigne, e.cle))
        regles = dict(re.findall(r"(\w+) => (\w+)", consigne))
        mot = e.entree[0].split()[0]
        attendu = MONDE[mot]
        if mot not in regles:
            return 0.5, f"Pas de réponse. Le mot « {mot} » désigne « {attendu} ».", None
        return (1.0, "Juste.", attendu) if regles[mot] == attendu else (0.0, f"Faux. Le mot « {mot} » désigne « {attendu} ».", regles[mot])
    return executer


def reflechir_jouet(consigne, traces):
    """Le « modèle de réflexion » ajoute la règle que le premier retour d'erreur lui souffle."""
    for e, note, commentaire, _ in traces:
        if note < 1.0:
            m = re.search(r"Le mot « (\w+) » désigne « (\w+) »", commentaire)
            return (consigne + "\n" if consigne else "") + f"{m.group(1)} => {m.group(2)}"
    return None


def test_la_boucle_ameliore_sans_depasser_le_budget_et_sans_refaire_un_appel():
    ex = probleme(60)
    retour, selection = ex[:30], ex[30:50]
    journal = []
    r = G.optimiser("", executer_jouet(journal), reflechir_jouet, retour, selection, budget=260, lot=4, graine=1)
    t = r["candidats"]
    assert r["appels"]["lecture"] <= 260 and r["appels"]["lecture"] == len(journal) == len(set(journal))        # budget tenu, aucun couple refait
    assert t["Note sur la sélection"].iloc[0] == 0.5 and t["Note sur la sélection"].max() > 0.9               # du silence aux règles apprises
    assert r["meilleure"] == r["textes"][int(t.loc[t["Retenu"], "Candidat"].iloc[0])] and int(t["Retenu"].sum()) == 1
    assert all(t["Note sur la sélection"].iloc[int(p)] <= 1 for p in t["Issu de"].dropna())                  # chaque candidat a un parent connu
    assert len(re.findall(r" => ", r["meilleure"])) >= 6                                                      # les règles s'accumulent le long de la lignée
    assert any("accepté" in l for l in r["journal"])
    # même graine, même déroulement
    r2 = G.optimiser("", executer_jouet([]), reflechir_jouet, retour, selection, budget=260, lot=4, graine=1)
    assert r2["meilleure"] == r["meilleure"] and r2["appels"] == r["appels"]
    # une proposition n'est gardée que si elle fait mieux que son parent sur le même lot
    pire = lambda consigne, traces: consigne + "\nboard => Métal\npcb => Métal\nharness => Métal\ncable => Plastique\ncover => Carte\nbezel => Carte\nbracket => Câble\nscrew => Câble"
    r3 = G.optimiser("", executer_jouet([]), pire, retour, selection, budget=260, lot=4, graine=1)
    assert r3["meilleure"] == "" and len(r3["candidats"]) == 1 and all("écartée" in l or "refusée" in l for l in r3["journal"])


def test_arrets_refus_et_petits_budgets():
    ex = probleme(40)
    retour, selection = ex[:20], ex[20:30]
    journal = []
    parfait = "\n".join(f"{m} => {c}" for m, c in MONDE.items())
    r = G.optimiser(parfait, executer_jouet(journal), reflechir_jouet, retour, selection, budget=500)             # déjà parfait : rien à chercher
    assert r["meilleure"] == parfait and len(journal) == len(selection) and r["appels"]["réflexion"] == 0
    r = G.optimiser("", executer_jouet([]), reflechir_jouet, retour, selection, budget=5)                         # budget sous la notation de départ
    assert r["meilleure"] == "" and r["appels"]["lecture"] == 0 and "budget trop petit" in r["journal"][0]
    journal = []
    refuse = lambda consigne: "contient un code article" if "=>" in consigne else None
    r = G.optimiser("", executer_jouet(journal), reflechir_jouet, retour, selection, budget=300, valide=refuse, patience=5)
    assert r["meilleure"] == "" and r["appels"]["réflexion"] == 5 and all("refusée (contient un code article)" in l for l in r["journal"])
    assert {c for c, _ in journal} == {""}                                                                    # une consigne refusée n'est jamais essayée
    r = G.optimiser("", executer_jouet([]), lambda c, t: None, retour, selection, budget=300, patience=3)          # le modèle de réflexion ne propose rien
    assert r["meilleure"] == "" and all("aucune proposition" in l for l in r["journal"])


# ------------------------------------------------------------------ sur les descriptions du cortex
class Lecteur:
    """Doublure d'un modèle privé : il lit une désignation avec les règles « mot => Classe » de ses conseils, et sait
    de lui-même que « cable » est un câble. Il note toutes les désignations qu'on lui montre."""
    prive, nature, modele = True, "ce poste", "lecteur-test"

    def __init__(self):
        self.conseils, self.vues, self.questions = {}, [], []

    def classer_detail(self, description, classes, contexte="", conseils=None):
        conseils = self.conseils.get("description", "") if conseils is None else conseils
        self.vues.append((conseils, description))
        regles = dict({"cable": "Câble"}, **dict(re.findall(r"(\w+) => (\w+)", conseils)))
        mot = description.split()[0].lower()
        if mot not in regles:
            return {"classe": None, "indice": "", "repondu": None, "rejet": "le modèle ne se prononce pas"}
        return {"classe": regles[mot], "indice": mot, "repondu": regles[mot], "rejet": None}

    def demander(self, consigne, contenu, schema=None):
        """Réflexion : ajoute aux conseils la règle que souffle le premier retour d'erreur."""
        self.questions.append(contenu)
        actuels = contenu.split("Conseils actuels :\n```\n")[1].split("\n```")[0]
        actuels = "" if actuels.startswith("(aucun") else actuels
        for bloc in contenu.split("Désignation : ")[1:]:
            mot = bloc.split()[0].lower()
            m = re.search(r"Il fallait « (\w+) »", bloc)
            if m and f"{mot} =>" not in actuels:
                return f"<think>je cherche le mot trompeur</think>Voici.\n```\n{(actuels + chr(10)) if actuels else ''}{mot} => {m.group(1)}\n```"
        return "```\n" + actuels + "\n```"


def cortex_valide(cx, n=64, graine=0):
    rng = np.random.default_rng(graine)
    mots = list(MONDE)
    for i in range(n):
        mot = mots[i % len(mots)]
        cx.declarer(D, f"PN-{i:04d}", f"{mot} assembly rev {rng.integers(1, 9)} lot {i}")
        cx.valider(D, f"PN-{i:04d}", A, MONDE[mot], "expert")
    cx.declarer(D, "NON-VALIDEE", "board non validée")


def test_descriptions_amelioration_mesuree_sur_des_pieces_jamais_vues():
    with K.Cortex(":memory:") as cx:
        cortex_valide(cx)
        avant = (len(cx.affirmations(D, A)), len(cx.journal(D)))
        m = Lecteur()
        g = G.optimiser_descriptions(cx, m, CLASSES, budget=400, graine=2)
        assert (len(cx.affirmations(D, A)), len(cx.journal(D))) == avant                                      # rien n'est écrit dans le cortex
    assert g["jeux"]["retour"] + g["jeux"]["sélection"] + g["jeux"]["essai"] == 64 and g["jeux"]["essai"] >= 16
    essai = set(g["essai"]["Description"])
    # la recherche n'a jamais vu une pièce d'essai : elles ne sont lues qu'après, avec la consigne de départ et la consigne retenue
    n_recherche = g["appels"]["lecture"]
    assert not essai & {d for _, d in m.vues[:n_recherche]} and {d for _, d in m.vues[n_recherche:]} == essai
    assert not any(d in q for q in m.questions for d in essai)                                                # ni montrées au modèle de réflexion
    assert g["appels"]["lecture"] <= 400 and g["appels"]["essai"] == 2 * g["jeux"]["essai"]
    r = g["resume"].set_index("Consigne")
    assert g["adopte"] and r.at["retenue", "Taux de justes"] > r.at["de départ", "Taux de justes"] + 0.5       # de « cable » seul à presque tout
    assert r.at["de départ", "Sans réponse"] > 0 and r.at["retenue", "Fausses"] == 0 and "PN-" not in g["conseils"]
    assert r["Écart entre les deux : hasard possible (p)"].iloc[0] < 0.01 and "peu compatible avec le hasard" in g["raison"]
    assert len(re.findall(r" => ", g["conseils"])) >= 5 and len(g["conseils"]) <= M.LONGUEUR_MAX_CONSEILS
    # les classes sont réparties dans les trois jeux
    assert set(g["essai"]["Classe validée"]) == set(CLASSES)


def test_garde_fous_contre_les_raccourcis():
    """Une consigne qui recopie un code article ou une désignation entière est refusée ; une consigne qui gagne sur la
    sélection mais perd sur l'essai n'est pas adoptée ; les modèles doivent être privés ; il faut assez de pièces."""
    class Tricheur(Lecteur):
        def demander(self, consigne, contenu, schema=None):                                                  # dresse la table des réponses
            self.questions.append(contenu)
            bloc = contenu.split("Désignation : ")[1]
            return "```\nSi la désignation est « " + bloc.split(" |")[0].split("\n")[0].strip() + " », réponds comme pour PN-0001.\n```"

    with K.Cortex(":memory:") as cx:
        cortex_valide(cx)
        g = G.optimiser_descriptions(cx, Lecteur(), CLASSES, reflexion=Tricheur(), budget=300, graine=2)
        assert not g["adopte"] and g["conseils"] == "" and any("contient un code article" in l or "recopie une désignation" in l for l in g["journal"])
        assert all("refusée" in l or "rien à corriger" in l for l in g["journal"])

        class Exterieur(Lecteur):
            prive = False
        with pytest.raises(PermissionError, match="lecture n'est pas privé"):
            G.optimiser_descriptions(cx, Exterieur(), CLASSES)
        with pytest.raises(PermissionError, match="réflexion n'est pas privé"):
            G.optimiser_descriptions(cx, Lecteur(), CLASSES, reflexion=Exterieur())

        class Surappris(Lecteur):                             # des conseils qui ne marchent que sur les pièces déjà vues par la recherche
            def __init__(self, vues_par_la_recherche):
                super().__init__()
                self.connues = vues_par_la_recherche

            def classer_detail(self, description, classes, contexte="", conseils=None):
                d = super().classer_detail(description, classes, contexte, conseils)
                conseils = self.conseils.get("description", "") if conseils is None else conseils
                if conseils and description not in self.connues:
                    return {"classe": "Plastique" if not description.startswith(("cover", "bezel")) else "Métal", "indice": description.split()[0], "repondu": "x", "rejet": None}
                return d
        retour, selection, essai = G.partager([G.Exemple(f"PN-{i:04d}", (d, ""), c) for i, (d, c) in enumerate(
            (r["description"], cx.verite(D, r["sujet"], A)) for _, r in cx._table("SELECT sujet, description FROM sujet WHERE domaine=? ORDER BY sujet", (D,)).iterrows()
            if cx.verite(D, r["sujet"], A))], 2)
        s = Surappris({e.entree[0] for e in retour + selection})
        g = G.optimiser_descriptions(cx, s, CLASSES, budget=400, graine=2)
        assert not g["adopte"] and "moins bien sur les pièces d'essai" in g["raison"]
    with K.Cortex(":memory:") as cx:
        cortex_valide(cx, n=10)
        g = G.optimiser_descriptions(cx, Lecteur(), CLASSES)
        assert not g["adopte"] and "il en faut au moins 24" in g["raison"] and g["appels"]["lecture"] == 0


def test_partage_disjoint_repetable_et_bloc_de_reponse():
    pieces = [G.Exemple(f"P{i:03d}", (f"d{i}", ""), CLASSES[i % 4]) for i in range(40)]
    a, b, c = G.partager(pieces, 1)
    cles = [e.cle for e in a + b + c]
    assert len(cles) == len(set(cles)) == 40 and G.partager(pieces, 1) == (a, b, c) and G.partager(pieces, 2) != (a, b, c)
    assert all({e.attendu for e in jeu} == set(CLASSES) for jeu in (a, b, c)) and len(c) == 12
    assert G._bloc("blabla\n```\npremier\n```\npuis\n```text\nle bon\n```\nfin") == "le bon"
    assert G._bloc("<think>``` piège ```</think>sans bloc") == "sans bloc" and G._bloc(None) == ""


# ------------------------------------------------------------------ conseils gardés et utilisés
def test_conseils_gardes_dans_le_dossier_et_envoyes_au_modele(tmp_path, monkeypatch):
    for v in ("ERC_MODELE_URL", "ERC_MODELE_NOM", "ERC_MODELE_CLE"):
        monkeypatch.delenv(v, raising=False)
    cfg = erc.charger_config(dossier=tmp_path, demo=True)
    assert M.lire_conseils(cfg) == {}
    f = M.garder_conseils(cfg, "qwen-test", "description", "  « PSU » désigne une alimentation : carte.  ", note_essai_apres=0.9)
    M.garder_conseils(cfg, "autre", "description", "autres conseils")
    d = M.lire_conseils(cfg)
    assert f.name == "consignes_modele.json" and d["qwen-test"]["description"]["texte"] == "« PSU » désigne une alimentation : carte."
    assert d["qwen-test"]["description"]["note_essai_apres"] == 0.9 and set(d) == {"qwen-test", "autre"}
    M.chemin_reglage(cfg).parent.mkdir(parents=True, exist_ok=True)
    M.chemin_reglage(cfg).write_text("[modele]\nurl = http://localhost:1/v1\nnom = qwen-test\n[controle]\nnom = sans-conseils\n", encoding="utf-8")
    lecture, controle = M.modeles_du_reglage(M.lire_reglage(cfg), cfg=cfg)
    assert lecture.conseils == {"description": "« PSU » désigne une alimentation : carte."} and controle.conseils == {}
    assert M.modeles_du_reglage(M.lire_reglage(cfg))[0].conseils == {}                                         # sans dossier : pas de conseils
    # le cadre de la consigne est fixe ; seuls les conseils s'y insèrent
    nue, avec = M.consigne_description(CLASSES), M.consigne_description(CLASSES, lecture.conseils["description"])
    assert "Conseils" not in nue and "« PSU » désigne une alimentation" in avec
    for c in (nue, avec):
        assert c.startswith("Tu classes une pièce de rechange") and " ; ".join(CLASSES) in c and c.rstrip().endswith('qui le justifient>"}')
    (Path(cfg.parametres) / M.FICHIER_CONSEILS).write_text("pas du json", encoding="utf-8")
    assert M.lire_conseils(cfg) == {}
