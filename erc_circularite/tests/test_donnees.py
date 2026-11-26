"""Couche de données et pipeline : premier lancement sur données réelles, défauts des fichiers, classeur de paramètres,
dépôt des artefacts, répétabilité. Les « données réelles » sont ici une copie des sources fictives de la démonstration."""
import json
import math
import shutil

import numpy as np
import pandas as pd
import pytest

import erc
from erc import parametres as P
from erc.config import NOM_PROJET
from conftest import lancer


# ------------------------------------------------------------------ cellules du classeur
@pytest.mark.parametrize("cellule, attendu", [
    (45, 45.0), ("45", 45.0), ("0,35", 0.35), (" 1 234,5 ", 1234.5), ("30|70", (30.0, 70.0)), ("70|30", (30.0, 70.0)),
    ("30|45|70", (30.0, 45.0, 70.0)), ("0,2 | 0,5", (0.2, 0.5)), ("30|30", 30.0), (None, None), ("", None), (float("nan"), None),
    ("abc", None), ("30|", None), ("1|2|3|4", None),
])
def test_plage(cellule, attendu):
    assert P.plage(cellule) == attendu


def test_plage_mode_hors_bornes_ramene():
    bas, mode, haut = P.plage("30|90|70")
    assert bas == 30 and haut == 90 or (bas <= mode <= haut)


def test_produit_et_bornes():
    assert P.produit(2, 3) == 6
    assert P.produit((1, 2, 3), 2) == (2, 4, 6)
    assert P.produit(None, 2) is None and P.produit(float("nan"), 2) is None
    assert P.bornes((1, 3)) == (1.0, 2.0, 3.0) and P.bornes(None) is None


# ------------------------------------------------------------------ premier lancement sur données réelles
def test_premier_lancement_gabarit_vierge(reel):
    dossier, projet, racine = reel
    ctx = lancer(dossier, projet, racine)
    assert not ctx.cfg.demo and ctx.cfg.classeur.is_file()
    x = pd.read_excel(ctx.cfg.classeur, sheet_name=None)
    assert {"Lisez_moi", "Ligne", "FRU", "Pieces", "Supply", "Ateliers"} <= set(x)
    # gabarit vierge : aucune valeur de démonstration ne s'y glisse en mode réel
    assert x["Ligne"].loc[x["Ligne"]["Paramètre"].ne("amortissement_ans"), "Valeur"].isna().all()
    assert x["FRU"]["ouverture_min"].isna().all() and x["Pieces"]["extraction_min"].isna().all()
    assert len(x["FRU"]) > 0 and "CARCASSE" in set(x["Pieces"]["Pièce"])
    # rien n'est calculé à partir d'inconnues
    plan = ctx.res["ligne"]["Plan optimal"]
    assert len(plan) and plan["Décision"].eq("incomplet").all()
    r = ctx.res["ligne"]["Notes"]["resume"]
    assert math.isnan(r["Résultat / an (€)"]) and math.isnan(r["Marge variable / an (€)"])
    assert len(ctx.res["ligne"]["Données à obtenir"]) > 0
    decision = ctx.res["synthese"]["Tableau de décision"].set_index("Indicateur")["Valeur"]
    assert decision["Gain annuel par rapport à la situation actuelle"] == "inconnu"
    assert not ctx.anomalies, ctx.anomalies
    # tout est écrit dans le dossier de travail, rien dans les sources hors du cache documenté
    assert (dossier / "artefacts" / "manifeste.json").is_file()


def test_classeur_jamais_reecrit(reel):
    dossier, projet, racine = reel
    ctx = lancer(dossier, projet, racine, jusqua="classement")
    avant = ctx.cfg.classeur.read_bytes()
    lancer(dossier, projet, racine, jusqua="ligne")
    assert ctx.cfg.classeur.read_bytes() == avant


def _remplir(classeur):
    """Remplit le gabarit comme le ferait un utilisateur : nombres, plages, virgule décimale, une cellule illisible."""
    x = pd.read_excel(classeur, sheet_name=None, dtype=object)
    lg = x["Ligne"].set_index("Paramètre")
    for k, v in {"cout_installation_eur": "20000|40000", "couts_fixes_annuels_eur": 5000, "heures_operateur_an": 600, "taux_horaire_eur": "40",
                 "cout_traitement_eur_kg": "0,2", "valeur_reemploi_frac": "0,3|0,5|0,7"}.items():
        lg.at[k, "Valeur"] = v
    x["Ligne"] = lg.reset_index()
    x["FRU"]["ouverture_min"] = "20|30|45"
    x["FRU"].loc[x["FRU"].index[0], "ouverture_min"] = "trente minutes"            # illisible : doit rester inconnu
    pc = x["Pieces"]
    vraies = pc["Pièce"].ne("CARCASSE")
    pc.loc[vraies, ["extraction_min", "test_min", "tri_min"]] = [5, 8, 1]
    pc.loc[vraies, "p_reutilisable"] = "0,4|0,6"
    pc.loc[~vraies, ["prix_recycleur_eur_kg", "tri_min"]] = [0.2, 8]
    P.ecrire_classeur(classeur, x)


def test_classeur_rempli_donne_un_resultat(reel):
    dossier, projet, racine = reel
    ctx = lancer(dossier, projet, racine, jusqua="classement")
    _remplir(ctx.cfg.classeur)
    ctx = lancer(dossier, projet, racine)
    plan = ctx.res["ligne"]["Plan optimal"]
    assert plan["Décision"].eq("traiter").any()
    premier = pd.read_excel(ctx.cfg.classeur, sheet_name="FRU")["FRU"].iloc[0]
    # la cellule illisible n'a pas été devinée : aucun réemploi possible pour ce FRU, faute d'ouverture soignée
    opts = ctx.res["ligne"]["Options par pièce"]
    assert opts.loc[opts["Type de FRU"].eq(premier), "1 Réemploi (€/FRU)"].isna().all()
    prov = ctx.res["ligne"]["Paramètres effectifs"]
    manquants = prov[prov["État"].eq("manquant")]
    assert manquants["Valeur"].fillna("").eq("").all()                              # « manquant » ne porte jamais de nombre
    r = ctx.res["ligne"]["Notes"]["resume"]
    assert r["Heures utilisées / an"] <= r["Capacité (h/an)"] + 1e-6
    assert r["FRU traitées / an"] <= plan.drop_duplicates("Type de FRU")["FRU scrapées / an"].sum() + 1e-6
    assert r["Masse détournée de la benne (kg/an)"] <= r["Masse des FRU scrapées (kg/an)"] + 1e-6
    # données de l'outil : JSON strict, sans NaN
    d = json.loads(json.dumps(ctx.res["synthese"]["Données de l'outil"], allow_nan=False))
    assert d["meta"]["donnees"] == "réelles" and len(d["frus"]) == plan["Type de FRU"].nunique()
    assert not ctx.anomalies, ctx.anomalies


# ------------------------------------------------------------------ fichiers manquants ou abîmés
FICHIERS = ["FRU_info.xlsx", "ERC_Valorisation_MICV_v1.xlsx", f"{NOM_PROJET}/Classification_matieres/ERC_Classification_Cartes_resultats.xlsx",
            f"{NOM_PROJET}/Classification_matieres/ERC_Referentiel_Grades.xlsx", f"{NOM_PROJET}/Extraction_R26/poids_items_vwAllItems.csv",
            f"{NOM_PROJET}/Extraction_R26/fiabilite_ELF_references_ERC.csv", f"{NOM_PROJET}/Extraction_R26/poses_2022_2023_par_reference.csv",
            f"{NOM_PROJET}/Acquisition/pesees_hebdo.csv", f"{NOM_PROJET}/Acquisition/audit_demontage.csv"]


@pytest.mark.parametrize("fichier", FICHIERS)
def test_source_absente_ne_bloque_pas(reel, fichier):
    dossier, projet, racine = reel
    (racine / fichier).unlink()
    ctx = lancer(dossier, projet, racine)
    etat = ctx.res["sources"]["État des sources"]
    assert etat["État"].eq("absent").any()
    assert not ctx.anomalies, ctx.anomalies
    assert not etat["Fichier"].astype(str).str.contains(str(racine), regex=False).any()      # aucun chemin du poste dans les artefacts


def test_fichier_illisible_est_signale(reel):
    dossier, projet, racine = reel
    (racine / "FRU_info.xlsx").write_bytes(b"ceci n'est pas un classeur")
    (projet / "Acquisition" / "pesees_hebdo.csv").write_bytes(b"")
    ctx = lancer(dossier, projet, racine)
    etat = ctx.res["sources"]["État des sources"].set_index("Source")["État"]
    assert etat["FRU_info"] == "erreur"
    assert len(ctx.res["flux"]["Estimé contre pesé"]) > 0                             # le reste du pipeline a tourné


def test_references_numeriques_et_colonnes_approximatives(reel):
    """Références lues comme des nombres, noms de colonnes en autre casse ou avec espaces : la lecture les tolère."""
    dossier, projet, racine = reel
    f = sorted(projet.glob("ERC_R26_extraction_*.xlsx"))[-1]
    x = pd.read_excel(f, sheet_name=None)
    ev = x["Composants_jour"]
    attendu = float(ev["Qte"].sum())
    ev = ev.rename(columns={"Component ITEM": "component item ", "Qte": "QTE"})
    x["Composants_jour"] = ev
    with pd.ExcelWriter(f, engine="openpyxl") as w:
        for nom, d in x.items():
            d.to_excel(w, sheet_name=nom, index=False)
    for g in projet.glob("ERC_R26_extraction_*.xlsx"):
        if g != f:
            g.unlink()
    ctx = lancer(dossier, projet, racine, jusqua="classement")
    assert math.isclose(float(ctx.src.ev["Qte"].sum()), attendu)


def test_extractions_qui_se_chevauchent(reel):
    """Sur un jour commun, l'extraction dont la période finit le plus tard est lue, quelle que soit la date de modification."""
    dossier, projet, racine = reel
    fichiers = sorted(projet.glob("ERC_R26_extraction_*.xlsx"))
    assert len(fichiers) == 2
    ancien, recent = fichiers
    x = pd.read_excel(ancien, sheet_name=None)
    x["Composants_jour"]["Qte"] = x["Composants_jour"]["Qte"] * 1000                  # l'ancien fichier ment sur les jours communs
    with pd.ExcelWriter(ancien, engine="openpyxl") as w:
        for nom, d in x.items():
            d.to_excel(w, sheet_name=nom, index=False)                                # réécrit après : c'est lui le plus récemment modifié
    ctx = lancer(dossier, projet, racine, jusqua="sources")
    ev = ctx.src.ev
    debut_recent = pd.Timestamp(recent.stem.split("_")[-2])
    assert ev.loc[ev["Jour"] >= debut_recent, "Qte"].max() < 1000
    assert ev.loc[ev["Jour"] < debut_recent, "Qte"].max() >= 1000


def test_audit_incoherent_ecarte(reel):
    dossier, projet, racine = reel
    f = projet / "Acquisition" / "audit_demontage.csv"
    a = pd.read_csv(f, sep=";", encoding="utf-8-sig")
    n = len(a)
    a.loc[0, "Pièces bonnes"] = a.loc[0, "Pièces testées"] + 5                        # plus de bonnes que de testées
    a.loc[1, "Pièces testées"] = -3
    a.to_csv(f, sep=";", index=False, encoding="utf-8-sig")
    ctx = lancer(dossier, projet, racine, jusqua="sources")
    assert len(ctx.src.audit) == n - 2
    assert (ctx.src.audit["Pièces bonnes"] <= ctx.src.audit["Pièces testées"]).all()


# ------------------------------------------------------------------ dépôt des artefacts et répétabilité
def test_manifeste_fidele_et_execution_repetable(reel):
    dossier, projet, racine = reel
    ctx = lancer(dossier, projet, racine, jusqua="classement")
    _remplir(ctx.cfg.classeur)
    ctx1 = lancer(dossier, projet, racine)
    m = json.loads((ctx1.cfg.artefacts / "manifeste.json").read_text(encoding="utf-8"))
    assert m["donnees"] == "réelles" and len(m["artefacts"]) > 30
    for e in m["artefacts"]:
        assert (ctx1.cfg.artefacts / e["fichier"]).is_file(), e["fichier"]
        assert all(ord(c) < 128 for c in e["fichier"]), e["fichier"]                  # noms de fichiers sans accent
    tables1 = {(e, n): t.copy() for e, r in ctx1.res.items() for n, t in r.items() if isinstance(t, pd.DataFrame)}
    ctx2 = lancer(dossier, projet, racine)
    for (e, n), t1 in tables1.items():
        t2 = ctx2.res[e][n]
        assert list(t1.columns) == list(t2.columns) and len(t1) == len(t2), (e, n)
        for c in t1.columns:
            if pd.api.types.is_numeric_dtype(t1[c]):
                assert np.allclose(t1[c].astype(float), t2[c].astype(float), equal_nan=True, rtol=1e-9, atol=1e-9), (e, n, c)
    # une table relue du disque redonne ce qui a été écrit, y compris des références qui ressemblent à des nombres
    t = ctx2.depot.lire_table("classement", "FRU scrapées")
    assert len(t) == len(ctx2.res["classement"]["FRU scrapées"])


def test_mode_demonstration_isole(tmp_path):
    cfg = erc.charger_config(dossier=tmp_path, demo=True)
    assert cfg.demo and cfg.dossier == tmp_path / "demo"
    assert not (tmp_path / "artefacts").exists()                                      # la démonstration n'écrit jamais dans les artefacts réels


def test_memoriser_chemins(reel, monkeypatch):
    dossier, projet, racine = reel
    for v in ("ERC_PROJET", "ERC_RACINE", "ERC_DEMO", "ERC_DOSSIER"):
        monkeypatch.delenv(v, raising=False)
    erc.memoriser_chemins(projet=projet, racine=racine, dossier=dossier, n_top=12)
    cfg = erc.charger_config(dossier=dossier)
    assert not cfg.demo and cfg.projet == projet and cfg.racine == racine and cfg.n_top == 12


# ------------------------------------------------------------------ vocabulaire : « scrapé » remplace « rebuté »
def test_ancien_onglet_et_anciennes_colonnes_toujours_lus(reel):
    """Les extractions produites avant le changement de vocabulaire gardent l'onglet FRU_rebutees ; un classeur déjà
    rempli garde la colonne rebut_an. Les deux sont encore lus."""
    dossier, projet, racine = reel
    attendu = None
    for f in projet.glob("ERC_R26_extraction_*.xlsx"):
        x = pd.read_excel(f, sheet_name=None)
        assert "FRU_scrapees" in x
        x["FRU_rebutees"] = x.pop("FRU_scrapees")
        with pd.ExcelWriter(f, engine="openpyxl") as w:
            for nom, d in x.items():
                d.to_excel(w, sheet_name=nom, index=False)
    ctx = lancer(dossier, projet, racine, jusqua="classement")
    assert len(ctx.src.fru_scrapees) > 0
    x = pd.read_excel(ctx.cfg.classeur, sheet_name=None, dtype=object)
    premier = x["FRU"]["FRU"].iloc[0]
    x["FRU"] = x["FRU"].rename(columns={"scrap_an": "rebut_an"})
    x["FRU"].loc[x["FRU"].index[0], "rebut_an"] = 123
    P.ecrire_classeur(ctx.cfg.classeur, x)
    p = P.lire(ctx.cfg)
    assert p.fru.set_index("FRU").at[premier, "scrap_an"] == 123.0
