"""Outil des décideurs : le modèle JavaScript doit redonner les résultats de Python, et le fichier produit doit être autonome.

    pytest tests/test_outil.py

1. Parité : le jeu de démonstration et des scénarios tirés au hasard (graine fixe) sont calculés par erc/ligne.py puis
   par erc/outil_modele.js (via node tests/outil_parite.mjs) ; indicateurs, plan et comparaison doivent coïncider.
   Les tests de parité sont sautés si node n'est pas installé.
2. Fichier : aucune ressource extérieure, données retrouvées à l'identique, taille raisonnable, variante « fragment ».
"""
from __future__ import annotations

import copy
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

import erc  # noqa: E402
from erc import etapes as mod_etapes  # noqa: E402
from erc import ligne as mod_ligne  # noqa: E402
from erc import outil as mod_outil  # noqa: E402

SCRIPT = RACINE / "tests" / "outil_parite.mjs"
NODE = shutil.which("node")
N_SCENARIOS = 60
TOL_REL, TOL_ABS = 1e-6, 1e-6
CLES_LIGNE = ["heures_operateur_an", "taux_horaire_eur", "cout_traitement_eur_kg", "cout_installation_eur",
              "amortissement_ans", "couts_fixes_annuels_eur"]
CHAMPS_PIECE = ["n_par_fru", "extraction_min", "test_min", "tri_min", "p_reutilisable", "valeur_eur", "delai_semaines",
                "valeur_semaine_eur", "transport_eur", "poids_kg", "prix_recycleur_eur_kg"]


# --------------------------------------------------------------------------- jeu de démonstration (une fois par session)
@pytest.fixture(scope="session")
def ctx(tmp_path_factory):
    dossier = tmp_path_factory.mktemp("dossier_outil")
    return erc.executer(jusqua="ligne", cfg=erc.charger_config(dossier=str(dossier), demo=True), silencieux=True)


@pytest.fixture(scope="session")
def donnees(ctx):
    return mod_etapes.donnees_outil(ctx)


@pytest.fixture(scope="session")
def base(ctx):
    """Paramètres du modèle au centre des plages : (ligne, frus) comme les lit erc.ligne.optimiser_ligne."""
    modele = ctx.res["ligne"]["Modèle"]
    return mod_ligne._milieu(modele["ligne"]), mod_ligne._milieu(modele["frus"])


# --------------------------------------------------------------------------- scénarios
def en_listes(frus: dict) -> list:
    """{fru: {..., pieces: {pièce: {...}}}} → listes ordonnées, pour JSON (l'ordre des FRU et des pièces compte)."""
    out = []
    for f, d in frus.items():
        item = {"fru": f, **{k: v for k, v in d.items() if k != "pieces"}}
        item["pieces"] = [{"piece": p, **e} for p, e in d.get("pieces", {}).items()]
        out.append(item)
    return out


def _heures_libres(lg: dict, fr: dict) -> float:
    r = mod_ligne.optimiser_ligne(dict(lg, heures_operateur_an=None), fr)["resume"]["Heures utilisées / an"]
    return float(r) if r is not None and np.isfinite(r) else 0.0


def scenario_aleatoire(lg0: dict, fr0: dict, rng: np.random.Generator, i: int) -> tuple[dict, dict]:
    """Un scénario : prix, temps et probabilités perturbés, paramètres rendus inconnus, capacité saturée ou non."""
    lg, fr = copy.deepcopy(lg0), copy.deepcopy(fr0)
    lg = {k: lg.get(k) for k in CLES_LIGNE}
    lg["taux_horaire_eur"] = None if rng.random() < 0.05 else float(lg0.get("taux_horaire_eur") or 40.0) * rng.uniform(0.5, 2.0)
    lg["cout_traitement_eur_kg"] = [0.0, -0.12, 0.25, 0.8, None, float(rng.uniform(-0.3, 1.0))][int(rng.integers(0, 6))]
    lg["cout_installation_eur"] = None if rng.random() < 0.08 else float(rng.uniform(0, 80000))
    lg["couts_fixes_annuels_eur"] = None if rng.random() < 0.08 else float(rng.uniform(0, 20000))
    lg["amortissement_ans"] = [5.0, 1.0, 0.0, 0.5, None, 8.0][int(rng.integers(0, 6))]
    pool = [(p, e) for d in fr0.values() for p, e in d.get("pieces", {}).items() if "extraction_min" in e]
    for f, d in list(fr.items()):
        u = rng.random()
        d["scrap_an"] = None if u < 0.05 else 0.0 if u < 0.15 else float((d.get("scrap_an") or 60.0) * rng.uniform(0.2, 3.0))
        if rng.random() < 0.06:
            d["poids_fru_kg"] = None
        d["ouverture_min"] = None if rng.random() < 0.06 else float((d.get("ouverture_min") or 20.0) * rng.uniform(0.3, 2.0))
        u = rng.random()
        if u < 0.25:
            d.pop("ouverture_tri_min", None)                    # clé absente : retombe sur l'ouverture soignée
        elif u < 0.30:
            d["ouverture_tri_min"] = None                       # clé présente mais inconnue : recyclage non calculable
        else:
            d["ouverture_tri_min"] = float(rng.uniform(0, 20))
        u = rng.random()
        if u < 0.2:
            d["taux_horaire_eur"] = float(rng.uniform(25, 90))  # taux propre au FRU
        elif u < 0.23:
            d["taux_horaire_eur"] = None                        # présent et inconnu : type incomplet
        for p, e in d.get("pieces", {}).items():
            for k in list(e):
                if k == "description":
                    continue
                if rng.random() < 0.06:
                    e[k] = None
                elif e[k] is not None:
                    e[k] = float(e[k]) * rng.uniform(0.3, 2.5)
                elif k in ("transport_eur", "delai_semaines", "valeur_semaine_eur") and rng.random() < 0.4:
                    e[k] = float(rng.uniform(0, 12))
            if e.get("p_reutilisable") is not None:
                e["p_reutilisable"] = float(np.clip(e["p_reutilisable"], 0, 1))
            if e.get("n_par_fru") is not None:
                e["n_par_fru"] = float(max(1, round(e["n_par_fru"])))
    if i % 3 == 0 and pool:                                     # un type de FRU de plus de 8 pièces
        n = int(rng.integers(9, 12))
        pieces = {}
        for j in range(n):
            p, e = pool[int(rng.integers(0, len(pool)))]
            e = {k: (None if v is None or (k != "description" and rng.random() < 0.05) else v if k == "description" else float(v) * rng.uniform(0.4, 2.0))
                 for k, v in e.items()}
            if e.get("p_reutilisable") is not None:
                e["p_reutilisable"] = float(np.clip(e["p_reutilisable"], 0, 1))
            if e.get("n_par_fru") is not None:
                e["n_par_fru"] = float(max(1, round(e["n_par_fru"])))
            pieces[f"X-{j:02d}"] = e
        fr["FRU-GROS-R"] = {"description": "FRU fictif de plus de 8 pièces", "scrap_an": float(rng.uniform(20, 200)), "poids_fru_kg": 30.0,
                            "ouverture_min": float(rng.uniform(10, 50)), "ouverture_tri_min": float(rng.uniform(3, 15)), "pieces": pieces}
    if i % 11 == 5:
        fr["FRU-VIDE-R"] = {"description": "FRU fictif sans pièce", "scrap_an": 12.0, "poids_fru_kg": 4.0, "ouverture_min": 10.0, "pieces": {}}
    libres = _heures_libres(lg, fr)
    facteur = [None, 0.0, 0.05, 0.2, 0.4, 0.6, 0.8, 0.95, 1.0, 1.3, 2.5][i % 11]
    lg["heures_operateur_an"] = None if facteur is None else float(libres * facteur) if libres > 0 else float(rng.uniform(0, 500))
    return lg, fr


def scenarios(base) -> list:
    lg0, fr0 = base
    rng = np.random.default_rng(20260614)
    cas = [("base", copy.deepcopy(lg0), copy.deepcopy(fr0))]
    cas.append(("aucun FRU", copy.deepcopy(lg0), {}))
    cas.append(("ligne entièrement inconnue", {k: None for k in CLES_LIGNE}, copy.deepcopy(fr0)))
    sans_temps = copy.deepcopy(fr0)
    for d in sans_temps.values():
        d["ouverture_min"] = None
        d.pop("ouverture_tri_min", None)
        for e in d["pieces"].values():
            for k in ("extraction_min", "test_min", "tri_min"):
                if k in e:
                    e[k] = None
    cas.append(("aucun temps connu", copy.deepcopy(lg0), sans_temps))
    cas.append(("capacité nulle", dict(copy.deepcopy(lg0), heures_operateur_an=0.0), copy.deepcopy(fr0)))
    cas.append(("capacité illimitée", dict(copy.deepcopy(lg0), heures_operateur_an=None), copy.deepcopy(fr0)))
    cas.append(("recycleur actuel qui paie", dict(copy.deepcopy(lg0), cout_traitement_eur_kg=-0.4), copy.deepcopy(fr0)))
    zero = copy.deepcopy(fr0)                                   # ex æquo entre plans : une pièce présente en zéro exemplaire
    next(iter(next(iter(zero.values()))["pieces"].values()))["n_par_fru"] = 0.0
    cas.append(("pièce en zéro exemplaire", copy.deepcopy(lg0), zero))
    gratuit = copy.deepcopy(fr0)                                # tri sans temps : des plans à zéro heure restent choisis sans capacité
    for d in gratuit.values():
        d["ouverture_tri_min"] = 0.0
        for e in d["pieces"].values():
            if e.get("tri_min") is not None:
                e["tri_min"] = 0.0
    cas.append(("tri sans temps, capacité nulle", dict(copy.deepcopy(lg0), heures_operateur_an=0.0), gratuit))
    for i in range(N_SCENARIOS):
        lg, fr = scenario_aleatoire(lg0, fr0, rng, i)
        cas.append((f"aléatoire {i:02d}", lg, fr))
    return cas


# --------------------------------------------------------------------------- comparaison
def _nan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA


def meme_nombre(py, js, quoi: str):
    if _nan(py):
        assert js is None, f"{quoi} : Python inconnu, JavaScript {js!r}"
        return
    py = float(py)
    if math.isinf(py):
        assert js == ("inf" if py > 0 else "-inf"), f"{quoi} : Python {py}, JavaScript {js!r}"
        return
    assert isinstance(js, (int, float)) and not isinstance(js, bool), f"{quoi} : Python {py}, JavaScript {js!r}"
    assert math.isclose(py, float(js), rel_tol=TOL_REL, abs_tol=TOL_ABS), f"{quoi} : Python {py!r}, JavaScript {js!r}"


def _ensemble(texte) -> set:
    return set() if _nan(texte) or not str(texte).strip() else {x.strip() for x in str(texte).split(",")}


def comparer_plan(detail: pd.DataFrame, plan: list, nom: str):
    lignes = detail.to_dict("records") if len(detail) else []
    assert len(lignes) == len(plan), f"{nom} : {len(lignes)} lignes de plan en Python, {len(plan)} en JavaScript"
    for k, (py, js) in enumerate(zip(lignes, plan)):
        ou = f"{nom}, plan ligne {k} ({py['Type de FRU']})"
        assert py["Type de FRU"] == js["Type de FRU"], ou
        assert py["Décision"] == js["Décision"], f"{ou} : décision {py['Décision']!r} / {js['Décision']!r}"
        assert (py.get("Entrées manquantes") or "") == (js.get("Entrées manquantes") or ""), f"{ou} : entrées manquantes"
        if py["Décision"] == "incomplet":
            continue
        assert _ensemble(py["1 Réemploi"]) == _ensemble(js["1 Réemploi"]), f"{ou} : réemploi {py['1 Réemploi']!r} / {js['1 Réemploi']!r}"
        assert _ensemble(py["2 Recyclage"]) == _ensemble(js["2 Recyclage"]), f"{ou} : recyclage {py['2 Recyclage']!r} / {js['2 Recyclage']!r}"
        for c in ("FRU traitées / an", "FRU scrapées / an", "Heures par FRU", "Marge par FRU (€)", "Marge par heure (€)", "Heures / an",
                  "Marge variable / an (€)", "Kg détournés / an"):
            meme_nombre(py[c], js[c], f"{ou}, {c}")


def comparer_scenarios(t: pd.DataFrame, js: dict, nom: str):
    assert len(t) == len(js["lignes"]) == 4
    for py, l in zip(t.to_dict("records"), js["lignes"]):
        assert py["Poste (€/an)"] == l["Poste (€/an)"]
        for c in ("Actuel", "Avec la ligne", "Écart"):
            meme_nombre(py[c], l[c], f"{nom}, actuel contre ligne, {py['Poste (€/an)']}, {c}")
    for k, v in t.attrs.items():
        meme_nombre(v, js["attrs"][k], f"{nom}, actuel contre ligne, {k}")


def comparer_options(lg: dict, fr: dict, js: list, nom: str) -> int:
    """Valeur des trois options par pièce. Renvoie le nombre de FRU comparés (ligne.py échoue si le taux horaire est inconnu)."""
    n = 0
    for (f, d), o in zip(fr.items(), js):
        assert o["fru"] == f
        try:
            t = mod_ligne.valeurs_options(dict(d, _c_trait=lg.get("cout_traitement_eur_kg")), lg.get("taux_horaire_eur"))
        except TypeError:
            continue
        n += 1
        assert len(t) == len(o["lignes"])
        for cle, js in (("Ouverture soignée (€/FRU)", o["ouverture_soignee"]), ("Ouverture sommaire (€/FRU)", o["ouverture_sommaire"])):
            py = t.attrs.get(cle)
            if not _nan(py):                                    # ligne.py rend NaN pour une ouverture de 0 minute ; l'outil rend 0 €
                meme_nombre(py, js, f"{nom}, {f}, {cle}")
        for py, l in zip(t.to_dict("records"), o["lignes"]):
            ou = f"{nom}, options {f} / {py['Pièce']}"
            assert py["Pièce"] == l["Pièce"]
            for c in ("1 Réemploi (€/FRU)", "2 Recyclage (€/FRU)", "3 Jeté (€/FRU)", "Heures réemploi", "Heures recyclage",
                      "Kg détournés réemploi", "Kg détournés recyclage"):
                meme_nombre(py[c], l[c], f"{ou}, {c}")
            for c in ("Manque réemploi", "Manque recyclage", "Meilleure option seule"):
                assert py[c] == l[c], f"{ou}, {c} : {py[c]!r} / {l[c]!r}"
    return n


# --------------------------------------------------------------------------- exécution de node
def lancer_node(cas: list, dossier: Path) -> dict:
    fichier = dossier / "cas.json"
    fichier.write_text(json.dumps({"cas": cas}, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    r = subprocess.run([NODE, str(SCRIPT), str(fichier)], capture_output=True, text=True, encoding="utf-8", timeout=600)
    assert r.returncode == 0, f"node a échoué :\n{r.stderr[-2000:]}"
    return json.loads(r.stdout)


@pytest.fixture(scope="session")
def parite(base, ctx, donnees, tmp_path_factory):
    """Tous les cas calculés des deux côtés : [(nom, ligne, frus, résultat Python, résultat JavaScript)]."""
    if NODE is None:
        pytest.skip("node n'est pas installé : parité JavaScript / Python non vérifiée")
    liste = scenarios(base)
    cas = [{"nom": nom, "ligne": lg, "frus": en_listes(fr)} for nom, lg, fr in liste]
    flux = ctx.res["flux"]["FRU scrapées par semaine"]
    cas[0]["flux"] = [{"Semaine": pd.Timestamp(r["Semaine"]).isoformat(), "FRU": r["FRU"], "FRU scrapées": float(r["FRU scrapées"])}
                      for r in flux.to_dict("records")]
    cas.append({"nom": "données de l'outil", "donnees": donnees, "monte_carlo": {"n": 400, "graine": 2026}})
    sortie = lancer_node(cas, tmp_path_factory.mktemp("parite"))
    return liste, sortie


# --------------------------------------------------------------------------- 1. parité
def test_scenarios_assez_varies(base):
    """Le générateur produit bien les situations demandées : capacité saturée ou non, options et types incomplets, gros FRU."""
    liste = scenarios(base)
    assert len(liste) >= 41
    satures = libres = incomplets = illimites = gros = zeros = negatifs = 0
    for nom, lg, fr in liste:
        r = mod_ligne.optimiser_ligne(lg, fr)
        res, d = r["resume"], r["detail"]
        mu = res["Valeur d'une heure opérateur en plus (€ net)"]
        satures += bool(mu is not None and np.isfinite(mu) and mu > 0)
        libres += bool(mu == 0)
        illimites += lg.get("heures_operateur_an") is None
        incomplets += bool(res["Types de FRU incomplets"])
        gros += any(len(x.get("pieces", {})) > mod_ligne.MAX_PIECES_ENUM for x in fr.values())
        zeros += any(x.get("scrap_an") == 0 for x in fr.values())
        negatifs += bool((lg.get("cout_traitement_eur_kg") or 0) < 0)
        assert d is not None
    assert satures >= 10 and libres >= 10 and illimites >= 3 and incomplets >= 10 and gros >= 10 and zeros >= 5 and negatifs >= 3, \
        (satures, libres, illimites, incomplets, gros, zeros, negatifs)


def test_parite_resume_et_plan(parite):
    liste, sortie = parite
    for (nom, lg, fr), js in zip(liste, sortie["resultats"]):
        assert js["nom"] == nom
        py = mod_ligne.optimiser_ligne(lg, fr)
        assert set(py["resume"]) == set(js["resume"]), nom
        for k, v in py["resume"].items():
            meme_nombre(v, js["resume"][k], f"{nom}, {k}")
        comparer_plan(py["detail"], js["plan"], nom)


def test_parite_actuel_contre_ligne(parite):
    liste, sortie = parite
    for (nom, lg, fr), js in zip(liste, sortie["resultats"]):
        comparer_scenarios(mod_ligne.comparer_scenarios(lg, fr), js["scenarios"], nom)


def test_parite_options_par_piece(parite):
    liste, sortie = parite
    compares = sum(comparer_options(lg, fr, js["options"], nom) for (nom, lg, fr), js in zip(liste, sortie["resultats"]))
    assert compares >= 100


def test_parite_periode_par_periode(parite, ctx):
    liste, sortie = parite
    modele = ctx.res["ligne"]["Modèle"]
    py = mod_ligne.resultat_par_periode(modele["ligne"], modele["frus"], ctx.res["flux"]["FRU scrapées par semaine"])
    js = sortie["resultats"][0]["periodes"]
    assert len(py) == len(js["lignes"]) > 0
    for a, b in zip(py.to_dict("records"), js["lignes"]):
        assert pd.Timestamp(a["Semaine"]) == pd.Timestamp(b["Semaine"])
        for c in ("FRU arrivées", "FRU traitées", "Heures utilisées", "Capacité (h)", "Marge variable (€)", "Coût fixe (€)", "Résultat (€)",
                  "Valeur d'une heure en plus (€)", "Résultat cumulé (€)"):
            meme_nombre(a[c], b[c], f"semaine {a['Semaine']}, {c}")
    for k, v in py.attrs.items():
        meme_nombre(v, js["attrs"][k], f"période par période, {k}")


def test_conversion_des_donnees_de_l_outil(parite, base, donnees):
    """versModele (JavaScript) retrouve les valeurs centrales lues par Python, et les mêmes résultats que la référence embarquée."""
    _, sortie = parite
    lg, fr = base
    js = sortie["resultats"][-1]
    assert js["nom"] == "données de l'outil"
    for k in CLES_LIGNE:
        meme_nombre(lg.get(k), js["modele"]["ligne"][k], f"ligne.{k}")
    assert [d["fru"] for d in js["modele"]["frus"]] == list(fr)
    for d in js["modele"]["frus"]:
        py = fr[d["fru"]]
        for k in ("scrap_an", "poids_fru_kg", "ouverture_min"):
            meme_nombre(py.get(k), d[k], f"{d['fru']}.{k}")
        for k in ("ouverture_tri_min", "taux_horaire_eur"):       # inconnus : clé absente des deux côtés
            assert (k in d) == (py.get(k) is not None), f"{d['fru']}.{k}"
            if k in d:
                meme_nombre(py[k], d[k], f"{d['fru']}.{k}")
        assert [e["piece"] for e in d["pieces"]] == list(py["pieces"])
        for e in d["pieces"]:
            for k in CHAMPS_PIECE:
                if k in e:
                    meme_nombre(py["pieces"][e["piece"]].get(k), e[k], f"{d['fru']}/{e['piece']}.{k}")
    for k, v in donnees["reference"]["resume"].items():
        meme_nombre(v, js["resume"][k], f"référence embarquée, {k}")
    for a, b in zip(donnees["reference"]["actuel_contre_ligne"], js["scenarios"]["lignes"]):
        for c in ("Actuel", "Avec la ligne", "Écart"):
            meme_nombre(a[c], b[c], f"référence embarquée, {a['Poste (€/an)']}, {c}")


def test_monte_carlo_meme_distribution(parite, donnees):
    """Les tirages JavaScript (autre générateur aléatoire) suivent la même distribution que ceux de Python."""
    _, sortie = parite
    js, py = sortie["resultats"][-1]["monte_carlo"], donnees["monte_carlo"]
    x_py = np.array([v for v in py["tirages"] if v is not None], dtype=float)
    x_js = np.array([v for v in js["tirages"] if v is not None], dtype=float)
    assert len(x_js) == 400 and len(x_py) >= 100
    erreur = 5 * 1.25 * math.sqrt(x_py.var() / len(x_py) + x_js.var() / len(x_js))    # cinq écarts-types de la médiane
    assert abs(np.median(x_py) - np.median(x_js)) <= max(erreur, 1.0), (np.median(x_py), np.median(x_js), erreur)
    assert abs(x_py.std() - x_js.std()) <= 0.35 * max(x_py.std(), 1.0)
    assert abs(float(py["p_rentable"]) - float(js["p_rentable"])) <= 0.1
    assert js["p5_mediane_p95"][0] <= js["p5_mediane_p95"][1] <= js["p5_mediane_p95"][2]
    assert set(js["frequence_traitement"]) == set(py["frequence_traitement"])
    for f, v in py["frequence_traitement"].items():
        assert abs(v - js["frequence_traitement"][f]) <= 0.15, f


def test_vitesse_d_une_optimisation(parite):
    """Une optimisation de 10 types de FRU x 8 pièces prend moins de 50 ms (moyenne, capacité saturée)."""
    _, sortie = parite
    assert sortie["ms_10_fru_8_pieces"] < 50, sortie["ms_10_fru_8_pieces"]


# --------------------------------------------------------------------------- 2. fichier produit
@pytest.fixture(scope="session")
def page(donnees, tmp_path_factory):
    chemin = tmp_path_factory.mktemp("outil") / "sous" / "dossier" / "ERC_Outil_Decision.html"
    assert mod_outil.construire(donnees, chemin) == chemin and chemin.is_file()        # les dossiers parents sont créés
    return chemin.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def fragment(donnees, tmp_path_factory):
    chemin = mod_outil.construire(donnees, tmp_path_factory.mktemp("outil_fragment") / "fragment.html", fragment=True)
    return chemin.read_text(encoding="utf-8")


def _donnees_integrees(html: str):
    m = re.search(r'<script type="application/json" id="donnees">(.*?)</script>', html, flags=re.S)
    assert m, "bloc de données introuvable"
    return json.loads(m.group(1)), html[:m.start(1)] + html[m.end(1):]


def test_document_complet(page):
    assert page.startswith('<!doctype html><html lang="fr"><head><meta charset="utf-8">'
                           '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">')
    assert "<title>Outil de décision ERC</title>" in page
    assert page.rstrip().endswith("</body></html>")
    for balise in ("<html", "<head>", "</head>", "<body>", "</body>", "</html>"):
        assert page.count(balise) == 1, balise
    assert mod_outil.MARQUE_MODELE not in page and mod_outil.MARQUE_DONNEES not in page
    assert "ERCModele" in page and "optimiserLigne" in page                       # le modèle est dans la page


def test_donnees_retrouvees_a_l_identique(page, fragment, donnees):
    for html in (page, fragment):
        relu, _ = _donnees_integrees(html)
        assert relu == json.loads(json.dumps(donnees, ensure_ascii=False))


def test_aucune_ressource_exterieure(page, fragment):
    for html in (page, fragment):
        _, sans = _donnees_integrees(html)
        urls = set(re.findall(r"https?://[^\s\"'<>)]+", sans))
        assert urls <= {"http://www.w3.org/2000/svg"}, urls                         # seul l'espace de noms SVG, jamais chargé
        assert not re.search(r"<(script|img|iframe|audio|video|source|embed|object)\b[^>]*\bsrc\s*=", sans, flags=re.I)
        assert not re.search(r"<link\b", sans, flags=re.I)
        assert not re.search(r"@import|url\(\s*['\"]?(https?:|//)", sans, flags=re.I)
        for interdit in ("fetch(", "XMLHttpRequest", "importScripts(", "sendBeacon(", "WebSocket(", "EventSource("):
            assert interdit not in sans, interdit


def test_contrat_de_la_page(page):
    _, sans = _donnees_integrees(page)
    for interdit in ("alert(", "confirm(", "prompt(", ".print(", "100vh"):
        assert interdit not in sans, interdit
    assert "prefers-color-scheme: dark" in sans and ':root:not([data-theme="light"])' in sans and ':root[data-theme="dark"]' in sans
    assert "prefers-reduced-motion" in sans
    assert "env(safe-area-inset-left" in sans and "env(safe-area-inset-right" in sans
    # aucune couleur écrite en dur hors des blocs de jetons (:root) : ni dans le reste des styles, ni dans le code
    style = re.search(r"<style>(.*?)</style>", sans, flags=re.S).group(1)
    hors_jetons = re.sub(r":root[^{]*\{[^}]*\}", "", style)
    hors_jetons = re.sub(r"@media \(prefers-color-scheme: dark\)\s*\{\s*\}", "", hors_jetons)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", hors_jetons), re.findall(r"#[0-9a-fA-F]{3,8}\b|\brgba?\([^)]*\)", hors_jetons)[:5]
    code = "".join(re.findall(r"<script>(.*?)</script>", sans, flags=re.S))
    assert not re.search(r"[\"']#[0-9a-fA-F]{3,8}[\"']|\brgba?\(", code)
    ids = re.findall(r'<(?:input|select|textarea|button)\b[^>]*>', re.sub(r"<script>.*?</script>", "", sans, flags=re.S))
    assert ids and all(" id=" in b for b in ids), [b for b in ids if " id=" not in b][:3]


def test_identifiants_du_code_presents_dans_la_page(page):
    """Chaque élément que le code va chercher par son identifiant existe dans la page, une seule fois."""
    _, sans = _donnees_integrees(page)
    code = "".join(re.findall(r"<script>(.*?)</script>", sans, flags=re.S))
    statique = re.sub(r"(<script\b[^>]*>).*?(</script>)", r"\1\2", sans, flags=re.S)   # balises gardées, code retiré
    cherches = set(re.findall(r'\$\("([A-Za-z0-9_-]+)"\)', code))
    assert len(cherches) > 40
    for i in sorted(cherches):
        assert statique.count(f'id="{i}"') == 1, i
    declares = re.findall(r'\bid="([^"]+)"', statique)
    assert len(declares) == len(set(declares)), [i for i in set(declares) if declares.count(i) > 1]
    for cible in re.findall(r'href="#([^"]+)"', statique):                          # liens du sommaire : identifiants simples
        assert cible in declares, cible


def test_taille(page, fragment):
    assert len(page.encode("utf-8")) < 2_000_000
    assert len(fragment.encode("utf-8")) < 2_000_000


def test_fragment(fragment, page):
    enveloppe = re.search(r"<!doctype|</?(html|head|body)\b", fragment, flags=re.I)        # <header> reste permis
    assert enveloppe is None, enveloppe.group(0)
    assert fragment.startswith("<title>Outil de décision ERC</title>")
    assert re.match(r'<title>[^<]*</title>\s*<meta name="claude:viewport-fit-sides" content="cover">\s*<style>', fragment)
    assert 'name="viewport"' not in fragment and "charset" not in fragment.split("<style>", 1)[0]
    corps = page.split("<body>", 1)[1].split("</body>", 1)[0].strip()
    assert fragment.rstrip().endswith(corps)                                       # même contenu que le document complet


def test_donnees_pieges(tmp_path):
    """Texte qui pourrait refermer la balise <script>, valeurs non finies, types non JSON : la page reste lisible."""
    pieges = {"meta": {"donnees": "démonstration", "note": "</script><script>x()</script> <!-- fin --> é \u2028 \u2029 ]]>"},
              "ligne": {}, "frus": [], "nan": float("nan"), "inf": float("inf"), "tuple": (1, 2), "numpy": np.float64(2.5),
              "entier": np.int64(3), "chemin": Path("a") / "b"}
    html = mod_outil.construire(pieges, tmp_path / "pieges.html").read_text(encoding="utf-8")
    assert html.count("</script>") == mod_outil.GABARIT.read_text(encoding="utf-8").count("</script>")
    relu, _ = _donnees_integrees(html)
    assert relu["meta"]["note"] == pieges["meta"]["note"]
    assert relu["nan"] is None and relu["inf"] is None and relu["tuple"] == [1, 2] and relu["numpy"] == 2.5 and relu["entier"] == 3
    assert relu["chemin"] == str(Path("a") / "b")


def test_etape_synthese_produit_l_outil(ctx):
    """L'étape synthèse du pipeline appelle outil.construire et dépose la page dans artefacts/outil/."""
    tables = mod_etapes.etape_synthese(ctx)
    chemin = tables["Outil"]["chemin"]
    assert chemin and Path(chemin).is_file(), [a for a in ctx.anomalies if a["Calcul"] == "outil des décideurs"]
    assert Path(chemin).read_text(encoding="utf-8").startswith("<!doctype html>")
    assert not [a for a in ctx.anomalies if a["Calcul"] == "outil des décideurs"]
