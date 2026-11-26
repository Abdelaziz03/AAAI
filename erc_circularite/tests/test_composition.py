"""Cortex (base de connaissance à sources faillibles) et chaîne de composition des nomenclatures.
Aucun accès au réseau : les fournisseurs sont des doublures, le serveur de modèle est un serveur local de test."""
import json
import math
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


def piece(pn, description, **plus):
    return dict({"PN": pn, "Description": description, "FRU": None, "Quantité": None, "Fabricant": None,
                 "Référence fabricant": None, "Interne": False, "Poids (kg)": None}, **plus)


# ------------------------------------------------------------------ cortex : fusion des preuves
def test_fusion_une_source_puis_deux():
    """Une source de fiabilité r sur C classes : P = r. Deux sources d'accord : r1 r2 / (r1 r2 + (C−1) (1−r1)(1−r2)/(C−1)²)."""
    with K.Cortex(":memory:") as cx:
        cx.affirmer(D, "x", A, "Carte", "règle", "règle : board")
        r1 = K.A_PRIORI_SOURCES["règle"]
        b = cx.croyance(D, "x", A, CLASSES)
        assert math.isclose(b["probabilite"], r1) and b["retenue"] == "Carte" and not b["validee"]
        cx.affirmer(D, "x", A, "Carte", "document", "site-a")
        r2 = K.A_PRIORI_SOURCES["document"]
        attendu = r1 * r2 / (r1 * r2 + 3 * ((1 - r1) / 3) * ((1 - r2) / 3))
        assert math.isclose(cx.croyance(D, "x", A, CLASSES)["probabilite"], attendu)
        assert math.isclose(sum(cx.croyance(D, "x", A, CLASSES)["probabilites"].values()), 1.0)


def test_une_origine_ne_compte_qu_une_fois_et_negation():
    with K.Cortex(":memory:") as cx:
        for _ in range(5):                                    # la même page relue cinq fois reste une preuve
            cx.affirmer(D, "x", A, "Carte", "document", "site-a")
        p1 = cx.croyance(D, "x", A, CLASSES)["probabilite"]
        assert cx.croyance(D, "x", A, CLASSES)["preuves"] == 1 and math.isclose(p1, K.A_PRIORI_SOURCES["document"])
        cx.affirmer(D, "x", A, "Carte", "modèle : validation", "site-a # contrôle", polarite=-1)   # un contrôle qui contredit
        r, rv = K.A_PRIORI_SOURCES["document"], K.A_PRIORI_SOURCES["modèle : validation"]
        attendu = r * (1 - rv) / (r * (1 - rv) + 3 * ((1 - r) / 3) * rv)
        assert math.isclose(cx.croyance(D, "x", A, CLASSES)["probabilites"]["Carte"], attendu) and attendu < p1


def test_sans_preuve_inconnu_et_validation_fait_foi():
    with K.Cortex(":memory:") as cx:
        b = cx.croyance(D, "x", A, CLASSES)
        assert b["retenue"] is None and math.isnan(b["probabilite"]) and b["preuves"] == 0
        cx.affirmer(D, "x", A, "Carte", "règle", "r")
        cx.valider(D, "x", A, "Câble", "expert")
        b = cx.croyance(D, "x", A, CLASSES)
        assert b["validee"] and b["retenue"] == "Câble" and b["probabilite"] == 1.0
        cx.valider(D, "x", A, "Métal", "expert")              # la dernière validation fait foi
        assert cx.verite(D, "x", A) == "Métal"


def test_fiabilite_apprise_des_validations():
    with K.Cortex(":memory:") as cx:
        for i, (dit, vrai) in enumerate([("Carte", "Carte"), ("Carte", "Carte"), ("Carte", "Câble"), ("Câble", "Câble")]):
            cx.affirmer(D, f"s{i}", A, dit, "règle", "r")
            cx.valider(D, f"s{i}", A, vrai, "expert")
        cx.affirmer(D, "non_valide", A, "Carte", "règle", "r")   # sans validation : ne compte pas
        f = cx.fiabilites(D, A).set_index("Type de source").loc["règle"]
        assert (f["Affirmations vérifiées"], f["Justes"], f["Fausses"]) == (4, 3, 1)
        m0, F = K.A_PRIORI_SOURCES["règle"], K.FORCE_A_PRIORI
        assert math.isclose(f["Fiabilité"], (m0 * F + 3) / (F + 4))


def test_voisins_valides_seulement():
    with K.Cortex(":memory:") as cx:
        cx.declarer(D, "a", "Gate driver board rev B")
        cx.declarer(D, "b", "Gate driver board rev C")
        cx.declarer(D, "c", "Cooling fan 120 mm")
        assert cx.voisins(D, A, "Gate driver board rev D") == []          # personne n'est validé
        cx.valider(D, "a", A, "Carte", "expert")
        v = cx.voisins(D, A, "Gate driver board rev D", seuil=0.5)
        assert [x[0] for x in v] == ["a"] and v[0][2] == "Carte" and 0.5 <= v[0][1] <= 1
        assert cx.voisins(D, A, "Gate driver board rev B", sauf="a") == []  # une pièce n'est pas sa propre voisine


# ------------------------------------------------------------------ chaîne : arrêt au plus tôt, enjeu, confidentialité
def test_enjeu():
    assert math.isclose(C.enjeu(100.0, {"Carte": 0.5, "Plastique": 0.5}, PRIX), 100 * 0.5 * (8.0 - 0.05))
    assert C.enjeu(100.0, {"Carte": 1.0}, PRIX) == 0.0                     # une seule classe possible : rien à apprendre
    assert math.isnan(C.enjeu(None, {"Carte": 0.5, "Plastique": 0.5}, PRIX))
    assert math.isnan(C.enjeu(100.0, {"Carte": 0.5, "Inconnue": 0.5}, PRIX))   # prix d'une classe plausible inconnu


class Espion:
    """Collecteur de test : note chaque requête et rend les documents prévus."""

    def __init__(self, documents=None):
        self.requetes, self.documents = [], documents or {}

    def __call__(self, requete):
        self.requetes.append(requete)
        return self.documents.get(requete["reference_fabricant"], [])


class ModeleTest:
    def __init__(self, classe="Carte", verdict=True):
        self.classe, self.verdict, self.textes = classe, verdict, []

    def extraire(self, texte, classes):
        self.textes.append(texte)
        return (self.classe, "citation") if self.classe else (None, "")

    def valider(self, classe, texte):
        self.textes.append(texte)
        return self.verdict


def test_piece_legere_aucun_appel_payant():
    """Même avec un collecteur et un modèle branchés, une pièce dont l'enjeu est sous le coût ne déclenche rien."""
    esp, mod = Espion(), ModeleTest()
    with K.Cortex(":memory:") as cx:
        r = C.resoudre(cx, piece("p1", "Vis M4", **{"Fabricant": "F", "Référence fabricant": "MPN-1"}), CLASSES, PRIX, REGLES,
                       masse_annuelle_kg=0.01, collecteur=esp, modele=mod)
        assert esp.requetes == [] and mod.textes == [] and r["Appels au modèle"] == 0 and r["Coût des acquisitions (€)"] == 0
        assert r["Statut"] == "à valider" and r["Prochaine action"].startswith("aucune")
        assert len(cx.journal(D)) == 0


def test_chaine_payante_et_minimum_d_appels():
    docs = {"MPN-1": [{"origine": "site-a", "nature": "document", "texte": "Fiche technique sans mot-clé."}]}
    esp, mod = Espion(docs), ModeleTest("Câble", True)
    with K.Cortex(":memory:") as cx:
        r = C.resoudre(cx, piece("p1", "Module à préciser", **{"Fabricant": "F", "Référence fabricant": "MPN-1"}), CLASSES, PRIX, REGLES,
                       masse_annuelle_kg=500.0, collecteur=esp, modele=mod)
        j = cx.journal(D)
        assert list(j["action"]) == ["collecte", "lecture par le modèle", "contrôle par le modèle"]   # lecture, puis contrôle car doute
        assert r["Appels au modèle"] == 2 and r["Classe retenue"] == "Câble" and r["Statut"] == "acceptée"
        assert math.isclose(r["Coût des acquisitions (€)"], 0.02 + 0.05 + 0.03)


def test_un_document_n_est_pas_relu_avec_les_regles():
    """La même règle appliquée à la description puis au document ne fait pas deux sources : sans modèle, un document
    ordinaire qui contient un mot-clé n'ajoute aucune preuve."""
    docs = {"MPN-1": [{"origine": "site-a", "nature": "document", "texte": "Notice : montage sur carte mère, board level."}]}
    with K.Cortex(":memory:") as cx:
        r = C.resoudre(cx, piece("p1", "Controller board", **{"Fabricant": "F", "Référence fabricant": "MPN-1"}), CLASSES, PRIX, REGLES,
                       masse_annuelle_kg=500.0, collecteur=Espion(docs), modele=None)
        assert r["Preuves"] == 1 and r["Sources"] == "règle" and math.isclose(r["Probabilité"], K.A_PRIORI_SOURCES["règle"])
    docs["MPN-1"][0]["nature"] = "déclaration fabricant"       # une déclaration du fabricant, elle, nomme les matières
    with K.Cortex(":memory:") as cx:
        r = C.resoudre(cx, piece("p1", "Controller board", **{"Fabricant": "F", "Référence fabricant": "MPN-1"}), CLASSES, PRIX, REGLES,
                       masse_annuelle_kg=500.0, collecteur=Espion(docs), modele=None)
        assert r["Preuves"] == 2 and "déclaration fabricant" in r["Sources"] and r["Statut"] == "acceptée"


def test_rien_d_interne_ne_sort():
    secret_pn, secret_desc = "INT-778899", "Capot spécial projet Aurore"
    esp = Espion({"MPN-9": [{"origine": "site-a", "nature": "document", "texte": "Texte public."}]})
    mod = ModeleTest("Plastique")
    with K.Cortex(":memory:") as cx:
        C.resoudre(cx, piece(secret_pn, secret_desc, **{"Fabricant": "Fab", "Référence fabricant": "MPN-9"}), CLASSES, PRIX, REGLES,
                   masse_annuelle_kg=500.0, collecteur=esp, modele=mod)
        C.resoudre(cx, piece("INT-2", "Autre pièce maison", **{"Fabricant": "Fab", "Référence fabricant": "MPN-9", "Interne": True}), CLASSES, PRIX, REGLES,
                   masse_annuelle_kg=500.0, collecteur=esp, modele=mod)
        C.resoudre(cx, piece("INT-3", "Sans référence fabricant"), CLASSES, PRIX, REGLES, masse_annuelle_kg=500.0, collecteur=esp, modele=mod)
    assert len(esp.requetes) == 1                               # la pièce interne et la pièce sans référence ne sont jamais recherchées
    sorti = json.dumps(esp.requetes, ensure_ascii=False) + " ".join(mod.textes)
    for interdit in (secret_pn, secret_desc, "Aurore", "INT-2", "INT-3"):
        assert interdit not in sorti
    assert set(esp.requetes[0]) == {"fabricant", "reference_fabricant", "type"}


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


def test_resultat_independant_de_l_ordre():
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
    texte = "Fiche : assemblage de circuit imprimé multicouche, conforme RoHS."
    Serveur.reponse = 'Voici : {"classe": "Carte", "citation": "circuit imprimé multicouche"}'
    assert m.extraire(texte, CLASSES) == ("Carte", "circuit imprimé multicouche")
    Serveur.reponse = '{"classe": "Carte", "citation": "contient de l\'or et du palladium"}'      # citation absente du document
    assert m.extraire(texte, CLASSES) == (None, "")
    Serveur.reponse = '{"classe": "Céramique", "citation": "circuit imprimé multicouche"}'        # classe hors de la liste
    assert m.extraire(texte, CLASSES) == (None, "")
    Serveur.reponse = "je ne sais pas"
    assert m.extraire(texte, CLASSES) == (None, "")
    for brut, attendu in (('{"verdict": "oui"}', True), ('{"verdict": "non"}', False), ('{"verdict": "indetermine"}', None), ("???", None)):
        Serveur.reponse = brut
        assert m.valider("Carte", texte) is attendu
    assert m.appels == 8
    assert C.ModeleLocal("http://127.0.0.1:9/v1", delai=1).extraire(texte, CLASSES) == (None, "")   # serveur absent : pas d'exception


# ------------------------------------------------------------------ dans le dossier
def test_demonstration_de_bout_en_bout(tmp_path):
    cfg = erc.charger_config(dossier=tmp_path, demo=True)
    cfg.figures, cfg.n_monte_carlo = False, 20
    ctx = erc.executer("ligne", cfg=cfg, silencieux=True)
    t = C.executer(ctx)
    res, notes = t["Composition proposée"], t["Notes"]
    assert notes["fournisseurs_fictifs"] and notes["validations_importees"] == 6 and len(res) == notes["pieces"] > 15
    assert set(res["Statut"]) <= {"validée", "acceptée", "à valider", "inconnue"}
    assert notes["appels_au_modele"] <= 5 and notes["pieces_sans_appel_payant"] >= len(res) - 3    # peu d'appels : la plupart des pièces n'en demandent aucun
    vraies = res.set_index("PN")
    assert vraies.at["P-5001", "Classe retenue"] == "Carte C"                                         # la règle « board → Carte B » est corrigée par les autres sources
    f = t["Fiabilité des sources"].set_index("Type de source")
    assert f.at["règle", "Fausses"] >= 1 and f.at["règle", "Fiabilité"] < f.at["classement antérieur", "Fiabilité"]
    assert (ctx.cfg.artefacts / "composition" / "Composition_proposee.csv").is_file() and cfg.cortex.is_file()
    assert not ctx.anomalies
    # une classe validée dans le cortex devient une donnée du dossier à l'exécution suivante
    with K.Cortex(cfg.cortex) as cx:
        cx.valider(D, "P-6001", A, "Carte B", "expert")
    ctx2 = erc.executer("sources", cfg=cfg, silencieux=True)
    assert ctx2.src.classification.at["P-6001", "Catégorie proposée"] == "Carte B"
