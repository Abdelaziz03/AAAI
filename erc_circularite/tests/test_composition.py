"""Cortex (base de connaissance à sources faillibles) et chaîne de composition des nomenclatures.
Aucun accès au réseau : les fournisseurs sont des doublures, le serveur de modèle est un serveur local de test."""
import json
import math
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import erc  # noqa: E402
from erc import composition as C, cortex as K  # noqa: E402

D, A = C.DOMAINE, C.ATTRIBUT
CLASSES = ["Carte", "Câble", "Métal", "Plastique"]
PRIX = {"Carte": 8.0, "Câble": 2.0, "Métal": 0.3, "Plastique": 0.05}
REGLES = pd.DataFrame({"Motif": ["board|carte", "cable", "vis|radiateur"], "Classe": ["Carte", "Câble", "Métal"]})
N = len(CLASSES) + 1                                           # valeurs possibles : la liste, plus « hors référentiel »
F0 = K.FORCE_A_PRIORI


def piece(pn, description, **plus):
    return dict({"PN": pn, "Description": description, "FRU": None, "Quantité": None, "Fabricant": None,
                 "Référence fabricant": None, "Interne": False, "Poids (kg)": None}, **plus)


def achetee(pn, description, mpn="MPN-1", **plus):
    return piece(pn, description, **dict({"Fabricant": "Fabricant F", "Référence fabricant": mpn}, **plus))


def proba(cx, sujet="x"):
    return cx.croyance(D, sujet, A, CLASSES)


# ------------------------------------------------------------------ cortex : fusion des preuves
def test_fusion_une_source_puis_deux():
    """Une source de fiabilité r : P = r. Deux sources de types différents, d'accord, sur N valeurs possibles :
    r1 r2 / (r1 r2 + (N−1) × (1−r1)/(N−1) × (1−r2)/(N−1))."""
    with K.Cortex(":memory:") as cx:
        cx.affirmer(D, "x", A, "Carte", "règle", "règle")
        r1 = K.A_PRIORI_SOURCES["règle"]
        b = proba(cx)
        assert math.isclose(b["probabilite"], r1) and b["retenue"] == "Carte" and not b["validee"]
        assert list(b["probabilites"]) == CLASSES + [K.HORS]
        cx.affirmer(D, "x", A, "Carte", "document", "site-a")
        r2 = K.A_PRIORI_SOURCES["document"]
        attendu = r1 * r2 / (r1 * r2 + (N - 1) * ((1 - r1) / (N - 1)) * ((1 - r2) / (N - 1)))
        assert math.isclose(proba(cx)["probabilite"], attendu)
        assert math.isclose(sum(proba(cx)["probabilites"].values()), 1.0)


def test_meme_type_de_source_fiabilite_integree():
    """Deux documents d'accord partagent une fiabilité inconnue : la fusion intègre sur sa loi Bêta. Le résultat est
    moins sûr que si l'on branchait deux fois la moyenne, et trois documents contre un ne sont pas trois preuves."""
    r, a, b = K.A_PRIORI_SOURCES["document"], K.A_PRIORI_SOURCES["document"] * F0, (1 - K.A_PRIORI_SOURCES["document"]) * F0
    B = lambda x, y: math.exp(math.lgamma(x) + math.lgamma(y) - math.lgamma(x + y))
    with K.Cortex(":memory:") as cx:
        cx.affirmer(D, "x", A, "Carte", "document", "site-a")
        cx.affirmer(D, "x", A, "Carte", "document", "site-b")
        juste, faux = B(a + 2, b) / B(a, b), B(a, b + 2) / B(a, b) / (N - 1) ** 2
        exact = juste / (juste + (N - 1) * faux)
        branche = r * r / (r * r + (N - 1) * ((1 - r) / (N - 1)) ** 2)
        p = proba(cx)["probabilite"]
        assert math.isclose(p, exact) and p < branche
        cx.affirmer(D, "x", A, "Câble", "document", "site-c")                # un troisième n'est pas d'accord
        carte = B(a + 2, b + 1) / (N - 1)
        cable = B(a + 1, b + 2) / (N - 1) ** 2
        autres = B(a, b + 3) / (N - 1) ** 3
        assert math.isclose(proba(cx)["probabilites"]["Carte"], carte / (carte + cable + (N - 2) * autres))


def test_une_origine_ne_compte_qu_une_fois():
    with K.Cortex(":memory:") as cx:
        for _ in range(5):                                    # la même page relue cinq fois reste une preuve
            cx.affirmer(D, "x", A, "Carte", "document", "site-a")
        assert proba(cx)["preuves"] == 1 and math.isclose(proba(cx)["probabilite"], K.A_PRIORI_SOURCES["document"])


def test_verdict_oui_non_canal_binaire():
    """Un contrôle répond oui ou non, juste avec la probabilité r quelle que soit la vraie classe. Lecture à 0,60 puis
    « oui » à 0,70 : 0,42 / (0,42 + 0,4 × 0,3) = 0,778, et non 0,91 comme si le « oui » nommait la classe parmi N.
    « Non » : 0,18 / (0,18 + 0,4 × 0,7) = 0,391."""
    re_, rv = K.A_PRIORI_SOURCES["modèle : extraction"], K.A_PRIORI_SOURCES["modèle : validation"]
    with K.Cortex(":memory:") as cx:
        cx.affirmer(D, "x", A, "Carte", "modèle : extraction", "site-a")
        cx.affirmer(D, "x", A, "Carte", "modèle : validation", "site-a", nature="verdict", polarite=1)
        oui = proba(cx)["probabilites"]["Carte"]
        assert math.isclose(oui, re_ * rv / (re_ * rv + (1 - re_) * (1 - rv))) and abs(oui - 0.7778) < 1e-4
        cx.affirmer(D, "x", A, "Carte", "modèle : validation", "site-a", nature="verdict", polarite=-1)   # la même origine change d'avis
        non = proba(cx)["probabilites"]["Carte"]
        assert math.isclose(non, re_ * (1 - rv) / (re_ * (1 - rv) + (1 - re_) * rv)) and abs(non - 0.3913) < 1e-4
        # les deux réponses forment bien une loi : P(oui | autre classe) + P(non | autre classe) = (1 − r) + r = 1
        with pytest.raises(ValueError):
            cx.affirmer(D, "x", A, "Carte", "modèle : validation", "o", nature="autre")
    with K.Cortex(":memory:") as cx:                         # une négation simple se lit comme un verdict « non »
        cx.affirmer(D, "x", A, "Carte", "document", "site-a", polarite=-1)
        r = K.A_PRIORI_SOURCES["document"]
        assert math.isclose(proba(cx)["probabilites"]["Carte"], (1 - r) / ((1 - r) + (N - 1) * r))


def test_valeur_hors_referentiel():
    """Une classe affirmée hors de la liste n'est ni perdue ni prise pour une classe de la liste ; le nombre de valeurs
    possibles ne change pas d'une pièce à l'autre."""
    with K.Cortex(":memory:") as cx:
        cx.affirmer(D, "x", A, "Verre", "classement antérieur", "classement antérieur")
        b = proba(cx)
        assert b["retenue"] == K.HORS and math.isclose(b["probabilite"], K.A_PRIORI_SOURCES["classement antérieur"])
        assert list(b["probabilites"]) == CLASSES + [K.HORS]
        cx.affirmer(D, "y", A, "Carte", "règle", "règle")
        cx.affirmer(D, "y", A, "Céramique", "analogie", "analogie")
        b = proba(cx, "y")
        assert b["retenue"] == "Carte" and len(b["probabilites"]) == N and b["probabilites"][K.HORS] > b["probabilites"]["Câble"]
        with pytest.raises(ValueError):
            cx.croyance(D, "y", A, [])


def test_sans_preuve_inconnu_et_validation_fait_foi():
    with K.Cortex(":memory:") as cx:
        b = proba(cx)
        assert b["retenue"] is None and math.isnan(b["probabilite"]) and b["preuves"] == 0
        cx.affirmer(D, "x", A, "Carte", "règle", "règle")
        cx.valider(D, "x", A, "Câble", "expert")
        b = proba(cx)
        assert b["validee"] and b["retenue"] == "Câble" and b["probabilite"] == 1.0
        cx.valider(D, "x", A, "Métal", "expert")              # la dernière validation fait foi
        assert cx.verite(D, "x", A) == "Métal"
        cx.valider(D, "x", A, "Verre trempé", "expert")       # une personne peut valider une classe hors de la liste
        assert proba(cx)["retenue"] == "Verre trempé"


def test_supposition_et_retrait():
    """`en_plus` et `sans` disent ce que deviendrait la croyance, sans rien écrire ; `retirer` enlève ce qu'une source disait."""
    with K.Cortex(":memory:") as cx:
        cx.affirmer(D, "x", A, "Carte", "modèle : extraction", "site-a")
        avant = proba(cx)["probabilite"]
        si = cx.croyance(D, "x", A, CLASSES, en_plus=[{"type_source": "modèle : extraction confirmée", "valeur": "Carte"}],
                         sans=[("modèle : extraction", "site-a")])
        assert math.isclose(si["probabilite"], K.A_PRIORI_SOURCES["modèle : extraction confirmée"]) and si["preuves"] == 0
        assert math.isclose(proba(cx)["probabilite"], avant) and len(cx.affirmations(D, A, "x")) == 1
        assert cx.retirer(D, "x", A, "modèle : extraction", "site-a") == 1 and proba(cx)["retenue"] is None


# ------------------------------------------------------------------ cortex : fiabilité apprise
def test_fiabilite_apprise_des_validations():
    with K.Cortex(":memory:") as cx:
        for i, (dit, vrai) in enumerate([("Carte", "Carte"), ("Carte", "Carte"), ("Carte", "Câble"), ("Câble", "Câble")]):
            cx.affirmer(D, f"s{i}", A, dit, "règle", "règle")
            cx.valider(D, f"s{i}", A, vrai, "expert")
        f = cx.fiabilites(D, A).set_index("Type de source").loc["règle"]
        assert (f["Affirmations vérifiées"], f["Justes"], f["Fausses"]) == (4, 3, 1)
        m0 = K.A_PRIORI_SOURCES["règle"]
        assert math.isclose(f["Fiabilité"], (m0 * F0 + 3) / (F0 + 4))
        cx.affirmer(D, "non_valide", A, "Carte", "règle", "règle")          # sans validation : ne juge pas la source
        assert cx.fiabilites(D, A).set_index("Type de source").at["règle", "Affirmations vérifiées"] == 4


def test_fiabilite_par_strates_validations_de_la_file_et_du_sondage():
    """Valider seulement les cas douteux ferait croire que la source est mauvaise partout. Les validations de la file
    ne renseignent que la file, celles du sondage que les pièces acceptées, chaque strate pesant ce qu'il y reste à juger."""
    m0 = K.A_PRIORI_SOURCES["règle"]
    a0, b0 = m0 * F0, (1 - m0) * F0
    with K.Cortex(":memory:") as cx:
        for i in range(10):                                   # dix pièces acceptées, dix dans la file ; la règle parle de toutes
            cx.affirmer(D, f"acc{i}", A, "Carte", "règle", "règle")
            cx.conclure(D, f"acc{i}", A, "Carte", 0.95, "acceptée")
            cx.affirmer(D, f"file{i}", A, "Carte", "règle", "règle")
            cx.conclure(D, f"file{i}", A, "Carte", 0.6, "à valider")
        for i in range(2):                                    # deux pièces de la file validées : la règle avait tort
            cx.valider(D, f"file{i}", A, "Câble", "expert", motif="file")
        avec_file_seule = cx.fiabilites(D, A).set_index("Type de source").at["règle", "Fiabilité"]
        m_file = a0 / (a0 + b0 + 2)
        assert math.isclose(avec_file_seule, (10 * m0 + 8 * m_file) / 18)     # les pièces acceptées gardent l'a priori
        assert avec_file_seule > (a0 + 0) / (a0 + b0 + 2)                     # et non le taux observé dans la seule file
        for i in range(3):                                    # trois pièces acceptées tirées au sondage : la règle avait raison
            cx.valider(D, f"acc{i}", A, "Carte", "expert", motif="sondage")
        f = cx.fiabilites(D, A).set_index("Type de source").loc["règle"]
        m_acc = (a0 + 3) / (a0 + b0 + 3)
        assert math.isclose(f["Fiabilité"], (7 * m_acc + 8 * m_file) / 15)
        assert (f["dont par sondage"], f["dont dans la file"], f["Affirmations vérifiées"]) == (3, 2, 5)
        cx.valider(D, "acc9", A, "Câble", "expert", motif="choix")           # une correction choisie fixe la classe, sans juger la source
        g = cx.fiabilites(D, A).set_index("Type de source").loc["règle"]
        assert g["Affirmations vérifiées"] == 5 and math.isclose(g["Fiabilité"], (6 * m_acc + 8 * m_file) / 14)
        assert cx.verite(D, "acc9", A) == "Câble"


def test_voisins_valides_seulement_et_descriptions_absentes():
    with K.Cortex(":memory:") as cx:
        cx.declarer(D, "a", "Gate driver board rev B")
        cx.declarer(D, "b", "Gate driver board rev C")
        cx.declarer(D, "c", "Cooling fan 120 mm")
        assert cx.voisins(D, A, "Gate driver board rev D") == []          # personne n'est validé
        cx.valider(D, "a", A, "Carte", "expert")
        v = cx.voisins(D, A, "Gate driver board rev D", seuil=0.5)
        assert [x[0] for x in v] == ["a"] and v[0][2] == "Carte" and 0.5 <= v[0][1] <= 1
        assert cx.voisins(D, A, "Gate driver board rev B", sauf="a") == []  # une pièce n'est pas sa propre voisine
        # une description absente (cellule vide lue par pandas) ne devient pas le mot « nan » commun à toutes
        cx.declarer(D, "v1", float("nan"))
        cx.declarer(D, "v2", None)
        cx.valider(D, "v1", A, "Carte", "expert")
        assert cx._table("SELECT description FROM sujet WHERE sujet='v1'")["description"][0] == ""
        assert cx.voisins(D, A, float("nan")) == [] and K.ressemblance(float("nan"), None) == 0.0


def test_textes_accents_ligatures_autres_ecritures():
    assert K.mots("Câble blindé, cœur Ø12") >= {"cable", "blinde", "coeur"}
    assert K.ressemblance("電源ケーブル", "電源ケーブル") == 1.0
    assert K.texte(None) == "" and K.texte(float("nan")) == "" and K.texte(pd.NA) == "" and K.texte(12) == "12"


def test_journal_depense_conclusions():
    with K.Cortex(":memory:") as cx:
        cx.noter(D, "x", "collecte", 0.02, "échec : TimeoutError")
        cx.noter(D, "x", "collecte", 0.02, "2 document(s)")
        cx.noter(D, "y", "collecte", 0.02, "1 document(s)")
        assert cx.actions(D, "x", "collecte") == ["échec : TimeoutError", "2 document(s)"] and math.isclose(cx.depense(D, "x"), 0.04)
        cx.conclure(D, "x", A, "Carte", 0.93, "acceptée")
        cx.conclure(D, "x", A, "Câble", float("nan"), "à valider")
        c = cx.conclusions(D, A)
        assert list(c["sujet"]) == ["x"] and c["statut"][0] == "à valider" and c["valeur"][0] == "Câble" and pd.isna(c["probabilite"][0])


def test_fichier_d_une_version_anterieure_et_fichier_etranger(tmp_path):
    """Un cortex écrit par la première version (sans les colonnes ajoutées depuis) s'ouvre et garde son contenu ;
    un fichier qui n'est pas un cortex est refusé avec un message clair."""
    ancien = tmp_path / "ancien.sqlite"
    b = sqlite3.connect(ancien)
    b.executescript("""
        CREATE TABLE sujet(domaine TEXT, sujet TEXT, description TEXT, maj TEXT, PRIMARY KEY(domaine, sujet));
        CREATE TABLE affirmation(id INTEGER PRIMARY KEY, domaine TEXT, sujet TEXT, attribut TEXT, valeur TEXT, type_source TEXT,
            origine TEXT, detail TEXT, cree_le TEXT, UNIQUE(domaine, sujet, attribut, type_source, origine));
        CREATE TABLE validation(id INTEGER PRIMARY KEY, domaine TEXT, sujet TEXT, attribut TEXT, valeur TEXT, validateur TEXT,
            commentaire TEXT, cree_le TEXT);
        CREATE TABLE journal(id INTEGER PRIMARY KEY, cree_le TEXT, domaine TEXT, sujet TEXT, action TEXT, cout REAL, resultat TEXT);
        INSERT INTO affirmation(domaine, sujet, attribut, valeur, type_source, origine) VALUES('composition', 'x', 'classe matière', 'Carte', 'règle', 'r');
        INSERT INTO validation(domaine, sujet, attribut, valeur, validateur) VALUES('composition', 'z', 'classe matière', 'Câble', 'expert');
    """)
    b.commit()
    b.close()
    with K.Cortex(ancien) as cx:
        assert math.isclose(proba(cx)["probabilite"], K.A_PRIORI_SOURCES["règle"]) and cx.verite(D, "z", A) == "Câble"
        cx.affirmer(D, "x", A, "Carte", "modèle : validation", "site", nature="verdict")
        cx.valider(D, "x", A, "Carte", "expert", motif="sondage")
        cx.declarer(D, "x", "Carte de test", interne=True)
    assert sqlite3.connect(ancien).execute("PRAGMA user_version").fetchone()[0] == K.VERSION
    etranger = tmp_path / "autre.sqlite"
    b = sqlite3.connect(etranger)
    b.execute("CREATE TABLE journal(id INTEGER PRIMARY KEY, texte TEXT)")
    b.commit()
    b.close()
    with pytest.raises(ValueError, match="n'est pas un cortex"):
        K.Cortex(etranger)
    futur = tmp_path / "futur.sqlite"
    b = sqlite3.connect(futur)
    b.execute(f"PRAGMA user_version = {K.VERSION + 1}")
    b.commit()
    b.close()
    with pytest.raises(ValueError, match="version plus récente"):
        K.Cortex(futur)


def test_deux_connexions_sur_le_meme_fichier(tmp_path):
    """Chaque pièce résolue est écrite aussitôt : une seconde connexion voit le travail et peut écrire à son tour."""
    f = tmp_path / "c.sqlite"
    a, b = K.Cortex(f), K.Cortex(f)
    C.resoudre(a, piece("p1", "Controller board"), CLASSES, PRIX, REGLES, masse_annuelle_kg=1.0)
    assert not a.base.in_transaction and len(b.affirmations(D, A, "p1")) == 1
    b.valider(D, "p1", A, "Carte", "expert")
    assert a.verite(D, "p1", A) == "Carte"
    a.fermer()
    b.fermer()


# ------------------------------------------------------------------ chaîne : enjeu
def test_enjeu_et_enjeu_residuel():
    """Enjeu : masse × moyenne de (prix + traitement évité)⁺. La case hors référentiel n'a pas de débouché : 0."""
    assert math.isclose(C.enjeu(100.0, {"Carte": 0.5, "Plastique": 0.5}, PRIX), 100 * (0.5 * 8.0 + 0.5 * 0.05))
    assert math.isclose(C.enjeu(100.0, {"Carte": 0.5, "Plastique": 0.3, K.HORS: 0.2}, PRIX, 0.5), 100 * (0.5 * 8.5 + 0.3 * 0.55))
    assert math.isclose(C.enjeu(100.0, {"Carte": 1.0}, {"Carte": -2.0}, 0.5), 0.0)       # une classe qui coûte plus que la benne : rien à gagner
    assert math.isnan(C.enjeu(None, {"Carte": 0.5, "Plastique": 0.5}, PRIX))
    # des classes sans prix qui pèsent ensemble plus de 1 % : on ne peut rien borner, même si chacune est petite
    assert math.isnan(C.enjeu(1000.0, dict({"Plastique": 0.80}, **{f"Sans prix {i}": 0.04 for i in range(5)}), PRIX))
    assert math.isclose(C.enjeu(1000.0, {"Plastique": 0.995, "Sans prix": 0.005}, PRIX), 1000 * 0.995 * 0.05)
    # ce qu'une erreur peut coûter : masse × probabilité d'erreur × meilleure valeur des classes plausibles
    p = {"Plastique": 0.93, "Carte": 0.06, "Câble": 0.005, K.HORS: 0.005}
    assert math.isclose(C.enjeu_residuel(100.0, p, "Plastique", PRIX), 100 * 0.07 * 8.0)
    assert math.isclose(C.enjeu_residuel(100.0, {"Plastique": 0.99, "Carte": 0.005, "Câble": 0.005}, "Plastique", PRIX), 100 * 0.01 * 0.05)
    assert math.isnan(C.enjeu_residuel(None, p, "Plastique", PRIX)) and math.isnan(C.enjeu_residuel(100.0, p, None, PRIX))


class Espion:
    """Collecteur de test : note chaque requête et rend les documents prévus."""

    def __init__(self, documents=None):
        self.requetes, self.documents = [], documents or {}

    def __call__(self, requete):
        self.requetes.append(requete)
        return self.documents.get(requete["reference_fabricant"], [])


class ModeleTest:
    def __init__(self, classe="Carte", verdict=True):
        self.classe, self.verdict, self.textes, self.lectures, self.controles = classe, verdict, [], 0, 0

    def extraire(self, document, classes):
        self.textes.append(document)
        self.lectures += 1
        return (self.classe, "citation") if self.classe else (None, "")

    def valider(self, classe, document):
        self.textes.append(document)
        self.controles += 1
        return self.verdict


FICHE = [{"origine": "site-a", "nature": "document", "texte": "Fiche technique sans mot-clé."}]


# ------------------------------------------------------------------ chaîne : dépenser le moins possible
def test_piece_legere_aucun_appel_payant():
    """Même avec un collecteur et un modèle branchés, une pièce dont l'enjeu est sous le coût ne déclenche rien."""
    esp, mod = Espion({"MPN-1": FICHE}), ModeleTest()
    with K.Cortex(":memory:") as cx:
        r = C.resoudre(cx, achetee("p1", "Vis M4"), CLASSES, PRIX, REGLES, masse_annuelle_kg=0.01, collecteur=esp, modele=mod)
        assert esp.requetes == [] and mod.textes == [] and r["Appels au modèle"] == 0 and r["Coût des acquisitions (€)"] == 0
        assert r["Statut"] == "à valider" and r["Prochaine action"].startswith("aucune")
        assert len(cx.journal(D)) == 0


def test_la_confiance_se_gagne():
    """Une lecture par le modèle, même relue par lui, ne suffit pas à accepter une classe tant que rien n'a montré que
    ce modèle lit juste : aucun contrôle n'est payé, puisqu'un « oui » ne ferait pas passer le seuil. Quand les
    validations ont montré qu'il lit juste, le même cas est contrôlé puis accepté."""
    esp, mod = Espion({"MPN-1": FICHE}), ModeleTest("Câble", True)
    with K.Cortex(":memory:") as cx:
        r = C.resoudre(cx, achetee("p1", "Module à préciser"), CLASSES, PRIX, REGLES, masse_annuelle_kg=2.0, collecteur=esp, modele=mod)
        assert list(cx.journal(D)["action"]) == ["lecture par le modèle", "collecte"] and mod.controles == 0
        assert r["Appels au modèle"] == 1 and r["Classe retenue"] == "Câble" and r["Statut"] == "à valider"
        assert math.isclose(r["Probabilité"], K.A_PRIORI_SOURCES["modèle : extraction"]) and math.isclose(r["Coût des acquisitions (€)"], 0.07)
    esp, mod = Espion({"MPN-1": FICHE}), ModeleTest("Câble", True)
    with K.Cortex(":memory:") as cx:
        for i in range(12):                                   # douze lectures confirmées, toutes justes, validées sans regarder les sources
            cx.affirmer(D, f"v{i}", A, "Carte", "modèle : extraction confirmée", f"doc{i}")
            cx.valider(D, f"v{i}", A, "Carte", "expert")
        r = C.resoudre(cx, achetee("p1", "Module à préciser"), CLASSES, PRIX, REGLES, masse_annuelle_kg=2.0, collecteur=esp, modele=mod)
        assert list(cx.journal(D)["action"]) == ["lecture par le modèle", "collecte", "contrôle par le modèle"]
        assert r["Statut"] == "acceptée" and r["Sources"] == "modèle : extraction confirmée" and r["Preuves"] == 1
        assert r["Appels au modèle"] == 2 and math.isclose(r["Coût des acquisitions (€)"], 0.02 + 0.05 + 0.03)


def test_controle_par_le_meme_modele_ou_par_un_autre():
    """Le même modèle qui relit sa lecture ne fait pas une seconde source : « oui » la confirme, « non » la retire.
    Un autre modèle donne un verdict, qui est une source de plus."""
    fiable = lambda cx: [(cx.affirmer(D, f"v{i}", A, "Carte", t, f"doc{i}"), cx.valider(D, f"v{i}", A, "Carte", "expert"))
                         for i in range(12) for t in ("modèle : extraction confirmée", "modèle : validation")]       # la lecture seule reste à 0,60
    with K.Cortex(":memory:") as cx:                         # même modèle, « non » : la lecture est retirée
        fiable(cx)
        mod = ModeleTest("Câble", False)
        r = C.resoudre(cx, achetee("p1", "Module à préciser"), CLASSES, PRIX, REGLES, masse_annuelle_kg=2.0, collecteur=Espion({"MPN-1": FICHE}), modele=mod)
        assert mod.controles == 1 and r["Preuves"] == 0 and r["Statut"] == "inconnue" and r["Classe retenue"] is None
        assert list(cx.journal(D)["resultat"])[-1] == "contredit"
    with K.Cortex(":memory:") as cx:                         # autre modèle, « oui » : deux sources
        fiable(cx)
        lecteur, controleur = ModeleTest("Câble"), ModeleTest(verdict=True)
        r = C.resoudre(cx, achetee("p1", "Module à préciser"), CLASSES, PRIX, REGLES, masse_annuelle_kg=2.0, collecteur=Espion({"MPN-1": FICHE}),
                       modele=lecteur, modele_controle=controleur)
        assert (lecteur.lectures, lecteur.controles, controleur.controles) == (1, 0, 1)
        assert r["Sources"] == "modèle : extraction, modèle : validation" and r["Statut"] == "acceptée"
        v = cx.affirmations(D, A, "p1").set_index("type_source").loc["modèle : validation"]
        assert v["nature"] == "verdict" and v["polarite"] == 1 and v["origine"] == "site-a"
    with K.Cortex(":memory:") as cx:                         # le contrôle porte sur le document qui soutient la classe retenue
        fiable(cx)
        docs = [{"origine": "site-a", "nature": "document", "texte": "Texte A."}, {"origine": "site-b", "nature": "document", "classe": "Carte", "texte": "Texte B."}]
        lecteur, controleur = ModeleTest("Câble"), ModeleTest(verdict=None)
        r = C.resoudre(cx, achetee("p1", "Module à préciser"), CLASSES, PRIX, REGLES, masse_annuelle_kg=2.0, collecteur=Espion({"MPN-1": docs}),
                       modele=lecteur, modele_controle=controleur)
        retenue = r["Classe retenue"]
        assert controleur.textes in ([], ["Texte A."] if retenue == "Câble" else ["Texte B."])
        assert list(cx.journal(D)["resultat"])[-1] in ("ne tranche pas", "2 document(s)")


def test_budget_par_piece_et_arret_des_que_la_classe_est_acceptee():
    trois = [{"origine": f"site-{i}", "nature": "document", "texte": f"Texte {i}."} for i in range(3)]
    with K.Cortex(":memory:") as cx:                         # enjeu 0,06 € : la recherche (0,02) passe, pas une lecture de plus (0,05)
        mod = ModeleTest("Câble")
        masse = 0.06 / ((8.0 + 2.0 + 0.3 + 0.05) / N)
        r = C.resoudre(cx, achetee("p1", "Module à préciser"), CLASSES, PRIX, REGLES, masse_annuelle_kg=masse, collecteur=Espion({"MPN-1": trois}), modele=mod)
        assert mod.lectures == 0 and math.isclose(r["Coût des acquisitions (€)"], 0.02) and math.isclose(cx.depense(D, "p1"), 0.02)
    with K.Cortex(":memory:") as cx:                         # une déclaration structurée suffit : les deux autres documents ne sont pas lus
        mod = ModeleTest("Câble")
        docs = [{"origine": "fabricant", "nature": "déclaration fabricant", "classe": "Plastique", "texte": "Déclaration."}] + trois[:2]
        r = C.resoudre(cx, achetee("p1", "Module à préciser"), CLASSES, PRIX, REGLES, masse_annuelle_kg=5.0, collecteur=Espion({"MPN-1": docs}), modele=mod)
        assert mod.lectures == 0 and r["Statut"] == "acceptée" and r["Classe retenue"] == "Plastique" and r["Sources"] == "déclaration fabricant"
        assert math.isclose(r["Probabilité"], K.A_PRIORI_SOURCES["déclaration fabricant"])


def test_acceptee_seulement_si_une_erreur_coute_moins_qu_une_revue():
    """Règle et document d'accord : classe probable. Sur une pièce lourde, ce qu'une erreur peut coûter dépasse le coût
    d'une revue : la pièce va en revue. Sur une pièce légère, elle est acceptée."""
    docs = {"MPN-1": [{"origine": "site-a", "nature": "document", "classe": "Carte", "texte": "Fiche."}]}
    for masse, statut in ((2000.0, "à valider"), (5.0, "acceptée")):
        with K.Cortex(":memory:") as cx:
            r = C.resoudre(cx, achetee("p1", "Controller board"), CLASSES, PRIX, REGLES, masse_annuelle_kg=masse, collecteur=Espion(docs))
            assert r["Probabilité"] > 0.9 and r["Statut"] == statut, (masse, r)
            if statut == "à valider":
                assert "une erreur coûterait plus" in r["Prochaine action"]
                risque = C.enjeu_residuel(masse, proba(cx, "p1")["probabilites"], "Carte", PRIX)
                assert risque >= C.Reglages().cout_revue


def test_un_document_n_est_jamais_lu_avec_les_regles():
    """La même règle appliquée à la description puis au document ne fait pas deux sources, et un mot-clé dans une
    déclaration ne vaut pas une classe déclarée : sans modèle, seul un document qui donne lui-même la classe compte."""
    for nature in ("document", "déclaration fabricant"):
        docs = {"MPN-1": [{"origine": "site-a", "nature": nature, "texte": "Power cable assembly. Mounts on the main board."}]}
        with K.Cortex(":memory:") as cx:
            r = C.resoudre(cx, achetee("p1", "Controller board"), CLASSES, PRIX, REGLES, masse_annuelle_kg=500.0, collecteur=Espion(docs), modele=None)
            assert r["Preuves"] == 1 and r["Sources"] == "règle" and math.isclose(r["Probabilité"], K.A_PRIORI_SOURCES["règle"])
    docs = {"MPN-1": [{"origine": "site-a", "nature": "déclaration fabricant", "classe": "Carte", "texte": "Déclaration matière."}]}
    with K.Cortex(":memory:") as cx:
        r = C.resoudre(cx, achetee("p1", "Controller board"), CLASSES, PRIX, REGLES, masse_annuelle_kg=5.0, collecteur=Espion(docs), modele=None)
        assert r["Preuves"] == 2 and "déclaration fabricant" in r["Sources"] and r["Statut"] == "acceptée"


def test_regle_modifiee_ou_supprimee_ne_compte_pas_deux_fois():
    with K.Cortex(":memory:") as cx:
        p = piece("p1", "Module PCB board")
        r1 = C.resoudre(cx, p, CLASSES, PRIX, REGLES, masse_annuelle_kg=1.0)
        r2 = C.resoudre(cx, p, CLASSES, PRIX, pd.DataFrame({"Motif": ["board|carte|pcb"], "Classe": ["Carte"]}), masse_annuelle_kg=1.0)
        assert r1["Preuves"] == r2["Preuves"] == 1 and math.isclose(r1["Probabilité"], r2["Probabilité"]) and r2["Statut"] == "à valider"
        assert json.loads(cx.affirmations(D, A, "p1")["detail"][0])["motif"] == "board|carte|pcb"
        r3 = C.resoudre(cx, p, CLASSES, PRIX, pd.DataFrame({"Motif": ["cable"], "Classe": ["Câble"]}), masse_annuelle_kg=1.0)
        assert r3["Preuves"] == 0 and r3["Statut"] == "inconnue"
    assert C.regle("Câble blindé", REGLES) == ("Câble", "cable")                      # ni la casse ni les accents ne comptent
    assert C.regle("CABLE", pd.DataFrame({"Motif": ["câble"], "Classe": ["Câble"]})) == ("Câble", "câble")
    assert C.regle("Capteur", pd.DataFrame({"Motif": [r"\Bapteur", "("], "Classe": ["Carte", "Câble"]})) == ("Carte", r"\Bapteur")
    assert C.regles_invalides(pd.DataFrame({"Motif": ["(", "ok"], "Classe": ["a", "b"]}))[0].startswith("(")


# ------------------------------------------------------------------ chaîne : pannes et entrées abîmées
def test_second_passage_ne_repaie_rien():
    """Deux passages sur la même nomenclature : mêmes résultats, aucun nouvel appel au collecteur ni au modèle."""
    appels = {"collecte": 0, "modele": 0}

    def collecteur(requete):
        appels["collecte"] += 1
        return [{"origine": "fiche-" + requete["reference_fabricant"], "texte": "Housing material: polycarbonate plastic", "nature": "document"}]

    class Modele:
        def extraire(self, document, classes):
            appels["modele"] += 1
            return "Plastique", "polycarbonate plastic"

        def valider(self, classe, document):
            appels["modele"] += 1
            return True

    bom = pd.DataFrame([achetee("A1", "Capot avant", "AC-1"), piece("A2", "Carte de commande"), achetee("A3", "Support", "AC-3")])
    masses = {"A1": 400.0, "A2": 50.0, "A3": 400.0}
    with K.Cortex(":memory:") as cx:
        t1 = C.traiter(cx, bom, CLASSES, PRIX, REGLES, masses=masses, collecteur=collecteur, modele=Modele())
        n1, journal1 = dict(appels), len(cx.journal(D))
        assert n1 == {"collecte": 2, "modele": 2} and t1["Notes"]["appels_au_modele"] == 2
        t2 = C.traiter(cx, bom, CLASSES, PRIX, REGLES, masses=masses, collecteur=collecteur, modele=Modele())
        assert appels == n1 and len(cx.journal(D)) == journal1, "le second passage ne doit rien payer"
        assert t2["Notes"]["appels_au_modele"] == 0 and t2["Notes"]["cout_des_acquisitions_eur"] == 0.0
        cols = ["PN", "Classe retenue", "Statut", "Preuves"]
        pd.testing.assert_frame_equal(t1["Composition proposée"][cols], t2["Composition proposée"][cols])
        assert np.allclose(t1["Composition proposée"]["Probabilité"], t2["Composition proposée"]["Probabilité"], equal_nan=True)
        avant = appels["collecte"]
        C.traiter(cx, bom.iloc[[0]], CLASSES, PRIX, REGLES, C.Reglages(recollecter=True), masses, collecteur, Modele())
        assert appels["collecte"] == avant + 1                # sur demande, la recherche est refaite


def test_collecte_sans_modele_puis_avec_et_echec_repris():
    """Une collecte faite sans modèle n'a rien pu lire : elle est refaite quand un modèle est branché ; un échec aussi."""
    appels = {"collecte": 0, "echecs": 0}

    def collecteur(requete):
        appels["collecte"] += 1
        return [{"origine": "fiche", "texte": "aluminium heat sink", "nature": "document"}]

    def en_panne(requete):
        appels["echecs"] += 1
        raise TimeoutError("réseau")

    bom = pd.DataFrame([achetee("B1", "Dissipateur", "AC-9")])
    with K.Cortex(":memory:") as cx:
        C.traiter(cx, bom, CLASSES, PRIX, None, masses={"B1": 500.0}, collecteur=en_panne)
        assert list(cx.journal(D)["resultat"]) == ["échec : TimeoutError"]       # le texte de l'erreur n'est pas gardé
        C.traiter(cx, bom, CLASSES, PRIX, None, masses={"B1": 500.0}, collecteur=collecteur)          # l'échec n'empêche pas de réessayer
        assert appels == {"collecte": 1, "echecs": 1}
        C.traiter(cx, bom, CLASSES, PRIX, None, masses={"B1": 500.0}, collecteur=collecteur)          # sans modèle : déjà cherchée
        assert appels["collecte"] == 1
        t = C.traiter(cx, bom, CLASSES, PRIX, None, masses={"B1": 500.0}, collecteur=collecteur, modele=ModeleTest("Métal"))
        assert appels["collecte"] == 2 and t["Composition proposée"]["Classe retenue"][0] == "Métal"


def test_panne_du_modele_rien_n_est_compte_et_la_lecture_est_reprise():
    class EnPanne:
        def extraire(self, document, classes):
            raise C.Indisponible("TimeoutError")

    esp = Espion({"MPN-1": FICHE})
    with K.Cortex(":memory:") as cx:
        r = C.resoudre(cx, achetee("p1", "Module à préciser"), CLASSES, PRIX, REGLES, masse_annuelle_kg=500.0, collecteur=esp, modele=EnPanne())
        j = cx.journal(D)
        assert list(j["resultat"]) == ["échec : Indisponible", "1 document(s), à reprendre"] and list(j["cout"]) == [0.0, 0.02]
        assert r["Appels au modèle"] == 0 and r["Statut"] == "inconnue"
        mod = ModeleTest("Câble")
        r = C.resoudre(cx, achetee("p1", "Module à préciser"), CLASSES, PRIX, REGLES, masse_annuelle_kg=500.0, collecteur=esp, modele=mod)
        assert len(esp.requetes) == 2 and mod.lectures == 1 and r["Classe retenue"] == "Câble"


def test_documents_abimes_et_reponses_hors_liste_sans_arret():
    class Bizarre:
        def extraire(self, document, classes):
            return "Céramique hors liste", "citation"

        def valider(self, classe, document):
            return "oui"                                      # ni True ni False : ne tranche pas

    for documents in (["du texte brut"], [None], {"origine": "x"}, "une chaîne", [{"origine": None, "texte": None}], [{"texte": 12.5}]):
        with K.Cortex(":memory:") as cx:
            r = C.resoudre(cx, achetee("p1", "Module à préciser"), CLASSES, PRIX, REGLES, masse_annuelle_kg=500.0,
                           collecteur=lambda q, d=documents: d, modele=Bizarre())
            assert r["Statut"] == "inconnue" and r["Classe retenue"] is None, documents
            assert "collecte" in list(cx.journal(D)["action"])
    with K.Cortex(":memory:") as cx:                         # une classe hors liste rendue par un modèle n'est pas enregistrée
        r = C.resoudre(cx, achetee("p1", "Module à préciser"), CLASSES, PRIX, REGLES, masse_annuelle_kg=500.0,
                       collecteur=Espion({"MPN-1": FICHE}), modele=Bizarre())
        assert r["Preuves"] == 0 and list(cx.journal(D)["resultat"])[0] == "sans réponse fondée"


# ------------------------------------------------------------------ confidentialité
def test_rien_d_interne_ne_sort():
    secret_pn, secret_desc = "INT-778899", "Capot spécial projet Aurore"
    esp = Espion({"MPN-9": [{"origine": "site-a", "nature": "document", "texte": "Texte public."}]})
    mod = ModeleTest("Plastique")
    pns = frozenset({"INT-778899", "INT-2", "INT-3", "INT-4", "INT-5", "INT-6", "INT-7"})
    g = C.Reglages(fabricants_internes=("Atelier interne site X",))
    cas = [achetee(secret_pn, secret_desc, "MPN-9"),                                                      # seule pièce recherchée
           achetee("INT-2", "Autre pièce maison", "MPN-9", Interne=True),                                  # déclarée interne
           piece("INT-3", "Sans référence fabricant"),
           piece("INT-4", "Code interne dans la colonne référence", **{"Fabricant": "Fab", "Référence fabricant": "INT-4"}),
           piece("INT-5", "Code d'une autre pièce", **{"Fabricant": "Fab", "Référence fabricant": "int-778899"}),
           piece("INT-6", "Texte libre", **{"Fabricant": "Fab", "Référence fabricant": "voir plan INT-1 rev B projet Aurore, bureau d'études"}),
           piece("INT-7", "Fabriquée par l'entreprise", **{"Fabricant": "atelier INTERNE site x", "Référence fabricant": "MPN-9"}),
           piece("INT-8", "Référence sans fabricant", **{"Référence fabricant": "MPN-9"})]
    with K.Cortex(":memory:") as cx:
        for p in cas:
            C.resoudre(cx, p, CLASSES, PRIX, REGLES, g, masse_annuelle_kg=500.0, collecteur=esp, modele=mod, pns=pns)
    assert len(esp.requetes) == 1 and esp.requetes[0] == {"fabricant": "Fabricant F", "reference_fabricant": "MPN-9", "type": esp.requetes[0]["type"]}
    sorti = json.dumps(esp.requetes, ensure_ascii=False) + " ".join(mod.textes)
    for interdit in (secret_pn, secret_desc, "Aurore", "INT-", "Atelier", "plan"):
        assert interdit not in sorti
    assert esp.requetes[0]["type"] in ("",) or esp.requetes[0]["type"] not in secret_desc


def test_colonne_interne_tout_ce_qui_n_est_pas_non_vaut_interne(tmp_path):
    for v in ("M", "internal", "in-house", "maison", "X", "fabriqué", "1.0", "interne (plan)", "oui", "make", True, 1):
        assert C._est_interne(v), v
    for v in ("non", "No", " N ", "buy", "Achat", "acheté", "0", 0, 0.0, False, None, float("nan"), ""):
        assert not C._est_interne(v), v
    f = tmp_path / "bom.csv"
    f.write_bytes("Code article;Désignation;Make/Buy;Fabricant;MPN\nA1;Câble blindé;M;Fab;M-1\nA2;Vis;buy;Fab;M-2\n".encode("cp1252"))
    b = C.lire_bom(f)                                         # export Excel sous Windows : encodage cp1252
    assert list(b["Interne"]) == [True, False] and b.loc[0, "Description"] == "Câble blindé"
    assert C.requete_publique(b.iloc[0].to_dict()) is None and C.requete_publique(b.iloc[1].to_dict())["reference_fabricant"] == "M-2"


def test_modele_distant_refuse_sauf_accord_explicite():
    with pytest.raises(ValueError, match="n'est pas sur ce poste"):
        C.ModeleLocal("https://api.exemple-distant.example/v1", cle="k")
    assert C.ModeleLocal("https://api.exemple-distant.example/v1", cle="k", distant=True).url.endswith("/v1")
    assert C.ModeleLocal("http://127.0.0.1:1234/v1").modele == "qwen" and C.ModeleLocal("http://localhost:11434/v1")


# ------------------------------------------------------------------ nomenclature
def test_lecture_de_la_nomenclature(tmp_path):
    f = tmp_path / "bom.xlsx"
    pd.DataFrame({"Code article": [5123.0, " ab-1 ", "ab-1"], "Désignation": ["Board", "Cable", "Cable bis"], "MPN": ["M1", None, None],
                  "Make/Buy": ["buy", "make", "make"], "Poids": ["0,5", None, None]}).to_excel(f, index=False)
    b = C.lire_bom(f)
    assert list(b["PN"]) == ["5123", "AB-1"] and list(b["Interne"]) == [False, True]
    assert b.loc[0, "Référence fabricant"] == "M1" and math.isclose(b.loc[0, "Poids (kg)"], 0.5)
    pd.DataFrame({"Truc": [1]}).to_excel(f, index=False)
    with pytest.raises(ValueError, match="Nomenclature illisible"):
        C.lire_bom(f)


def test_resultat_independant_de_l_ordre_et_codes_repetes():
    lignes = [piece("a", "Controller board"), piece("b", "Power cable"), piece("c", "Cooling module"), piece("d", "Main board assy")]
    bom = pd.DataFrame(lignes)
    resultats = []
    for ordre in ([0, 1, 2, 3], [3, 2, 1, 0]):
        with K.Cortex(":memory:") as cx:
            cx.declarer(D, "a", "Controller board")
            cx.valider(D, "a", A, "Carte", "expert")
            t = C.traiter(cx, bom.iloc[ordre].reset_index(drop=True), CLASSES, PRIX, REGLES)["Composition proposée"]
            resultats.append(t.set_index("PN").sort_index()[["Classe retenue", "Probabilité", "Statut"]])
    pd.testing.assert_frame_equal(resultats[0], resultats[1])
    assert resultats[0].at["d", "Classe retenue"] == "Carte" and resultats[0].at["c", "Statut"] == "inconnue"
    with K.Cortex(":memory:") as cx:                         # un code article répété : la première ligne est gardée, et c'est dit
        t = C.traiter(cx, pd.DataFrame([piece("a", "Controller board"), piece("a", "Power cable")]), CLASSES, PRIX, REGLES)
        assert len(t["Composition proposée"]) == 1 and t["Composition proposée"]["Classe retenue"][0] == "Carte"
        assert t["Notes"]["codes_article_repetes_ignores"] == 1 and len(cx.affirmations(D, A, "a")) == 1
    with K.Cortex(":memory:") as cx:                         # pièces sans description : aucune analogie entre elles
        bom = pd.DataFrame([piece("v1", float("nan")), piece("v2", None), piece("v3", float("nan"))])
        cx.declarer(D, "v1", float("nan"))
        cx.valider(D, "v1", A, "Carte", "expert")
        t = C.traiter(cx, bom, CLASSES, PRIX, REGLES)["Composition proposée"].set_index("PN")
        assert t.at["v2", "Statut"] == "inconnue" and t.at["v3", "Statut"] == "inconnue" and t.at["v2", "Description"] == ""


def test_validations_importees_avec_leur_motif():
    with K.Cortex(":memory:") as cx:
        t = pd.DataFrame({"PN": ["a1", " b2 ", None, "c3"], "Classe validée": ["Carte", "Câble", "Métal", " "],
                          "Validateur": ["Camille", None, "x", "x"], "Motif": ["sondage", "file", "", ""]})
        assert C.importer_validations(cx, t) == 2 and C.importer_validations(cx, t) == 0
        assert cx.verites(D, A) == {"A1": "Carte", "B2": "Câble"} and cx.motifs(D, A) == {"A1": "sondage", "B2": "file"}
        assert C.importer_validations(cx, pd.DataFrame({"PN": ["a1"], "Classe validée": ["Métal"]})) == 1 and cx.motifs(D, A)["A1"] == ""


# ------------------------------------------------------------------ modèle local : garde-fous
class Serveur(BaseHTTPRequestHandler):
    reponse = ""

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        corps = json.dumps({"choices": [{"message": {"content": type(self).reponse}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(corps)

    def log_message(self, *a):
        pass


@pytest.fixture()
def serveur():
    s = HTTPServer(("127.0.0.1", 0), Serveur)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}/v1"
    s.shutdown()


def test_modele_local_reponse_fondee_ou_rejetee(serveur):
    m = C.ModeleLocal(serveur, "qwen-test", delai=5)
    document = "Fiche : assemblage de circuit imprimé multicouche, conforme RoHS."
    Serveur.reponse = 'Voici : {"classe": "Carte", "citation": "circuit imprimé multicouche"}'
    assert m.extraire(document, CLASSES) == ("Carte", "circuit imprimé multicouche")
    Serveur.reponse = '{"classe": "Carte", "citation": "contient de l\'or et du palladium"}'      # citation absente du document
    assert m.extraire(document, CLASSES) == (None, "")
    Serveur.reponse = '{"classe": "Céramique", "citation": "circuit imprimé multicouche"}'        # classe hors de la liste
    assert m.extraire(document, CLASSES) == (None, "")
    Serveur.reponse = "je ne sais pas"
    assert m.extraire(document, CLASSES) == (None, "")
    for brut, attendu in (('{"verdict": "oui"}', True), ('{"verdict": "non"}', False), ('{"verdict": "indetermine"}', None), ("???", None)):
        Serveur.reponse = brut
        assert m.valider("Carte", document) is attendu
    assert m.appels == 8
    with pytest.raises(C.Indisponible):                       # serveur absent : une panne n'est pas une réponse
        C.ModeleLocal("http://127.0.0.1:9/v1", delai=1).extraire(document, CLASSES)


# ------------------------------------------------------------------ dans le dossier
def test_demonstration_de_bout_en_bout(tmp_path):
    cfg = erc.charger_config(dossier=tmp_path, demo=True)
    cfg.figures, cfg.n_monte_carlo = False, 20
    ctx = erc.executer("ligne", cfg=cfg, silencieux=True)
    t = C.executer(ctx)
    res, notes = t["Composition proposée"], t["Notes"]
    assert notes["fournisseurs_fictifs"] and notes["validations_importees"] == 6 and len(res) == notes["pieces"] > 15
    assert set(res["Statut"]) <= {"validée", "acceptée", "à valider", "inconnue"}
    assert int((res["Appels au modèle"] > 0).sum()) <= 3 and notes["pieces_sans_appel_payant"] >= len(res) - 3    # la plupart des pièces ne demandent aucun appel
    assert notes["appels_au_modele"] <= 9 and notes["descriptions_lues_par_le_modele"] is True and notes["modele_heberge"] == "ce poste"
    assert notes["traitement_evite_dans_l_enjeu"] == "compté"
    vraies = res.set_index("PN")
    assert vraies.at["P-5001", "Classe retenue"] == "Carte C"                                         # la règle « board → Carte B » est corrigée par les autres sources
    f = t["Fiabilité des sources"].set_index("Type de source")
    assert f.at["règle", "Fausses"] >= 1 and f.at["règle", "Fiabilité"] < f.at["classement antérieur", "Fiabilité"]
    assert (ctx.cfg.artefacts / "composition" / "Composition_proposee.csv").is_file() and cfg.cortex.is_file()
    assert list(t["Valeur de l'information"].columns) == list(erc.information.COLS_CLASSES) if hasattr(erc, "information") else True
    assert not ctx.anomalies


def test_une_validation_ne_revient_pas_comme_preuve_et_une_classe_acceptee_complete_le_dossier(tmp_path):
    """Valider une pièce contre son classement antérieur, puis relancer deux fois : ce classement reste compté faux.
    Une classe acceptée par la chaîne complète le classement du dossier là où il était vide, sans jamais devenir une
    preuve de plus au passage suivant."""
    cfg = erc.charger_config(dossier=tmp_path, demo=True)
    cfg.figures, cfg.n_monte_carlo = False, 20
    ctx = erc.executer("ligne", cfg=cfg, silencieux=True)
    C.executer(ctx)
    with K.Cortex(cfg.cortex) as cx:
        assert cx.affirmations(D, A, "P-1002").set_index("type_source").at["classement antérieur", "valeur"] == "Composant de puissance"
        cx.valider(D, "P-1002", A, "Carte B", "expert")                         # la personne contredit le classement antérieur
        cx.conclure(D, "P-NEUVE", A, "Métal", 0.94, "acceptée")                  # une pièce absente du classement, acceptée par la chaîne
        cx.conclure(D, "P-1003", A, "Métal", 0.94, "acceptée")                   # une pièce déjà classée : son classement n'est pas remplacé
    for _ in range(2):
        ctx = erc.executer("ligne", cfg=cfg, silencieux=True)
        cl = ctx.src.classification
        assert cl.at["P-1002", "Catégorie proposée"] == "Carte B" and cl.at["P-1002", "Niveau de preuve"].startswith("cortex : classe validée")
        assert cl.at["P-NEUVE", "Catégorie proposée"] == "Métal" and "acceptée, non validée" in cl.at["P-NEUVE", "Niveau de preuve"]
        assert cl.at["P-1003", "Catégorie proposée"] == "Condensateur"
        t = C.executer(ctx)
        f = t["Fiabilité des sources"].set_index("Type de source")
        assert f.at["classement antérieur", "Fausses"] >= 1, "le classement contredit par la validation doit rester compté faux"
        with K.Cortex(cfg.cortex) as cx:
            a = cx.affirmations(D, A, "P-1002").set_index("type_source")
            assert a.at["classement antérieur", "valeur"] == "Composant de puissance"
            assert "classement antérieur" not in set(cx.affirmations(D, A, "P-NEUVE")["type_source"]) if len(cx.affirmations(D, A, "P-NEUVE")) else True
