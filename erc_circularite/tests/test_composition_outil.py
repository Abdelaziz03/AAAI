"""Page de revue de la composition : contenu fidèle au cortex, fichier autonome, et boucle fermée
(décisions prises dans la page → fichier CSV → validations dans le cortex au passage suivant).

Les fonctions sans affichage de la page sont exécutées avec node ; ces tests sont sautés si node n'est pas installé."""
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
import erc  # noqa: E402
from erc import composition as C, composition_outil as P, cortex as K  # noqa: E402

NODE = shutil.which("node")
SCRIPT = RACINE / "tests" / "composition_logique.mjs"


@pytest.fixture(scope="module")
def passage(tmp_path_factory):
    dossier = tmp_path_factory.mktemp("dossier_revue")
    cfg = erc.charger_config(dossier=str(dossier), demo=True)
    ctx = erc.executer(jusqua="ligne", cfg=cfg, silencieux=True)
    tables = C.executer(ctx)
    return cfg, ctx, tables


def donnees_de(page: Path) -> dict:
    m = re.search(r'<script type="application/json" id="donnees">(.*?)</script>', page.read_text(encoding="utf-8"), re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


def logique(entree: dict) -> dict:
    r = subprocess.run([NODE, str(SCRIPT), str(P.GABARIT)], input=json.dumps(entree), capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ------------------------------------------------------------------ contenu
def test_page_deposee_et_fidele_aux_tables(passage):
    cfg, ctx, tables = passage
    page = cfg.artefacts / "composition" / P.NOM_PAGE
    assert page.is_file()
    d = donnees_de(page)
    res = tables["Composition proposée"]
    assert [p["pn"] for p in d["pieces"]] == res["PN"].astype(str).tolist()
    par = {p["pn"]: p for p in d["pieces"]}
    for _, r in res.iterrows():
        p = par[str(r["PN"])]
        assert p["statut"] == r["Statut"] and p["classe"] == (r["Classe retenue"] if isinstance(r["Classe retenue"], str) else None)
        assert len(p["preuves"]) == r["Preuves"]
        if p["probabilites"] and p["statut"] != "validée":      # la croyance affichée est celle que la chaîne a utilisée
            assert abs(max(p["probabilites"].values()) - r["Probabilité"]) < 1e-9
            assert max(p["probabilites"], key=p["probabilites"].get) == p["classe"]
    assert d["demo"] is True and d["fournisseurs_fictifs"] is True
    assert set(d["sondage"]) <= {p["pn"] for p in d["pieces"] if p["statut"] == "acceptée"}
    assert {f["type"] for f in d["fiabilites"]} >= set(K.A_PRIORI_SOURCES)
    assert ("composition", "Page de revue", "outil") in ctx.depot._entrees      # inscrite au manifeste du dossier


def test_page_autonome(passage):
    cfg, _, _ = passage
    texte = (cfg.artefacts / "composition" / P.NOM_PAGE).read_text(encoding="utf-8")
    sans_donnees = re.sub(r'<script type="application/json" id="donnees">.*?</script>', "", texte, flags=re.S)
    assert not re.search(r'(src|href)\s*=\s*"(https?:)?//', sans_donnees), "aucune ressource extérieure"
    assert "@import" not in sans_donnees and "url(" not in sans_donnees
    assert "__ERC_" not in texte and "--fond:" in texte        # repères remplacés, palette du dossier reprise
    assert texte.count("<html") == 1 and texte.rstrip().endswith("</html>")


def test_fragment_pour_hebergeur(passage, tmp_path):
    cfg, _, _ = passage
    d = donnees_de(cfg.artefacts / "composition" / P.NOM_PAGE)
    f = P.construire(d, tmp_path / "revue_fragment.html", fragment=True).read_text(encoding="utf-8")
    assert f.startswith("<title>") and "<html" not in f and "<body" not in f and "claude:viewport-fit-sides" in f
    assert donnees_de(tmp_path / "revue_fragment.html") == d


def test_sondage_repetable_et_borne():
    res = pd.DataFrame({"PN": [f"P{i:03d}" for i in range(100)], "Statut": ["acceptée"] * 60 + ["à valider"] * 40})
    a, b = P.sondage(res, n=20, graine=3), P.sondage(res, n=20, graine=3)
    assert a == b and len(a) == 20 and set(a) <= set(res["PN"][:60])
    assert P.sondage(res, n=20, graine=4) != a
    assert P.sondage(res.iloc[:5], n=20) == sorted(res["PN"][:5])


# ------------------------------------------------------------------ logique de la page (node)
@pytest.mark.skipif(NODE is None, reason="node n'est pas installé")
def test_files_recherche_et_compte(passage):
    cfg, _, tables = passage
    d = donnees_de(cfg.artefacts / "composition" / P.NOM_PAGE)
    s = logique({"pieces": d["pieces"], "sondage": d["sondage"], "decisions": {}, "validateur": "", "recherche": "RADIATEUR"})
    res = tables["Composition proposée"]
    statut = dict(zip(res["PN"].astype(str), res["Statut"]))
    assert set(s["files"]["a-valider"]) == {k for k, v in statut.items() if v in ("à valider", "inconnue")}
    assert set(s["files"]["acceptees"]) == {k for k, v in statut.items() if v == "acceptée"}
    assert set(s["files"]["validees"]) == {k for k, v in statut.items() if v == "validée"}
    assert s["files"]["sondage"] == sorted(d["sondage"]) and s["files"]["decisions"] == []
    assert s["files"]["toutes"] == sorted(statut)
    enjeux = [next(p["enjeu"] for p in d["pieces"] if p["pn"] == pn) for pn in s["files"]["a-valider"]]
    connus = [e for e in enjeux if e is not None]
    assert connus == sorted(connus, reverse=True) and enjeux[: len(connus)] == connus      # enjeu décroissant, inconnus en dernier
    attendu = {str(r["PN"]) for _, r in res.iterrows() if "radiateur" in str(r["Description"]).lower()}
    assert attendu and set(s["recherche"]) == attendu          # la recherche ignore la casse et les accents
    n = s["compte"]
    assert n["total"] == len(res) and n["validée"] + n["acceptée"] + n["à valider"] + n["inconnue"] == len(res)
    assert n["appels"] == int(res["Appels au modèle"].sum()) and abs(n["cout"] - res["Coût des acquisitions (€)"].sum()) < 1e-9
    for p in d["pieces"]:                                       # les parts affichées somment à 1 (ou à la seule probabilité connue)
        parts = s["partages"][p["pn"]]
        if p["probabilites"]:
            assert abs(sum(x["part"] for x in parts) - sum(p["probabilites"].values())) < 1e-9 and len(parts) <= 3


@pytest.mark.skipif(NODE is None, reason="node n'est pas installé")
def test_boucle_fermee_decisions_vers_cortex(passage, tmp_path):
    """Des décisions prises dans la page, avec des caractères pénibles, reviennent dans le cortex à l'identique."""
    cfg, ctx, tables = passage
    d = donnees_de(cfg.artefacts / "composition" / P.NOM_PAGE)
    a_valider = [p for p in d["pieces"] if p["statut"] == "à valider"]
    acceptee = next(p for p in d["pieces"] if p["statut"] == "acceptée")
    autre = next(c for c in d["classes"] if c != acceptee["classe"])
    # le motif de chaque décision : pièce de la file, pièce acceptée tirée au sondage, ou autre
    motifs = logique({"pieces": d["pieces"], "sondage": d["sondage"], "decisions": {}, "validateur": ""})["motifs"]
    assert motifs[a_valider[0]["pn"]] == "file" and motifs[acceptee["pn"]] == ("sondage" if acceptee["pn"] in d["sondage"] else "choix")
    assert all(m == "choix" for pn, m in motifs.items() if next(p for p in d["pieces"] if p["pn"] == pn)["statut"] == "validée")
    decisions = {a_valider[0]["pn"]: {"classe": a_valider[0]["classe"], "commentaire": 'vu sur pièce ; marquage "inox"\nà revoir', "motif": "file"},
                 acceptee["pn"]: {"classe": autre, "commentaire": "", "motif": motifs[acceptee["pn"]]}}
    s = logique({"pieces": d["pieces"], "sondage": d["sondage"], "decisions": decisions, "validateur": "Camille ; Atelier"})
    assert sorted(s["files"]["decisions"]) == sorted(decisions)
    lu = pd.read_csv(io.StringIO(s["csv"]), sep=";", dtype=object)
    assert list(lu.columns) == ["PN", "Classe validée", "Validateur", "Commentaire", "Motif"] and len(lu) == 2
    assert lu.set_index("PN")["Motif"].to_dict() == {a_valider[0]["pn"]: "file", acceptee["pn"]: motifs[acceptee["pn"]]}
    assert lu.set_index("PN").loc[a_valider[0]["pn"], "Commentaire"] == 'vu sur pièce ; marquage "inox"\nà revoir'
    # le fichier, déposé comme le fait la personne (avec l'indicateur d'ordre des octets), est relu au passage suivant
    cible = cfg.projet / "Acquisition" / "validations_composition_revue.csv"
    cible.write_bytes(("﻿" + s["csv"]).encode("utf-8"))
    try:
        assert cible in C.fichiers_validations(cfg.projet) and len(C.fichiers_validations(cfg.projet)) == 2
        t2 = C.executer(ctx)
        r2 = t2["Composition proposée"].set_index("PN")
        assert r2.loc[a_valider[0]["pn"], "Statut"] == "validée" and r2.loc[a_valider[0]["pn"], "Classe retenue"] == a_valider[0]["classe"]
        assert r2.loc[acceptee["pn"], "Statut"] == "validée" and r2.loc[acceptee["pn"], "Classe retenue"] == autre   # la correction fait foi
        assert t2["Notes"]["validations_importees"] == 2
        with K.Cortex(cfg.cortex) as cx:
            v = cx._table("SELECT validateur, commentaire, motif FROM validation WHERE sujet=? ORDER BY id DESC LIMIT 1", (a_valider[0]["pn"],))
            assert cx.motifs(C.DOMAINE, C.ATTRIBUT)[acceptee["pn"]] == motifs[acceptee["pn"]]
        assert v["validateur"][0] == "Camille ; Atelier" and "inox" in v["commentaire"][0] and v["motif"][0] == "file"
        # une décision déjà importée n'est plus proposée à l'export ; une décision sur une pièce absente est écartée
        d2 = donnees_de(cfg.artefacts / "composition" / P.NOM_PAGE)
        s2 = logique({"pieces": d2["pieces"], "decisions": {}, "validateur": "", "a_nettoyer": dict(decisions, **{"ABSENTE": {"classe": autre}})})
        assert s2["nettoyees"] == {}
        assert C.executer(ctx)["Notes"]["validations_importees"] == 0      # relire le même fichier n'ajoute rien
    finally:
        cible.unlink()


@pytest.mark.skipif(NODE is None, reason="node n'est pas installé")
def test_csv_vide_et_sans_nom():
    s = logique({"pieces": [], "decisions": {"A": {"classe": ""}, "B": {"classe": "Métal"}}, "validateur": ""})
    assert s["csv"] == "PN;Classe validée;Validateur;Commentaire;Motif\r\nB;Métal;non précisé;;choix\r\n"
