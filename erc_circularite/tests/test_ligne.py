"""Modèle de la ligne de démontage et de tri (erc/ligne.py) : formules, optimalité, inconnues, robustesse.

    python -m pytest tests/test_ligne.py

Ce que ces tests vérifient
1. Formules : des cas calculés à la main, puis chaque plan de chaque type de FRU recalculé depuis les formules de
   docs/Modele_mathematique.md par un code indépendant de erc/ligne.py (`plans_document` ci-dessous).
2. Optimalité : sur 600 lignes tirées au hasard (graines fixes), la marge trouvée par `optimiser_ligne` est comparée
   - à un solveur exact de programmation linéaire (scipy ; test sauté si scipy n'est pas installé) ;
   - à une borne qu'aucun plan ne peut dépasser, calculée sans scipy (dualité : marge ≤ mu × heures + somme des
     meilleurs plans à ce prix de l'heure) ; la marge trouvée doit atteindre cette borne ;
   - à l'énumération de tous les sommets du programme linéaire sur de petites lignes (sans scipy).
3. Multiplicateur : « Valeur d'une heure opérateur en plus » = ce que rapporte une heure de plus, 0 si les heures
   ne manquent pas.
4. Inconnues : chaque paramètre de la ligne, d'un type de FRU et d'une pièce est mis à « inconnu », un par un ;
   aucun nombre ne doit sortir d'une entrée inconnue.
5. Robustesse : plages dégénérées, Monte-Carlo, rejeu période par période, comparaison au recycleur actuel,
   probabilités tirées de la consommation, types de FRU de plus de 8 pièces.
6. Compatibilité : le module n'importe que numpy et pandas et reste lisible par Python 3.9.

Toutes les références (FRU-T1, P-1, ...) et toutes les valeurs sont fictives.
"""
from __future__ import annotations

import ast
import copy
import functools
import itertools
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from erc import ligne as L  # noqa: E402

REL = 1e-6                                  # écart relatif toléré entre deux marges annuelles
N_BLOCS, PAR_BLOC = 12, 50                  # 600 lignes tirées au hasard
MARGE, FIXES, RESULTAT = "Marge variable / an (€)", "Coûts fixes annualisés (€)", "Résultat / an (€)"
HEURES, CAPACITE, OCCUPATION = "Heures utilisées / an", "Capacité (h/an)", "Taux d'occupation"
TRAITEES, MOYENNE, SEUIL = "FRU traitées / an", "Marge moyenne par FRU (€)", "Seuil de rentabilité (FRU / an)"
RETOUR, MU, INCOMPLETS = "Retour sur investissement (ans)", "Valeur d'une heure opérateur en plus (€ net)", "Types de FRU incomplets"
MASSE, DETOURNEE, ACTUEL = "Masse des FRU scrapées (kg/an)", "Masse détournée de la benne (kg/an)", "Coût actuel de traitement (€/an)"
CLES_RESUME = [MARGE, FIXES, RESULTAT, HEURES, CAPACITE, OCCUPATION, TRAITEES, MOYENNE, SEUIL, RETOUR, MU, INCOMPLETS, MASSE, DETOURNEE, ACTUEL]
COLONNES_DETAIL = ["Type de FRU", "Décision", "1 Réemploi", "2 Recyclage", "FRU traitées / an", "FRU scrapées / an", "Heures par FRU",
                   "Marge par FRU (€)", "Marge par heure (€)", "Heures / an", "Marge variable / an (€)", "Kg détournés / an",
                   "Entrées manquantes", "Pièces non examinées"]
RE, RC = "1 Réemploi (€/FRU)", "2 Recyclage (€/FRU)"


# =========================================================================== outils communs
def inconnu(v) -> bool:
    return v is None or v is pd.NA or (isinstance(v, float) and math.isnan(v))


def vaut(v, rel=1e-9, abs_=1e-9):
    return pytest.approx(v, rel=rel, abs=abs_)


def pareil(a, b, rel=1e-9, abs_=1e-9) -> bool:
    """Deux valeurs d'indicateur identiques : inconnu = inconnu, infini = infini, nombres égaux à la tolérance près."""
    if inconnu(a) or inconnu(b):
        return inconnu(a) and inconnu(b)
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    if math.isinf(a) or math.isinf(b):
        return a == b
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_)


def capacite(ligne: dict) -> float:
    """Heures opérateur de la ligne : inconnues = sans limite, négatives = aucune heure."""
    h = ligne.get("heures_operateur_an")
    return math.inf if inconnu(h) else max(float(h), 0.0)


def ensemble(texte) -> frozenset:
    return frozenset() if inconnu(texte) or not str(texte) else frozenset(str(texte).split(", "))


# --------------------------------------------------------------------------- le modèle, relu dans le document
CHAMPS_REEMPLOI = ("n_par_fru", "extraction_min", "test_min", "p_reutilisable", "valeur_eur")
CHAMPS_RECYCLAGE = ("n_par_fru", "poids_kg", "prix_recycleur_eur_kg", "tri_min")


def plans_document(ligne: dict, fru: dict) -> dict:
    """Tous les plans calculables d'un type de FRU, d'après docs/Modele_mathematique.md (§5 à §7), sans erc.ligne.

    Renvoie {(pièces réemployées, pièces recyclées): (heures par FRU, marge par FRU, kg sortis de la benne par FRU)}.
    Le plan vide (FRU laissé au recycleur actuel) vaut (0, 0, 0) et existe toujours.
    Entrée inconnue : règles de l'en-tête de erc/ligne.py (option non calculable, ou entrée facultative non comptée).
    """
    vide = {(frozenset(), frozenset()): (0.0, 0.0, 0.0)}
    taux = fru.get("taux_horaire_eur", ligne.get("taux_horaire_eur"))
    c_trait = ligne.get("cout_traitement_eur_kg")
    t_ouv = fru.get("ouverture_min")
    t_ouv_tri = fru.get("ouverture_tri_min", t_ouv)
    pieces = list((fru.get("pieces") or {}).items())
    if inconnu(taux) or inconnu(c_trait):
        return vide
    plans = {}
    for s in itertools.product((3, 2, 1), repeat=len(pieces)):          # 1 réemploi, 2 recyclage trié, 3 laissée dans le FRU
        heures = valeur = kg = 0.0
        for (_, d), o in zip(pieces, s):
            n, m, prix = d.get("n_par_fru"), d.get("poids_kg"), d.get("prix_recycleur_eur_kg")
            vente = None if inconnu(m) or inconnu(prix) else m * prix   # vente au kilo d'un exemplaire
            if o == 1:
                if inconnu(t_ouv) or any(inconnu(d.get(k)) for k in CHAMPS_REEMPLOI):
                    break
                q = d["p_reutilisable"]
                delai = 0.0 if inconnu(d.get("delai_semaines")) or inconnu(d.get("valeur_semaine_eur")) else d["delai_semaines"] * d["valeur_semaine_eur"]
                transport = 0.0 if inconnu(d.get("transport_eur")) else d["transport_eur"]
                valeur += n * (q * (d["valeur_eur"] + delai) + (1 - q) * (0.0 if vente is None else vente) - transport)
                heures += n * (d["extraction_min"] + d["test_min"]) / 60
                if not inconnu(m):                                      # l'exemplaire refusé au test ne quitte la benne que s'il est vendu
                    kg += n * m * (1.0 if vente is not None else q)
            elif o == 2:
                if inconnu(t_ouv_tri) or any(inconnu(d.get(k)) for k in CHAMPS_RECYCLAGE):
                    break
                valeur += n * vente
                heures += n * d["tri_min"] / 60
                kg += n * m
        else:
            if 1 in s:
                heures += t_ouv / 60                                    # ouverture soignée, une fois par FRU
            elif 2 in s:
                heures += t_ouv_tri / 60                                # ouverture sommaire si le FRU n'est ouvert que pour trier
            cle = (frozenset(p for (p, _), o in zip(pieces, s) if o == 1), frozenset(p for (p, _), o in zip(pieces, s) if o == 2))
            plans[cle] = (heures, valeur + c_trait * kg - taux * heures, kg)
    return plans


def plans_de_la_ligne(ligne: dict, frus: dict) -> dict:
    """{type de FRU: plans} pour les types calculables ; les autres sont « incomplets » pour le modèle."""
    out = {}
    for f, d in (frus or {}).items():
        d = d or {}
        if inconnu(d.get("scrap_an")) or d["scrap_an"] < 0:
            continue
        plans = plans_document(ligne, d)
        if len(plans) > 1:
            out[f] = plans
    return out


def besoin_sans_limite(ligne: dict, frus: dict) -> float:
    """Heures que demanderait le meilleur plan de chaque type si les heures ne manquaient pas (à marge égale, le plus long)."""
    total = 0.0
    for f, plans in plans_de_la_ligne(ligne, frus).items():
        g_max = max(g for _, g, _ in plans.values())
        total += frus[f]["scrap_an"] * max(h for h, g, _ in plans.values() if g >= g_max - 1e-12)
    return total


def controler(ligne: dict, frus: dict, res: dict | None = None, tol: float = REL) -> dict:
    """Passe un résultat de `optimiser_ligne` au crible du document.

    1. Chaque ligne du plan est un plan calculable, avec les heures, la marge et les kg du document.
    2. FRU traitées ≤ FRU scrapées pour chaque type ; heures ≤ capacité.
    3. Le résumé est la somme du plan.
    4. Optimalité : pour tout prix de l'heure mu ≥ 0, aucun plan ne rapporte plus que
       mu × capacité + somme sur les types de (FRU scrapées × meilleur plan à ce prix). La marge trouvée doit valoir
       cette borne au mu annoncé : le plan est donc optimal, et mu est bien la valeur d'une heure de plus.
    Renvoie la marge, les heures et les kg recalculés.
    """
    res = L.optimiser_ligne(ligne, frus) if res is None else res
    detail, resume = res["detail"], res["resume"]
    assert list(detail.columns) == COLONNES_DETAIL
    plans = plans_de_la_ligne(ligne, frus)
    cap = capacite(ligne)
    marge = heures = kg = 0.0
    traites = dict.fromkeys(plans, 0.0)
    vus = set()
    for r in detail.to_dict("records"):
        f = r["Type de FRU"]
        vus.add(f)
        if r["Décision"] == "incomplet":
            assert f not in plans, f"{f} : déclaré incomplet alors que le document sait le calculer"
            assert r["Entrées manquantes"], f"{f} : incomplet sans dire ce qui manque"
            assert all(inconnu(r[c]) for c in COLONNES_DETAIL[2:12]), f"{f} : un type incomplet ne porte aucun nombre"
            continue
        assert f in plans, f"{f} : calculé alors qu'une entrée nécessaire est inconnue"
        cle = (ensemble(r["1 Réemploi"]), ensemble(r["2 Recyclage"]))
        assert cle in plans[f], f"{f} : le plan {sorted(cle[0])} / {sorted(cle[1])} utilise une option non calculable"
        h, g, k = plans[f][cle]
        x = r["FRU traitées / an"]
        assert x >= 0, f"{f} : nombre de FRU traitées négatif"
        assert r["FRU scrapées / an"] == frus[f]["scrap_an"]
        assert r["Décision"] == ("traiter" if (cle[0] or cle[1]) and x > 0 else "jeter telle quelle")
        assert r["Heures par FRU"] == vaut(h) and r["Marge par FRU (€)"] == vaut(g), f"{f} : heures ou marge par FRU"
        assert pareil(r["Marge par heure (€)"], g / h if h else math.nan)
        assert r["Heures / an"] == vaut(x * h) and r["Marge variable / an (€)"] == vaut(x * g) and r["Kg détournés / an"] == vaut(x * k)
        assert r["Entrées manquantes"] == ""
        marge, heures, kg = marge + x * g, heures + x * h, kg + x * k
        traites[f] += x
    assert vus == set(frus or {}), "chaque type de FRU a sa ligne dans le plan"
    for f, x in traites.items():
        assert x <= frus[f]["scrap_an"] * (1 + 1e-9) + 1e-9, f"{f} : plus de FRU traitées que de FRU scrapées"
    assert heures <= cap * (1 + 1e-9) + 1e-9, f"heures utilisées {heures} au-delà de la capacité {cap}"
    assert resume[INCOMPLETS] == len(frus or {}) - len(plans)
    assert resume[CAPACITE] == cap
    borne = math.nan
    if plans:
        echelle = max(1.0, abs(marge))
        assert resume[MARGE] == vaut(marge, abs_=1e-9 * echelle)
        assert resume[HEURES] == vaut(heures) and resume[DETOURNEE] == vaut(kg) and resume[TRAITEES] == vaut(sum(traites.values()))
        mu = resume[MU]
        assert mu >= 0 and (mu == 0 or math.isfinite(cap)), "prix de l'heure négatif, ou positif sans limite d'heures"
        borne = (mu * cap if mu > 0 else 0.0) + sum(frus[f]["scrap_an"] * max(g - mu * h for h, g, _ in p.values()) for f, p in plans.items())
        assert abs(marge - borne) <= tol * max(1.0, abs(borne)), f"marge {marge} différente de la borne {borne} (mu = {mu})"
    else:
        assert all(inconnu(resume[c]) for c in (MARGE, HEURES, TRAITEES, DETOURNEE, MU, RESULTAT)), "aucun type calculable : rien de chiffré"
    return {"marge": marge, "heures": heures, "kg": kg, "plans": plans, "borne": borne}


# --------------------------------------------------------------------------- optimum exact, deux façons
def _blocs(ligne: dict, frus: dict) -> list:
    """[(FRU scrapées, heures des plans, marges des plans)] par type calculable."""
    return [(float(frus[f]["scrap_an"]), np.array([v[0] for v in p.values()]), np.array([v[1] for v in p.values()]))
            for f, p in plans_de_la_ligne(ligne, frus).items()]


def optimum_solveur_exact(linprog, ligne: dict, frus: dict) -> float:
    """Optimum du programme linéaire du document (§7), par le solveur HiGHS de scipy.

    Variables x[f, s] ≥ 0 ; somme sur s de x[f, s] = FRU scrapées de f ; somme de heures × x ≤ capacité.
    """
    blocs = _blocs(ligne, frus)
    if not blocs:
        return 0.0
    g, h = np.concatenate([b[2] for b in blocs]), np.concatenate([b[1] for b in blocs])
    a_eq, debut = np.zeros((len(blocs), len(g))), 0
    for i, b in enumerate(blocs):
        a_eq[i, debut:debut + len(b[1])] = 1.0
        debut += len(b[1])
    cap = capacite(ligne)
    limite = {"A_ub": h[None, :], "b_ub": [cap]} if math.isfinite(cap) else {}
    r = linprog(-g, A_eq=a_eq, b_eq=[b[0] for b in blocs], bounds=(0, None), method="highs", **limite)
    assert r.status == 0, r.message
    return float(-r.fun)


def optimum_par_enumeration(ligne: dict, frus: dict) -> float:
    """Optimum du même programme linéaire par énumération de ses sommets, avec numpy seul.

    Un sommet donne à chaque type un seul plan, sauf à un type au plus, partagé entre deux plans de sorte que les
    heures soient exactement épuisées (une seule contrainte lie les types entre eux).
    """
    blocs = _blocs(ligne, frus)
    if not blocs:
        return 0.0
    cap = capacite(ligne)
    meilleur = -math.inf
    for combo in itertools.product(*[range(len(b[1])) for b in blocs]):
        if sum(n * h[i] for (n, h, _), i in zip(blocs, combo)) <= cap * (1 + 1e-12) + 1e-12:
            meilleur = max(meilleur, sum(n * g[i] for (n, _, g), i in zip(blocs, combo)))
    if math.isfinite(cap):
        for k, (n, h, g) in enumerate(blocs):
            if n <= 0:
                continue
            autres = [b for j, b in enumerate(blocs) if j != k]
            dh = h[None, :] - h[:, None]                                # dh[a, b] = heures du plan b − heures du plan a
            for combo in itertools.product(*[range(len(b[1])) for b in autres]):
                h0 = sum(m * hh[i] for (m, hh, _), i in zip(autres, combo))
                g0 = sum(m * gg[i] for (m, _, gg), i in zip(autres, combo))
                with np.errstate(divide="ignore", invalid="ignore"):
                    x = (cap - h0 - n * h[:, None]) / dh                # FRU passées du plan a au plan b
                    ok = (dh > 0) & (x >= 0) & (x <= n)
                    valeur = g0 + (n - x) * g[:, None] + x * g[None, :]
                if ok.any():
                    meilleur = max(meilleur, float(valeur[ok].max()))
    return meilleur


# --------------------------------------------------------------------------- lignes tirées au hasard
def piece_aleatoire(rng, grille: bool) -> dict:
    if grille:
        e = {"n_par_fru": float(rng.integers(1, 3)), "extraction_min": float(rng.choice([0, 6, 12, 30])), "test_min": float(rng.choice([0, 6, 12])),
             "tri_min": float(rng.choice([0, 3, 6])), "p_reutilisable": float(rng.choice([0.0, 0.5, 1.0])), "valeur_eur": float(rng.choice([0, 10, 20, 40])),
             "poids_kg": float(rng.choice([0.5, 1.0, 2.0])), "prix_recycleur_eur_kg": float(rng.choice([0, 1, 2, 4])),
             "transport_eur": float(rng.choice([0, 1])), "delai_semaines": float(rng.choice([0, 4])), "valeur_semaine_eur": 0.5}
    else:
        e = {"n_par_fru": float(rng.integers(1, 4)), "extraction_min": float(rng.uniform(0, 30)), "test_min": float(rng.uniform(0, 20)),
             "tri_min": float(rng.uniform(0, 8)), "p_reutilisable": float(rng.uniform(0, 1)), "valeur_eur": float(rng.uniform(0, 120)),
             "poids_kg": float(rng.uniform(0.01, 3)), "prix_recycleur_eur_kg": float(rng.uniform(-0.5, 6)),
             "transport_eur": float(rng.uniform(0, 3)), "delai_semaines": float(rng.uniform(0, 12)), "valeur_semaine_eur": float(rng.uniform(0, 3))}
    u = rng.random()
    if u < 0.10:
        e["tri_min"] = None                     # recyclage non calculable ; un exemplaire refusé au test reste vendu au kilo
    elif u < 0.18:
        e["prix_recycleur_eur_kg"] = None       # ni recyclage, ni revente des exemplaires refusés
    elif u < 0.24:
        e["poids_kg"] = None                    # ni recyclage, ni revente, ni traitement évité
    elif u < 0.34:
        e["valeur_eur"] = None                  # réemploi non calculable
    for k in ("transport_eur", "delai_semaines", "valeur_semaine_eur"):
        if rng.random() < 0.15:
            e[k] = None                         # entrée facultative non saisie
    return e


def ligne_aleatoire(rng, types=(2, 6), pieces=(1, 5)) -> tuple:
    """Une ligne et ses types de FRU. Une fois sur deux les valeurs sont prises sur une grille grossière, ce qui multiplie
    les ex æquo, les plans sans heure et les types de FRU qui changent de plan au même prix de l'heure."""
    grille = bool(rng.random() < 0.5)
    frus = {}
    for i in range(int(rng.integers(types[0], types[1] + 1))):
        d = {"scrap_an": float(rng.choice([0, 10, 20, 50])) if grille else float(rng.integers(0, 200)), "poids_fru_kg": float(rng.uniform(1, 30)),
             "ouverture_min": float(rng.choice([0, 6, 12])) if grille else float(rng.uniform(0, 40)),
             "pieces": {f"P{i}{j}": piece_aleatoire(rng, grille) for j in range(int(rng.integers(pieces[0], pieces[1] + 1)))}}
        if rng.random() < 0.6:
            d["ouverture_tri_min"] = float(rng.choice([0, 3, 6])) if grille else float(rng.uniform(0, 15))
        if rng.random() < 0.3:
            d["taux_horaire_eur"] = float(rng.choice([30, 60])) if grille else float(rng.uniform(25, 90))
        u = rng.random()
        if u < 0.03:
            d["scrap_an"] = None                    # type incomplet : nombre de FRU scrapées inconnu
        elif u < 0.05:
            d["taux_horaire_eur"] = None            # type incomplet : taux propre au FRU présent mais inconnu
        elif u < 0.08:
            d["ouverture_min"] = None               # plus de réemploi ; plus rien si l'ouverture sommaire n'est pas saisie
        frus[f"F{i}"] = d
    if len(frus) < types[1] and rng.random() < 0.4:                      # un type jumeau : mêmes plans, même prix de bascule
        f = list(frus)[int(rng.integers(0, len(frus)))]
        frus[f + "-BIS"] = dict(copy.deepcopy(frus[f]), scrap_an=float(rng.integers(1, 100)))
    ligne = {"heures_operateur_an": None, "taux_horaire_eur": 60.0 if grille else 45.0,
             "cout_traitement_eur_kg": float(rng.choice([0.0, 1.0])) if grille else float(rng.choice([0.0, 0.25, -0.1])),
             "cout_installation_eur": 10000.0, "amortissement_ans": 5.0, "couts_fixes_annuels_eur": 2000.0}
    return ligne, frus


def capacite_aleatoire(rng, ligne: dict, frus: dict):
    """Heures opérateur entre zéro et au-delà du besoin : aucune, illimitées, juste le besoin, un sommet, quelconques."""
    besoin = besoin_sans_limite(ligne, frus)
    u = rng.random()
    if u < 0.08:
        return 0.0
    if u < 0.14:
        return None
    if u < 0.22:
        return besoin
    if u < 0.30:
        return besoin * 1.3
    if u < 0.45:                                                        # exactement les heures d'un plan pur par type
        total = 0.0
        for f, plans in plans_de_la_ligne(ligne, frus).items():
            total += frus[f]["scrap_an"] * list(plans.values())[int(rng.integers(0, len(plans)))][0]
        return total
    if u < 0.55:
        return float(round(besoin * rng.random()))
    return besoin * float(rng.random())


@functools.lru_cache(maxsize=None)
def bloc(k: int) -> tuple:
    """PAR_BLOC lignes tirées au hasard avec leur résultat ; calculé une fois, relu par plusieurs tests."""
    rng = np.random.default_rng(20260 + k)
    out = []
    for _ in range(PAR_BLOC):
        ligne, frus = ligne_aleatoire(rng)
        ligne["heures_operateur_an"] = capacite_aleatoire(rng, ligne, frus)
        out.append((ligne, frus, L.optimiser_ligne(ligne, frus)))
    return tuple(out)


def chaque(k: int, verifier):
    """Applique `verifier(ligne, frus, résultat)` aux lignes du bloc k, en nommant celle qui échoue."""
    for i, (ligne, frus, res) in enumerate(bloc(k)):
        try:
            verifier(ligne, frus, res)
        except AssertionError as e:
            raise AssertionError(f"bloc {k}, ligne {i} (capacité {ligne['heures_operateur_an']}) : {e}") from e


# --------------------------------------------------------------------------- modèles fixes des tests
def ligne_main(**remplace) -> dict:
    d = {"heures_operateur_an": None, "taux_horaire_eur": 60.0, "cout_traitement_eur_kg": 0.5,
         "cout_installation_eur": 5000.0, "amortissement_ans": 5.0, "couts_fixes_annuels_eur": 400.0}
    d.update(remplace)
    return d


def piece_main(**remplace) -> dict:
    """Pièce P-1 des cas calculés à la main. À 60 €/h, une minute coûte 1 €."""
    d = {"n_par_fru": 2.0, "extraction_min": 6.0, "test_min": 3.0, "tri_min": 3.0, "p_reutilisable": 0.5, "valeur_eur": 40.0,
         "delai_semaines": 4.0, "valeur_semaine_eur": 2.5, "transport_eur": 1.0, "poids_kg": 0.5, "prix_recycleur_eur_kg": 2.0}
    d.update(remplace)
    return d


def fru_main(pieces: dict | None = None, **remplace) -> dict:
    d = {"scrap_an": 100.0, "poids_fru_kg": 10.0, "ouverture_min": 12.0, "ouverture_tri_min": 6.0,
         "pieces": {"P-1": piece_main()} if pieces is None else pieces}
    d.update(remplace)
    return d


def modele_matrice() -> tuple:
    """Deux types de FRU entièrement renseignés, 60 heures par an : les heures manquent, les deux types sont servis.

    FRU-T1, par FRU : P-1 en réemploi (31,5 € hors ouverture), P-2 au recyclage (12,5 €), ouverture soignée 12 € :
    32 € en 0,525 h. FRU-T2 : P-3 en réemploi (12,14 €), ouverture 9 € : 3,14 € en 0,35 h.
    Sans limite : 100 × 32 + 50 × 3,14 = 3 357 € en 70 h. Avec 60 h : FRU-T1 en entier (52,5 h), puis 7,5 h de FRU-T2.
    """
    p2 = {"n_par_fru": 1.0, "extraction_min": 5.0, "test_min": 5.0, "tri_min": 1.5, "p_reutilisable": 0.2, "valeur_eur": 10.0,
          "delai_semaines": 2.0, "valeur_semaine_eur": 1.0, "transport_eur": 0.5, "poids_kg": 4.0, "prix_recycleur_eur_kg": 3.0}
    p3 = {"n_par_fru": 1.0, "extraction_min": 6.0, "test_min": 6.0, "tri_min": 2.0, "p_reutilisable": 0.8, "valeur_eur": 30.0,
          "delai_semaines": 1.25, "valeur_semaine_eur": 1.0, "transport_eur": 1.0, "poids_kg": 0.2, "prix_recycleur_eur_kg": 1.0}
    frus = {"FRU-T1": fru_main({"P-1": piece_main(), "P-2": p2}),
            "FRU-T2": {"scrap_an": 50.0, "poids_fru_kg": 4.0, "ouverture_min": 9.0, "ouverture_tri_min": 4.0, "pieces": {"P-3": p3}}}
    return ligne_main(heures_operateur_an=60.0), frus


def options(ligne: dict, fru: dict) -> pd.DataFrame:
    """Table des trois options par pièce, comme la calcule le pipeline."""
    t = L.valeurs_options(dict(fru, _c_trait=ligne.get("cout_traitement_eur_kg")), ligne.get("taux_horaire_eur"))
    par_piece = t.set_index("Pièce")
    par_piece.attrs = dict(t.attrs)
    return par_piece


# =========================================================================== 1. cas calculés à la main
def test_un_type_une_piece_calcule_a_la_main():
    """Réemploi de P-1, par FRU : 2 × [0,5 × (40 + 4 × 2,5) + 0,5 × (0,5 kg × 2 €/kg) − 1] = 49 € ;
    main-d'œuvre 2 × (6 + 3) min = 18 € ; traitement évité 0,5 €/kg × 1 kg = 0,5 € ; ouverture soignée 12 €.
    Marge 49 + 0,5 − 18 − 12 = 19,5 € en 0,5 h. Recyclage seul : 2 + 0,5 − 6 − 6 = −9,5 €, jamais retenu."""
    ligne, frus = ligne_main(), {"FRU-T1": fru_main()}
    t = options(ligne, frus["FRU-T1"])
    assert t.at["P-1", RE] == vaut(31.5) and t.at["P-1", RC] == vaut(-3.5) and t.at["P-1", "3 Jeté (€/FRU)"] == 0.0
    assert t.at["P-1", "Heures réemploi"] == vaut(0.3) and t.at["P-1", "Heures recyclage"] == vaut(0.1)
    assert t.at["P-1", "Kg détournés réemploi"] == vaut(1.0) and t.at["P-1", "Kg détournés recyclage"] == vaut(1.0)
    assert t.at["P-1", "Meilleure option seule"] == "Réemploi"
    assert t.at["P-1", "Manque réemploi"] == "" and t.at["P-1", "Manque recyclage"] == "" and t.at["P-1", "Non compté faute de donnée"] == ""
    assert t.attrs["Ouverture soignée (€/FRU)"] == vaut(12.0) and t.attrs["Ouverture sommaire (€/FRU)"] == vaut(6.0)

    res = L.optimiser_ligne(ligne, frus)
    controler(ligne, frus, res)
    d, r = res["detail"].iloc[0], res["resume"]
    assert len(res["detail"]) == 1 and d["Décision"] == "traiter" and d["1 Réemploi"] == "P-1" and d["2 Recyclage"] == ""
    assert d["Heures par FRU"] == vaut(0.5) and d["Marge par FRU (€)"] == vaut(19.5) and d["Marge par heure (€)"] == vaut(39.0)
    assert r[MARGE] == vaut(1950.0) and r[HEURES] == vaut(50.0) and r[TRAITEES] == vaut(100.0)
    assert r[FIXES] == vaut(1400.0) and r[RESULTAT] == vaut(550.0)                # 5 000 / 5 + 400
    assert r[CAPACITE] == math.inf and inconnu(r[OCCUPATION]) and r[MU] == 0.0
    assert r[MOYENNE] == vaut(19.5) and r[SEUIL] == vaut(1400.0 / 19.5) and r[RETOUR] == vaut(5000.0 / 1550.0)
    assert r[INCOMPLETS] == 0 and r[MASSE] == vaut(1000.0) and r[DETOURNEE] == vaut(100.0) and r[ACTUEL] == vaut(500.0)

    # 20 heures par an : 40 FRU sur 100, et une heure de plus vaut 19,5 / 0,5 = 39 €
    r = L.optimiser_ligne(dict(ligne, heures_operateur_an=20.0), frus)["resume"]
    assert r[TRAITEES] == vaut(40.0) and r[MARGE] == vaut(780.0) and r[HEURES] == vaut(20.0) and r[OCCUPATION] == vaut(1.0)
    assert r[MU] == vaut(39.0, rel=1e-9) and r[RESULTAT] == vaut(-620.0) and r[DETOURNEE] == vaut(40.0)


def modele_deux_types() -> tuple:
    """Sans recyclage ni traitement évité, à 60 €/h, 10 FRU de chaque type par an.
    FRU-X : une pièce, 30 € en 1 h (30 €/h). FRU-Y : A seule, 20 € en 0,5 h (40 €/h) ; A et B, 26 € en 1 h, soit 6 € de
    plus pour 0,5 h de plus (12 €/h) ; B seule perd 6 €."""
    def p(ext, test, valeur):
        return {"n_par_fru": 1.0, "extraction_min": ext, "test_min": test, "p_reutilisable": 1.0, "valeur_eur": valeur}
    frus = {"FRU-X": {"scrap_an": 10.0, "poids_fru_kg": 5.0, "ouverture_min": 30.0, "pieces": {"X1": p(20.0, 10.0, 90.0)}},
            "FRU-Y": {"scrap_an": 10.0, "poids_fru_kg": 5.0, "ouverture_min": 12.0, "pieces": {"A": p(12.0, 6.0, 50.0), "B": p(20.0, 10.0, 36.0)}}}
    return ligne_main(cout_traitement_eur_kg=0.0), frus


@pytest.mark.parametrize("heures, marge, mu, traitees, utilisees", [
    (0.0, 0.0, 40.0, 0.0, 0.0),             # aucune heure : la première irait à FRU-Y, 40 €/h
    (3.0, 120.0, 40.0, 6.0, 3.0),           # 6 FRU-Y avec A seule
    (12.0, 410.0, 30.0, 17.0, 12.0),        # les 10 FRU-Y (5 h, 200 €) puis 7 FRU-X (7 h, 210 €)
    (17.0, 524.0, 12.0, 20.0, 17.0),        # tout FRU-X (300 €), FRU-Y : 4 avec A et B (104 €), 6 avec A seule (120 €)
    (20.0, 560.0, 0.0, 20.0, 20.0),         # exactement le besoin : plus rien à gagner
    (30.0, 560.0, 0.0, 20.0, 20.0),
    (None, 560.0, 0.0, 20.0, 20.0),
])
def test_deux_types_heures_comptees_calcule_a_la_main(heures, marge, mu, traitees, utilisees):
    ligne, frus = modele_deux_types()
    ligne["heures_operateur_an"] = heures
    res = L.optimiser_ligne(ligne, frus)
    controler(ligne, frus, res)
    r = res["resume"]
    assert r[MARGE] == vaut(marge) and r[TRAITEES] == vaut(traitees) and r[HEURES] == vaut(utilisees)
    assert r[MU] == vaut(mu, rel=1e-9, abs_=1e-9)
    if mu == 0.0:
        assert r[MU] == 0.0, "heures suffisantes, y compris quand elles couvrent tout juste le besoin : zéro exactement"
    if heures == 17.0:                      # le type à la marge est partagé entre deux plans
        y = res["detail"][res["detail"]["Type de FRU"].eq("FRU-Y")].set_index("1 Réemploi")["FRU traitées / an"]
        assert y.to_dict() == {"A, B": vaut(4.0), "A": vaut(6.0)}


def test_ouverture_payee_une_fois_et_selon_le_plan():
    """Deux pièces réemployées : une seule ouverture soignée. Recyclage seul : ouverture sommaire, à défaut la soignée."""
    ligne = ligne_main(cout_traitement_eur_kg=0.0)
    fru = fru_main({"P-1": piece_main(), "P-1b": piece_main(), "R": piece_main(valeur_eur=None, prix_recycleur_eur_kg=30.0)})
    plans = plans_document(ligne, fru)
    etiquettes, h, m, _ = L.options_fru(dict(fru, _c_trait=0.0), 60.0)
    code = {(frozenset(p for p, o in e if o == "réemploi"), frozenset(p for p, o in e if o == "recyclage")): (hh, mm) for e, hh, mm in zip(etiquettes, h, m)}
    assert set(code) == set(plans)
    for cle, (hh, mm) in code.items():
        assert hh == vaut(plans[cle][0]) and mm == vaut(plans[cle][1])
    f = frozenset
    # par pièce réemployée : 49 − 18 = 31 € en 0,3 h ; R recyclée : 2 × 0,5 × 30 − 6 = 24 € en 0,1 h
    assert code[(f(["P-1"]), f())] == (vaut(0.5), vaut(19.0))                        # 0,3 + 12 min ; 31 − 12
    assert code[(f(["P-1", "P-1b"]), f())] == (vaut(0.8), vaut(50.0))                # 0,6 + 12 min ; 62 − 12, et non 62 − 24
    assert code[(f(), f(["R"]))] == (vaut(0.2), vaut(18.0))                          # 0,1 + 6 min ; 24 − 6
    assert code[(f(["P-1"]), f(["R"]))] == (vaut(0.6), vaut(43.0))                   # ouverture soignée seule : 31 + 24 − 12
    # sans ouverture sommaire saisie (clé absente), le tri seul paie l'ouverture soignée
    sans = {k: v for k, v in fru.items() if k != "ouverture_tri_min"}
    assert plans_document(ligne, sans)[(f(), f(["R"]))] == (vaut(0.3), vaut(12.0), vaut(1.0))
    controler(ligne, {"F": sans})
    assert L.optimiser_ligne(ligne, {"F": sans})["detail"].iloc[0]["Marge par FRU (€)"] == vaut(31.0 + 31.0 + 24.0 - 12.0)


@pytest.mark.parametrize("remplace, reemploi, kg, non_compte", [
    ({}, 31.5, 1.0, ""),
    # prix du recycleur inconnu : l'exemplaire refusé retourne à la benne ; seule la moitié réutilisable (q = 0,5) la quitte
    ({"prix_recycleur_eur_kg": None}, 2 * (25 - 1) - 18 + 0.5 * 0.5, 0.5, "revente au kilo des exemplaires refusés au test"),
    # poids inconnu : ni revente, ni traitement évité
    ({"poids_kg": None}, 2 * (25 - 1) - 18, 0.0, "revente au kilo des exemplaires refusés au test, traitement évité"),
    # temps de tri inconnu : le recyclage n'est pas calculable, mais l'exemplaire refusé au test est vendu comme avant
    ({"tri_min": None}, 31.5, 1.0, ""),
    ({"transport_eur": None}, 33.5, 1.0, "transport"),
    ({"delai_semaines": None}, 21.5, 1.0, "délai évité"),
    ({"valeur_semaine_eur": None}, 21.5, 1.0, "délai évité"),
])
def test_reemploi_exemplaires_refuses_et_entrees_facultatives(remplace, reemploi, kg, non_compte):
    ligne, fru = ligne_main(), fru_main({"P-1": piece_main(**remplace)})
    t = options(ligne, fru)
    assert t.at["P-1", RE] == vaut(reemploi)
    assert t.at["P-1", "Kg détournés réemploi"] == vaut(kg)
    assert t.at["P-1", "Non compté faute de donnée"] == non_compte
    assert t.at["P-1", "Heures réemploi"] == vaut(0.3)
    controler(ligne, {"FRU-T1": fru})


def test_ouverture_sommaire_inconnue_n_empeche_pas_la_revente_des_exemplaires_refuses():
    ligne, fru = ligne_main(), fru_main(ouverture_tri_min=None)
    t = options(ligne, fru)
    assert t.at["P-1", RE] == vaut(31.5) and inconnu(t.at["P-1", RC]) and t.at["P-1", "Manque recyclage"] == "ouverture_tri_min"
    assert inconnu(t.attrs["Ouverture sommaire (€/FRU)"]) and t.attrs["Ouverture soignée (€/FRU)"] == vaut(12.0)


def test_recycleur_actuel_gratuit_ou_qui_paie():
    """Coût de traitement nul : rien à éviter. Négatif (le recycleur actuel paie) : sortir une pièce de la benne coûte."""
    fru = fru_main()
    assert options(ligne_main(cout_traitement_eur_kg=0.0), fru).at["P-1", RE] == vaut(31.0)
    assert options(ligne_main(cout_traitement_eur_kg=-0.2), fru).at["P-1", RE] == vaut(31.0 - 0.2)
    assert options(ligne_main(cout_traitement_eur_kg=-0.2), fru).at["P-1", RC] == vaut(2.0 - 6.0 - 0.2)
    r = L.optimiser_ligne(ligne_main(cout_traitement_eur_kg=-0.2), {"FRU-T1": fru})["resume"]
    assert r[ACTUEL] == vaut(-200.0) and r[MARGE] == vaut(100 * (31.0 - 0.2 - 12.0))
    # appel direct sans coût de traitement (clé « _c_trait » absente) : le traitement évité n'est pas compté, et c'est dit
    t = L.valeurs_options(fru, 60.0).set_index("Pièce")
    assert t.at["P-1", RE] == vaut(31.0) and t.at["P-1", "Non compté faute de donnée"] == "traitement évité"


def test_options_recalculees_depuis_le_document():
    """Tous les plans de 120 types de FRU tirés au hasard : mêmes plans calculables, mêmes heures, marges et kg."""
    rng = np.random.default_rng(4)
    compares = 0
    for _ in range(30):
        ligne, frus = ligne_aleatoire(rng, types=(4, 4), pieces=(1, 4))
        for f, d in frus.items():
            attendus = plans_document(ligne, d)
            etiq, h, m, k = L.options_fru(dict(d, _c_trait=ligne["cout_traitement_eur_kg"]), ligne["taux_horaire_eur"])
            trouves = {(frozenset(p for p, o in e if o == "réemploi"), frozenset(p for p, o in e if o == "recyclage")): (hh, mm, k[e])
                       for e, hh, mm in zip(etiq, h, m)}
            assert set(trouves) == set(attendus), f"{f} : plans calculables différents"
            for cle, v in trouves.items():
                assert v == (vaut(attendus[cle][0]), vaut(attendus[cle][1]), vaut(attendus[cle][2])), f"{f} {cle}"
            compares += len(trouves)
    assert compares > 2000


# =========================================================================== 2. optimalité
@pytest.mark.parametrize("k", range(N_BLOCS))
def test_optimum_atteint_la_borne_sans_scipy(k):
    """Plan réalisable, résumé cohérent, et marge égale à la borne qu'aucun plan ne dépasse (voir `controler`)."""
    chaque(k, lambda ligne, frus, res: controler(ligne, frus, res))


@pytest.mark.parametrize("k", range(N_BLOCS))
def test_optimum_egal_au_solveur_exact(k):
    """La marge de `optimiser_ligne` est l'optimum du programme linéaire du document, à 1e-6 près en relatif."""
    linprog = pytest.importorskip("scipy.optimize", reason="scipy n'est pas installé : comparaison au solveur exact sautée").linprog

    def verifier(ligne, frus, res):
        r, d = res["resume"], res["detail"]
        exact = optimum_solveur_exact(linprog, ligne, frus)
        marge = 0.0 if inconnu(r[MARGE]) else r[MARGE]
        assert abs(marge - exact) <= REL * max(1.0, abs(exact)), f"marge {marge}, optimum exact {exact}"
        cap = capacite(ligne)
        assert inconnu(r[HEURES]) or r[HEURES] <= cap * (1 + 1e-9) + 1e-9, "heures au-delà de la capacité"
        traitees = d.groupby("Type de FRU")["FRU traitées / an"].sum(min_count=1).dropna()
        for f, x in traitees.items():
            assert x <= frus[f]["scrap_an"] * (1 + 1e-9) + 1e-9, f"{f} : plus de FRU traitées que scrapées"
    chaque(k, verifier)


def test_les_lignes_tirees_couvrent_les_cas_difficiles():
    """Le tirage contient bien ce qu'il doit éprouver : heures qui manquent, types jumeaux, types partagés entre deux plans..."""
    vus = {"sans heure": 0, "heures illimitées": 0, "heures qui manquent": 0, "heures suffisantes": 0, "type jumeau": 0,
           "type partagé entre deux plans": 0, "plusieurs types changent de plan au même prix": 0, "plan sans heure": 0, "type incomplet": 0}
    for k in range(N_BLOCS):
        for ligne, frus, res in bloc(k):
            r, d = res["resume"], res["detail"]
            cap = capacite(ligne)
            vus["sans heure"] += cap == 0
            vus["heures illimitées"] += math.isinf(cap)
            vus["heures qui manquent"] += bool(r[MU] > 1e-9)
            vus["heures suffisantes"] += bool(r[MU] == 0 and math.isfinite(cap))
            vus["type jumeau"] += any(f.endswith("-BIS") for f in frus)
            vus["type incomplet"] += r[INCOMPLETS] > 0
            calc = d[d["Décision"].ne("incomplet")]
            vus["type partagé entre deux plans"] += bool(calc["Type de FRU"].duplicated().any())
            vus["plan sans heure"] += bool(((calc["Heures par FRU"] == 0) & calc["Décision"].eq("traiter")).any())
            if r[MU] > 1e-9:                    # types indifférents entre deux plans au prix annoncé
                mu, indifferents = r[MU], 0
                for f, plans in plans_de_la_ligne(ligne, frus).items():
                    nets = sorted((g - mu * h for h, g, _ in plans.values()), reverse=True)
                    indifferents += frus[f]["scrap_an"] > 0 and nets[0] - nets[1] <= 1e-7 * max(1.0, abs(nets[0]))
                vus["plusieurs types changent de plan au même prix"] += indifferents >= 2
    assert sum(len(bloc(k)) for k in range(N_BLOCS)) >= 500
    for cas, n in vus.items():
        assert n >= 15, f"cas trop rare dans le tirage : {cas} ({n} lignes)"


def test_optimum_egal_a_l_enumeration_des_sommets():
    """Petites lignes (2 ou 3 types, 1 ou 2 pièces) : tous les sommets du programme linéaire sont énumérés, sans scipy."""
    rng = np.random.default_rng(77)
    saturees = 0
    for i in range(150):
        ligne, frus = ligne_aleatoire(rng, types=(2, 3), pieces=(1, 2))
        ligne["heures_operateur_an"] = capacite_aleatoire(rng, ligne, frus)
        r = L.optimiser_ligne(ligne, frus)["resume"]
        exact = optimum_par_enumeration(ligne, frus)
        marge = 0.0 if inconnu(r[MARGE]) else r[MARGE]
        assert abs(marge - exact) <= REL * max(1.0, abs(exact)), f"ligne {i} : marge {marge}, optimum par énumération {exact}"
        saturees += bool(r[MU] > 1e-9)
    assert saturees >= 40


def test_types_jumeaux_qui_changent_de_plan_au_meme_prix():
    """Trois types identiques (mêmes plans, 39 €/h) et un quatrième moins rentable : à chaque capacité, la marge est
    celle du calcul à la main, quel que soit le type servi en premier."""
    ligne = ligne_main()
    frus = {f"FRU-J{i}": fru_main(scrap_an=n) for i, n in enumerate((40.0, 25.0, 35.0))}               # 0,5 h et 19,5 € par FRU
    frus["FRU-K"] = fru_main({"P-1": piece_main(valeur_eur=30.0)})                                     # 0,5 h et 9,5 € par FRU, 100 FRU
    for heures in (0.0, 5.0, 20.0, 32.5, 49.99, 50.0, 50.01, 70.0, 100.0, 120.0):
        ligne["heures_operateur_an"] = heures
        res = L.optimiser_ligne(ligne, frus)
        attendu = 39.0 * min(heures, 50.0) + 19.0 * min(max(heures - 50.0, 0.0), 50.0)
        assert res["resume"][MARGE] == vaut(attendu), f"{heures} h"
        assert res["resume"][MU] == vaut(39.0 if heures < 50 else 19.0 if heures < 100 else 0.0, rel=1e-9, abs_=1e-9), f"{heures} h"
        assert attendu == vaut(optimum_par_enumeration(ligne, frus))
        controler(ligne, frus, res)


def test_plans_alignes_et_ex_aequo_a_marge_nulle():
    """Deux pièces identiques sans ouverture : 0, 1 ou 2 pièces extraites s'alignent (même gain par heure). Une pièce qui
    ne rapporte rien ne change pas la marge."""
    ligne = ligne_main(cout_traitement_eur_kg=0.0)
    p = {"n_par_fru": 1.0, "extraction_min": 6.0, "test_min": 0.0, "p_reutilisable": 1.0, "valeur_eur": 10.0}       # 4 € en 0,1 h
    nulle = {"n_par_fru": 1.0, "extraction_min": 0.0, "test_min": 0.0, "p_reutilisable": 1.0, "valeur_eur": 0.0}    # 0 € en 0 h
    frus = {"F1": {"scrap_an": 30.0, "poids_fru_kg": 1.0, "ouverture_min": 0.0, "pieces": {"a": dict(p), "b": dict(p), "z": nulle}},
            "F2": {"scrap_an": 20.0, "poids_fru_kg": 1.0, "ouverture_min": 0.0, "pieces": {"a": dict(p), "b": dict(p)}}}
    for heures in (0.0, 1.0, 3.0, 4.5, 6.0, 9.999, 10.0, 12.0, None):
        ligne["heures_operateur_an"] = heures
        res = L.optimiser_ligne(ligne, frus)
        controler(ligne, frus, res)
        assert res["resume"][MARGE] == vaut(40.0 * min(10.0 if heures is None else heures, 10.0)), f"{heures} h"


def test_resultat_independant_de_l_ordre_des_types_et_des_pieces():
    ligne, frus = modele_matrice()
    base = L.optimiser_ligne(ligne, frus)["resume"]
    inverse = {f: dict(d, pieces=dict(reversed(list(d["pieces"].items())))) for f, d in reversed(list(frus.items()))}
    autre = L.optimiser_ligne(ligne, inverse)["resume"]
    assert all(pareil(base[c], autre[c]) for c in CLES_RESUME)


def changer_d_unites(ligne: dict, frus: dict, argent: float, temps: float) -> tuple:
    """Le même modèle avec l'argent multiplié par `argent` et les durées par `temps` (le taux horaire suit les deux)."""
    ligne, frus = copy.deepcopy(ligne), copy.deepcopy(frus)

    def fois(d, cles, k):
        for c in cles:
            if not inconnu(d.get(c)):
                d[c] = d[c] * k
    fois(ligne, ("cout_traitement_eur_kg", "cout_installation_eur", "couts_fixes_annuels_eur"), argent)
    fois(ligne, ("taux_horaire_eur",), argent / temps)
    fois(ligne, ("heures_operateur_an",), temps)
    for d in frus.values():
        fois(d, ("ouverture_min", "ouverture_tri_min"), temps)
        fois(d, ("taux_horaire_eur",), argent / temps)
        for e in d["pieces"].values():
            fois(e, ("valeur_eur", "prix_recycleur_eur_kg", "transport_eur", "valeur_semaine_eur"), argent)
            fois(e, ("extraction_min", "test_min", "tri_min"), temps)
    return ligne, frus


@pytest.mark.parametrize("argent, temps", [(100.0, 1.0), (1.0, 60.0), (1e-3, 1e3), (1e4, 1e-3)])
def test_resultat_insensible_aux_unites(argent, temps):
    """Compter en centimes plutôt qu'en euros, en secondes plutôt qu'en minutes : la marge suit l'unité d'argent et rien
    d'autre ne change. Aucun seuil du calcul n'est donc réglé pour une échelle particulière."""
    rng = np.random.default_rng(61)
    for i in range(12):
        ligne, frus = ligne_aleatoire(rng)
        ligne["heures_operateur_an"] = capacite_aleatoire(rng, ligne, frus)
        base = L.optimiser_ligne(ligne, frus)["resume"]
        r = L.optimiser_ligne(*changer_d_unites(ligne, frus, argent, temps))["resume"]
        assert pareil(r[MARGE], base[MARGE] * argent, rel=1e-9, abs_=1e-9 * argent), f"ligne {i} : marge {r[MARGE]} au lieu de {base[MARGE] * argent}"
        assert pareil(r[FIXES], base[FIXES] * argent) and r[INCOMPLETS] == base[INCOMPLETS] and pareil(r[MASSE], base[MASSE])
    ligne, frus = modele_matrice()                                          # sans ex æquo : tout le résumé suit
    base = L.optimiser_ligne(ligne, frus)["resume"]
    r = L.optimiser_ligne(*changer_d_unites(ligne, frus, argent, temps))["resume"]
    facteur = {MARGE: argent, FIXES: argent, RESULTAT: argent, MOYENNE: argent, ACTUEL: argent, HEURES: temps, CAPACITE: temps, MU: argent / temps}
    for c in CLES_RESUME:
        assert pareil(r[c], base[c] * facteur.get(c, 1.0), rel=1e-9, abs_=1e-12), c


def test_entrees_absentes_rien_ne_plante():
    """Sans ligne, sans FRU, sans flux : des tables vides ou des indicateurs inconnus, jamais une erreur."""
    assert all(inconnu(v) or v in (0, math.inf) for v in L.optimiser_ligne(None, None)["resume"].values())
    t = L.comparer_scenarios(None, None)
    assert len(t) == 4 and inconnu(t["Écart"].iloc[-1]) and inconnu(t.attrs["Part détournée"])
    mc = L.monte_carlo_ligne(None, None, n=2, rng=0)
    assert inconnu(mc["P(ligne rentable)"]) and len(mc["tirages"]) == 2
    t = L.resultat_par_periode(None, None, flux([("S1", "FRU-T1", 3)]))
    assert len(t) == 1 and inconnu(t.at[0, "Résultat (€)"]) and t.at[0, "FRU arrivées"] == 0.0
    f = flux([("S1", "FRU-T1", 3)])
    f["Semaine complète"] = [False]                                          # toutes les semaines écartées
    t = L.resultat_par_periode(*modele_periodes(), f)
    assert len(t) == 0 and list(t.columns) == L.COLONNES_PERIODE
    assert L.options_disponibles({}) == {} and len(L.valeurs_options({}, None)) == 0
    assert L.options_fru({"pieces": {}}, 60.0)[0] == [()]                     # un seul plan : laisser le FRU tel quel
    assert L.Options({"pieces": None}, 60.0).meilleur(0.0) == ((), 0.0, 0.0, 0.0)


def test_entrees_non_modifiees_et_plages_lues_en_leur_centre():
    ligne, frus = modele_plages()
    avant = copy.deepcopy((ligne, frus))
    res = L.optimiser_ligne(ligne, frus)
    assert (ligne, frus) == avant, "optimiser_ligne ne doit pas modifier ses entrées"
    centre = L.optimiser_ligne(*modele_matrice())
    assert all(pareil(res["resume"][c], centre["resume"][c]) for c in CLES_RESUME)
    pd.testing.assert_frame_equal(res["detail"], centre["detail"])
    assert all(pareil(a, b) for a, b in zip(L.point_milieu(ligne, frus)["resume"].values(), centre["resume"].values()))
    en_listes = L._milieu({"a": [1.0, 3.0], "b": [1.0, 2.0, 9.0], "c": {"d": (2.0, 4.0)}})         # modèle relu d'un fichier JSON
    assert en_listes == {"a": 2.0, "b": 2.0, "c": {"d": 3.0}}


# =========================================================================== 3. valeur d'une heure en plus
@pytest.mark.parametrize("k", range(4))
def test_valeur_d_une_heure_en_plus_egale_a_la_pente_de_la_marge(k):
    """La marge optimale croît avec les heures, de moins en moins vite. Le multiplicateur est compris entre la pente à
    droite et la pente à gauche, et leur est égal là où elles coïncident. Il vaut 0 dès que les heures ne manquent pas."""
    rng = np.random.default_rng(500 + k)
    derivables = libres = 0
    for i in range(22):
        ligne, frus = ligne_aleatoire(rng)
        besoin = besoin_sans_limite(ligne, frus)
        if besoin <= 0:
            continue
        cap = besoin * float(rng.uniform(0.02, 1.25))
        pas = besoin * 1e-5

        def resume(heures):
            return L.optimiser_ligne(dict(ligne, heures_operateur_an=heures), frus)["resume"]
        r = resume(cap)
        gauche = (r[MARGE] - resume(cap - pas)[MARGE]) / pas
        droite = (resume(cap + pas)[MARGE] - r[MARGE]) / pas
        tol = 1e-6 * max(1.0, abs(gauche))
        assert gauche >= droite - tol >= -2 * tol, f"ligne {i} : la marge doit croître de moins en moins vite"
        assert droite - tol <= r[MU] <= gauche + tol, f"ligne {i} : mu {r[MU]} hors de [{droite}, {gauche}]"
        if gauche - droite <= tol:
            derivables += 1
            assert r[MU] == vaut(droite, rel=1e-6, abs_=1e-6), f"ligne {i}"
        if cap >= besoin:
            libres += 1
            assert r[MU] == 0.0, f"ligne {i} : heures suffisantes, une heure de plus ne vaut rien"
        if r[HEURES] < cap * (1 - 1e-9):
            assert r[MU] <= 1e-9, f"ligne {i} : des heures restent libres, une heure de plus ne vaut rien"
    assert derivables >= 12 and libres >= 1


def test_valeur_d_une_heure_en_plus_sur_le_modele_a_deux_types():
    """Entre deux seuils, la marge gagne exactement mu euros par heure ajoutée."""
    ligne, frus = modele_deux_types()

    def resume(heures):
        return L.optimiser_ligne(dict(ligne, heures_operateur_an=heures), frus)["resume"]
    for heures, mu in ((2.0, 40.0), (8.0, 30.0), (16.0, 12.0), (25.0, 0.0)):
        assert resume(heures)[MU] == vaut(mu, rel=1e-9, abs_=1e-9)
        assert resume(heures + 1.0)[MARGE] - resume(heures)[MARGE] == vaut(mu, abs_=1e-7)


# =========================================================================== 4. entrées inconnues
INCONNUS = [None, float("nan"), np.float64("nan"), pd.NA]


def modele_plages() -> tuple:
    """Le modèle de `modele_matrice` avec des plages dont le centre est la valeur d'origine."""
    ligne, frus = modele_matrice()
    ligne.update(taux_horaire_eur=(50.0, 60.0, 75.0), cout_traitement_eur_kg=(0.3, 0.7), cout_installation_eur=(4000.0, 5000.0, 8000.0))
    frus["FRU-T1"].update(scrap_an=(80.0, 100.0, 130.0), ouverture_min=(8.0, 16.0))
    frus["FRU-T1"]["pieces"]["P-1"].update(p_reutilisable=(0.3, 0.5, 0.7), valeur_eur=(30.0, 40.0, 55.0), extraction_min=(4.0, 6.0, 9.0))
    frus["FRU-T1"]["pieces"]["P-2"].update(prix_recycleur_eur_kg=(2.0, 4.0))
    frus["FRU-T2"]["pieces"]["P-3"].update(p_reutilisable=(0.7, 0.8, 0.95))
    return ligne, frus


def test_modele_de_reference_calcule_a_la_main():
    ligne, frus = modele_matrice()
    t1, t2 = options(ligne, frus["FRU-T1"]), options(ligne, frus["FRU-T2"])
    assert t1.at["P-1", RE] == vaut(31.5) and t1.at["P-1", RC] == vaut(-3.5)
    assert t1.at["P-2", RE] == vaut(3.5) and t1.at["P-2", RC] == vaut(12.5)
    assert t2.at["P-3", RE] == vaut(12.14) and t2.at["P-3", RC] == vaut(-1.7)
    libre = L.optimiser_ligne(dict(ligne, heures_operateur_an=None), frus)["resume"]
    assert libre[MARGE] == vaut(3357.0) and libre[HEURES] == vaut(70.0)
    res = L.optimiser_ligne(ligne, frus)
    controler(ligne, frus, res)
    r = res["resume"]
    assert r[MARGE] == vaut(3200.0 + 7.5 / 0.35 * 3.14) and r[HEURES] == vaut(60.0) and r[MU] == vaut(3.14 / 0.35, rel=1e-9)
    assert r[MASSE] == vaut(1200.0) and r[ACTUEL] == vaut(600.0)
    d = res["detail"][res["detail"]["Décision"].eq("traiter")].set_index("Type de FRU")
    assert d.at["FRU-T1", "1 Réemploi"] == "P-1" and d.at["FRU-T1", "2 Recyclage"] == "P-2" and d.at["FRU-T1", "Marge par FRU (€)"] == vaut(32.0)
    assert d.at["FRU-T1", "FRU traitées / an"] == vaut(100.0) and d.at["FRU-T2", "FRU traitées / an"] == vaut(7.5 / 0.35)


def _sans_limite():
    ligne, frus = modele_matrice()
    return dict(ligne, heures_operateur_an=None), frus


@pytest.mark.parametrize("vide", INCONNUS, ids=["None", "nan", "numpy nan", "pd.NA"])
@pytest.mark.parametrize("champ", ["cout_installation_eur", "amortissement_ans", "couts_fixes_annuels_eur"])
def test_inconnue_de_cout_fixe_rend_inconnus_les_indicateurs_qui_en_dependent(champ, vide):
    """Tout indicateur du résumé qui change quand le paramètre change doit être inconnu quand le paramètre l'est ;
    les autres indicateurs et le plan ne bougent pas."""
    ligne, frus = modele_matrice()
    base = L.optimiser_ligne(ligne, frus)
    a = L.optimiser_ligne(dict(ligne, **{champ: ligne[champ] * 0.5}), frus)["resume"]
    b = L.optimiser_ligne(dict(ligne, **{champ: ligne[champ] * 3.0}), frus)["resume"]
    dependants = {c for c in CLES_RESUME if not pareil(a[c], b[c])}
    attendus = {"cout_installation_eur": {FIXES, RESULTAT, SEUIL, RETOUR}, "amortissement_ans": {FIXES, RESULTAT, SEUIL},
                "couts_fixes_annuels_eur": {FIXES, RESULTAT, SEUIL, RETOUR}}[champ]
    assert dependants == attendus
    res = L.optimiser_ligne(dict(ligne, **{champ: vide}), frus)
    for c in CLES_RESUME:
        if c in dependants:
            assert inconnu(res["resume"][c]), f"{c} chiffré alors que {champ} est inconnu"
        else:
            assert pareil(res["resume"][c], base["resume"][c]), f"{c} ne dépend pas de {champ}"
    pd.testing.assert_frame_equal(res["detail"], base["detail"])
    t = L.comparer_scenarios(dict(ligne, **{champ: vide}), frus).set_index("Poste (€/an)")
    assert inconnu(t.at["TOTAL", "Écart"]) and inconnu(t.at["TOTAL", "Avec la ligne"]) and t.at["TOTAL", "Actuel"] == vaut(-600.0)


@pytest.mark.parametrize("vide", INCONNUS, ids=["None", "nan", "numpy nan", "pd.NA"])
def test_heures_inconnues_pas_de_limite(vide):
    ligne, frus = modele_matrice()
    res = L.optimiser_ligne(dict(ligne, heures_operateur_an=vide), frus)
    controler(dict(ligne, heures_operateur_an=None), frus, res)
    r = res["resume"]
    assert r[CAPACITE] == math.inf and inconnu(r[OCCUPATION]) and r[MU] == 0.0
    assert r[MARGE] == vaut(3357.0) and r[HEURES] == vaut(70.0)
    large = L.optimiser_ligne(dict(ligne, heures_operateur_an=1e9), frus)["resume"]
    assert all(pareil(r[c], large[c]) for c in CLES_RESUME if c not in (CAPACITE, OCCUPATION))


@pytest.mark.parametrize("champ", ["taux_horaire_eur", "cout_traitement_eur_kg"])
def test_taux_horaire_ou_cout_de_traitement_inconnu_rien_n_est_chiffre(champ):
    ligne, frus = modele_matrice()
    ligne[champ] = None
    res = L.optimiser_ligne(ligne, frus)
    controler(ligne, frus, res)
    r, d = res["resume"], res["detail"]
    assert r[INCOMPLETS] == 2 and list(d["Décision"]) == ["incomplet", "incomplet"]
    assert all(champ in m for m in d["Entrées manquantes"])
    for c in (MARGE, RESULTAT, HEURES, TRAITEES, MOYENNE, SEUIL, RETOUR, MU, DETOURNEE, OCCUPATION):
        assert inconnu(r[c]), f"{c} chiffré alors que {champ} est inconnu"
    assert r[MASSE] == vaut(1200.0) and r[FIXES] == vaut(1400.0)          # ce qui n'en dépend pas reste connu
    assert pareil(r[ACTUEL], 600.0 if champ == "taux_horaire_eur" else math.nan)
    for f, fru in frus.items():
        t = options(ligne, fru)
        assert t[[RE, RC]].isna().all().all(), f"{f} : une valeur d'option chiffrée sans {champ}"
        assert t["Heures réemploi"].notna().all() and t["Kg détournés recyclage"].notna().all()     # les heures et les kg n'en dépendent pas
    scen = L.comparer_scenarios(ligne, frus).set_index("Poste (€/an)")
    assert inconnu(scen.at["TOTAL", "Écart"]) and inconnu(scen.at["TOTAL", "Avec la ligne"])


def test_taux_propre_a_un_type_de_fru():
    """Taux de la ligne inconnu : seul le type qui a son propre taux est calculé. Taux du type présent mais inconnu :
    il ne retombe pas sur le taux de la ligne."""
    ligne, frus = _sans_limite()
    frus["FRU-T2"]["taux_horaire_eur"] = 60.0
    res = L.optimiser_ligne(dict(ligne, taux_horaire_eur=None), frus)
    controler(dict(ligne, taux_horaire_eur=None), frus, res)
    assert res["resume"][INCOMPLETS] == 1 and res["resume"][MARGE] == vaut(157.0)
    frus["FRU-T2"]["taux_horaire_eur"] = None
    res = L.optimiser_ligne(ligne, frus)
    controler(ligne, frus, res)
    d = res["detail"].set_index("Type de FRU")
    assert d.at["FRU-T2", "Décision"] == "incomplet" and d.at["FRU-T2", "Entrées manquantes"] == "taux_horaire_eur"
    assert res["resume"][MARGE] == vaut(3200.0)
    frus["FRU-T2"]["taux_horaire_eur"] = 30.0                              # 12,14 + 6 − 4,5 = 13,64 € par FRU à 30 €/h
    assert L.optimiser_ligne(ligne, frus)["resume"][MARGE] == vaut(3200.0 + 50 * 13.64)


@pytest.mark.parametrize("vide", INCONNUS, ids=["None", "nan", "numpy nan", "pd.NA"])
@pytest.mark.parametrize("champ, manque", [("scrap_an", "scrap_an"), ("taux_horaire_eur", "taux_horaire_eur")])
def test_type_de_fru_incomplet_les_autres_sont_optimises(champ, manque, vide):
    """Le type incomplet est écarté et compté ; le reste du résultat est celui de la ligne sans ce type."""
    ligne, frus = modele_matrice()
    frus["FRU-T1"][champ] = vide
    res = L.optimiser_ligne(ligne, frus)
    oracle = copy.deepcopy(frus)
    oracle["FRU-T1"][champ] = None
    controler(ligne, oracle, res)
    d = res["detail"].set_index("Type de FRU")
    assert d.at["FRU-T1", "Décision"] == "incomplet" and d.at["FRU-T1", "Entrées manquantes"] == manque
    seul = L.optimiser_ligne(ligne, {"FRU-T2": frus["FRU-T2"]})["resume"]
    r = res["resume"]
    assert r[INCOMPLETS] == 1 and r[MARGE] == vaut(157.0) and r[HEURES] == vaut(17.5)
    assert all(pareil(r[c], seul[c]) for c in CLES_RESUME if c not in (INCOMPLETS, MASSE, ACTUEL))
    if champ == "scrap_an":                 # la masse scrapée et le coût actuel ne se calculent plus
        assert inconnu(r[MASSE]) and inconnu(r[ACTUEL])
    else:
        assert r[MASSE] == vaut(1200.0) and r[ACTUEL] == vaut(600.0)


@pytest.mark.parametrize("vide", INCONNUS, ids=["None", "nan", "numpy nan", "pd.NA"])
def test_poids_d_un_fru_inconnu(vide):
    ligne, frus = modele_matrice()
    base = L.optimiser_ligne(ligne, frus)
    frus["FRU-T2"]["poids_fru_kg"] = vide
    res = L.optimiser_ligne(ligne, frus)
    for c in CLES_RESUME:
        assert inconnu(res["resume"][c]) if c in (MASSE, ACTUEL) else pareil(res["resume"][c], base["resume"][c]), c
    pd.testing.assert_frame_equal(res["detail"], base["detail"])
    t = L.comparer_scenarios(ligne, frus)
    assert inconnu(t.attrs["Masse scrapée (kg/an)"]) and inconnu(t.attrs["Part détournée"])
    t = t.set_index("Poste (€/an)")
    assert inconnu(t.at["TOTAL", "Actuel"]) and inconnu(t.at["TOTAL", "Avec la ligne"])
    assert t.at["TOTAL", "Écart"] == vaut(base["resume"][RESULTAT])           # le gain ne dépend pas du poids des FRU


def test_ouvertures_inconnues():
    ligne, frus = _sans_limite()
    # ouverture soignée inconnue : plus de réemploi dans ce type, le tri reste possible avec l'ouverture sommaire
    frus["FRU-T1"]["ouverture_min"] = None
    res = L.optimiser_ligne(ligne, frus)
    controler(ligne, frus, res)
    t = options(ligne, frus["FRU-T1"])
    assert t[RE].isna().all() and (t["Manque réemploi"] == "ouverture_min").all() and t[RC].notna().all()
    assert inconnu(t.attrs["Ouverture soignée (€/FRU)"]) and t.attrs["Ouverture sommaire (€/FRU)"] == vaut(6.0)
    d = res["detail"].set_index("Type de FRU")
    assert d.at["FRU-T1", "1 Réemploi"] == "" and d.at["FRU-T1", "2 Recyclage"] == "P-2" and d.at["FRU-T1", "Marge par FRU (€)"] == vaut(6.5)
    # sans ouverture sommaire saisie, elle retombe sur l'ouverture soignée, inconnue : plus rien n'est calculable
    del frus["FRU-T1"]["ouverture_tri_min"]
    res = L.optimiser_ligne(ligne, frus)
    controler(ligne, frus, res)
    d = res["detail"].set_index("Type de FRU")
    assert d.at["FRU-T1", "Décision"] == "incomplet" and d.at["FRU-T1", "Entrées manquantes"].startswith("aucune option calculable")
    assert "ouverture_min" in d.at["FRU-T1", "Entrées manquantes"] and "ouverture_tri_min" in d.at["FRU-T1", "Entrées manquantes"]
    # ouverture sommaire présente mais inconnue : plus de recyclage, le réemploi reste
    ligne, frus = _sans_limite()
    frus["FRU-T1"]["ouverture_tri_min"] = None
    res = L.optimiser_ligne(ligne, frus)
    controler(ligne, frus, res)
    t = options(ligne, frus["FRU-T1"])
    assert t[RC].isna().all() and (t["Manque recyclage"] == "ouverture_tri_min").all() and t[RE].notna().all()
    d = res["detail"].set_index("Type de FRU")
    assert d.at["FRU-T1", "1 Réemploi"] == "P-1, P-2" and d.at["FRU-T1", "2 Recyclage"] == "" and d.at["FRU-T1", "Marge par FRU (€)"] == vaut(23.0)


OBLIGATOIRES = {            # champ d'une pièce → options qui ne sont plus calculables
    "n_par_fru": ("réemploi", "recyclage"), "extraction_min": ("réemploi",), "test_min": ("réemploi",), "p_reutilisable": ("réemploi",),
    "valeur_eur": ("réemploi",), "tri_min": ("recyclage",), "poids_kg": ("recyclage",), "prix_recycleur_eur_kg": ("recyclage",)}
FACULTATIFS = {"transport_eur": "transport", "delai_semaines": "délai évité", "valeur_semaine_eur": "délai évité"}
COLONNE = {"réemploi": (RE, "Heures réemploi", "Manque réemploi"), "recyclage": (RC, "Heures recyclage", "Manque recyclage")}


@pytest.mark.parametrize("vide", INCONNUS, ids=["None", "nan", "numpy nan", "pd.NA"])
@pytest.mark.parametrize("piece", ["P-1", "P-2"])
@pytest.mark.parametrize("champ", list(OBLIGATOIRES))
def test_champ_obligatoire_d_une_piece_inconnu(champ, piece, vide):
    """L'option qui a besoin du champ n'est plus chiffrée ni choisie ; l'autre option, les autres pièces et l'autre type
    de FRU sont calculés comme avant ; le plan reste le meilleur parmi ce qui est calculable."""
    for ligne, frus in (modele_matrice(), _sans_limite()):
        avant = options(ligne, frus["FRU-T1"])
        frus["FRU-T1"]["pieces"][piece][champ] = vide
        apres = options(ligne, frus["FRU-T1"])
        for option, (valeur, heures, manque) in COLONNE.items():
            if option in OBLIGATOIRES[champ]:
                assert inconnu(apres.at[piece, valeur]) and inconnu(apres.at[piece, heures]), f"{option} chiffré sans {champ}"
                assert apres.at[piece, manque] == champ
            else:
                assert apres.at[piece, manque] == "" and apres.at[piece, heures] == vaut(avant.at[piece, heures])
        autre = "P-2" if piece == "P-1" else "P-1"
        assert all(pareil(apres.at[autre, c], avant.at[autre, c]) for c in avant.columns), "l'autre pièce ne doit pas changer"
        if champ == "tri_min":              # le temps de tri ne sert qu'au recyclage : la valeur du réemploi ne bouge pas
            assert apres.at[piece, RE] == vaut(avant.at[piece, RE])
        oracle = copy.deepcopy(frus)
        oracle["FRU-T1"]["pieces"][piece][champ] = None
        res = L.optimiser_ligne(ligne, frus)
        controler(ligne, oracle, res)
        d = res["detail"]
        for option in OBLIGATOIRES[champ]:
            colonne = "1 Réemploi" if option == "réemploi" else "2 Recyclage"
            assert not any(piece in ensemble(x) for x in d.loc[d["Type de FRU"].eq("FRU-T1"), colonne]), f"{piece} en {option} sans {champ}"
        if math.isinf(capacite(ligne)):     # sans limite d'heures, l'autre type de FRU ne voit rien
            t2 = d[d["Type de FRU"].eq("FRU-T2")].iloc[0]
            assert t2["FRU traitées / an"] == vaut(50.0) and t2["Marge variable / an (€)"] == vaut(157.0)


@pytest.mark.parametrize("vide", INCONNUS, ids=["None", "nan", "numpy nan", "pd.NA"])
@pytest.mark.parametrize("champ", list(FACULTATIFS))
def test_champ_facultatif_d_une_piece_inconnu(champ, vide):
    """Transport, délai, valeur d'une semaine : non comptés s'ils ne sont pas saisis, et la table des options le dit.
    Le résultat est celui du même modèle où l'entrée vaut zéro : rien d'autre n'en sort."""
    ligne, frus = modele_matrice()
    zero = copy.deepcopy(frus)
    zero["FRU-T1"]["pieces"]["P-1"][champ] = 0.0
    frus["FRU-T1"]["pieces"]["P-1"][champ] = vide
    t = options(ligne, frus["FRU-T1"])
    assert t.at["P-1", "Non compté faute de donnée"] == FACULTATIFS[champ] and t.at["P-1", "Manque réemploi"] == ""
    assert t.at["P-2", "Non compté faute de donnée"] == ""
    assert t.at["P-1", RE] == vaut(options(ligne, zero["FRU-T1"]).at["P-1", RE]) and t.at["P-1", RE] != vaut(31.5)
    res, ref = L.optimiser_ligne(ligne, frus), L.optimiser_ligne(ligne, zero)
    assert all(pareil(res["resume"][c], ref["resume"][c]) for c in CLES_RESUME)
    oracle = copy.deepcopy(frus)
    oracle["FRU-T1"]["pieces"]["P-1"][champ] = None
    controler(ligne, oracle, res)


def test_piece_sans_aucune_donnee_et_type_sans_piece():
    ligne, frus = _sans_limite()
    frus["FRU-T1"]["pieces"]["P-9"] = {}
    frus["FRU-T1"]["pieces"]["P-10"] = None
    res = L.optimiser_ligne(ligne, frus)
    assert res["resume"][MARGE] == vaut(3357.0) and res["resume"][INCOMPLETS] == 0
    t = options(ligne, frus["FRU-T1"])
    assert inconnu(t.at["P-9", RE]) and inconnu(t.at["P-10", RC]) and t.at["P-9", "Meilleure option seule"] == "Jeté"
    for vide in ({}, None):
        frus["FRU-T3"] = {"scrap_an": 5.0, "poids_fru_kg": 2.0, "ouverture_min": 5.0, "pieces": vide}
        res = L.optimiser_ligne(ligne, frus)
        d = res["detail"].set_index("Type de FRU")
        assert d.at["FRU-T3", "Décision"] == "incomplet" and d.at["FRU-T3", "Entrées manquantes"].startswith("aucune option calculable")
        assert res["resume"][MARGE] == vaut(3357.0) and res["resume"][INCOMPLETS] == 1 and res["resume"][MASSE] == vaut(1210.0)
    frus["FRU-T4"] = None
    res = L.optimiser_ligne(ligne, frus)
    assert res["resume"][INCOMPLETS] == 2 and res["resume"][MARGE] == vaut(3357.0) and inconnu(res["resume"][MASSE])


def test_bilan_cas_limites():
    ligne, frus = modele_matrice()
    # aucun type de FRU
    for vide in ({}, None):
        res = L.optimiser_ligne(ligne, vide)
        assert list(res["detail"].columns) == COLONNES_DETAIL and len(res["detail"]) == 0
        r = res["resume"]
        assert list(r) == CLES_RESUME and r[INCOMPLETS] == 0 and r[FIXES] == vaut(1400.0) and r[CAPACITE] == 60.0
        assert all(inconnu(r[c]) for c in CLES_RESUME if c not in (INCOMPLETS, FIXES, CAPACITE))
    # ligne sans aucun paramètre : tout est inconnu, rien ne plante
    for vide in ({}, None):
        r = L.optimiser_ligne(vide, frus)["resume"]
        assert r[INCOMPLETS] == 2 and r[CAPACITE] == math.inf and r[MASSE] == vaut(1200.0)
        assert all(inconnu(r[c]) for c in CLES_RESUME if c not in (INCOMPLETS, CAPACITE, MASSE))
    # aucune heure, heures négatives : rien n'est traité, la marge est nulle (connue), le taux d'occupation n'a pas de sens
    for heures in (0.0, -50.0):
        res = L.optimiser_ligne(dict(ligne, heures_operateur_an=heures), frus)
        controler(dict(ligne, heures_operateur_an=heures), frus, res)
        r = res["resume"]
        assert r[CAPACITE] == 0.0 and r[MARGE] == 0.0 and r[HEURES] == 0.0 and r[TRAITEES] == 0.0 and inconnu(r[OCCUPATION])
        assert inconnu(r[MOYENNE]) and inconnu(r[SEUIL]) and inconnu(r[RETOUR]) and r[RESULTAT] == vaut(-1400.0)
        assert r[MU] == vaut(32.0 / 0.525, rel=1e-9)                       # la première heure irait à FRU-T1
        assert set(res["detail"]["Décision"]) == {"jeter telle quelle"}
    # aucun FRU scrapé : type calculé, rien à traiter
    frus0 = copy.deepcopy(frus)
    frus0["FRU-T1"]["scrap_an"] = 0.0
    res = L.optimiser_ligne(ligne, frus0)
    controler(ligne, frus0, res)
    assert res["detail"].set_index("Type de FRU").at["FRU-T1", "Décision"] == "jeter telle quelle" and res["resume"][MASSE] == vaut(200.0)
    # nombre de FRU négatif : erreur de saisie, type écarté, masse inconnue
    frus0["FRU-T1"]["scrap_an"] = -3.0
    res = L.optimiser_ligne(ligne, frus0)
    controler(ligne, frus0, res)
    assert res["detail"].set_index("Type de FRU").at["FRU-T1", "Entrées manquantes"] == "scrap_an négatif" and inconnu(res["resume"][MASSE])
    # rien n'est rentable : marge nulle et connue, pas de seuil ni de retour sur investissement
    cher = L.optimiser_ligne(dict(ligne, taux_horaire_eur=1000.0), frus)["resume"]
    assert cher[MARGE] == 0.0 and cher[TRAITEES] == 0.0 and cher[RESULTAT] == vaut(-1400.0) and inconnu(cher[SEUIL]) and inconnu(cher[RETOUR])


def test_couts_fixes_annualises():
    """Installation / durée d'amortissement + fixes annuels ; une durée de moins d'un an compte pour un an."""
    f = L._couts_fixes
    assert f(ligne_main()) == vaut(1400.0)
    assert f(ligne_main(amortissement_ans=0.5)) == vaut(5400.0) and f(ligne_main(amortissement_ans=0.0)) == vaut(5400.0)
    assert f(ligne_main(amortissement_ans=1.0)) == vaut(5400.0) and f(ligne_main(amortissement_ans=10.0)) == vaut(900.0)
    assert f(ligne_main(cout_installation_eur=0.0, amortissement_ans=None)) == vaut(400.0)       # sans investissement, la durée ne sert pas
    assert inconnu(f(ligne_main(amortissement_ans=None))) and inconnu(f(ligne_main(cout_installation_eur=None)))
    assert inconnu(f(ligne_main(couts_fixes_annuels_eur=None))) and inconnu(f({}))
    ligne, frus = modele_matrice()
    r = L.optimiser_ligne(dict(ligne, cout_installation_eur=0.0, amortissement_ans=None), frus)["resume"]
    assert r[FIXES] == vaut(400.0) and r[RETOUR] == 0.0


def test_fonctions_d_inventaire_des_manques():
    fru = fru_main({"P-1": piece_main(valeur_eur=None, test_min=None), "P-2": piece_main(poids_kg=None)})
    assert L.options_disponibles(fru) == {"P-1": {"réemploi": ["test_min", "valeur_eur"], "recyclage": []},
                                          "P-2": {"réemploi": [], "recyclage": ["poids_kg"]}}
    assert L.manques(fru, 60.0) == [] and L.manques(fru, None) == ["taux_horaire_eur"]
    assert L.manques(dict(fru, scrap_an=None, _c_trait=None), 60.0) == ["scrap_an", "cout_traitement_eur_kg"]
    assert L.manques(dict(fru, _c_trait=0.0), 60.0) == []
    rien = fru_main({"P-1": piece_main(valeur_eur=None, tri_min=None)})
    assert L.manques(rien, 60.0) == ["aucune option calculable : P-1 réemploi[valeur_eur] recyclage[tri_min]"]
    assert L._inconnu(None) and L._inconnu(float("nan")) and L._inconnu(np.float32("nan")) and L._inconnu(pd.NA) and L._inconnu(pd.NaT)
    assert not any(L._inconnu(v) for v in (0, 0.0, "", "x", (1.0, 2.0), [None, None], False, np.int64(3)))


# =========================================================================== 5. robustesse
# --------------------------------------------------------------------------- plages
def test_tirer_plages_degenerees():
    rng = np.random.default_rng(0)
    assert L._tirer((5.0, 5.0), rng) == 5.0 and L._tirer((5.0, 5.0, 5.0), rng) == 5.0 and L._tirer((5.0, 9.0, 5.0), rng) == 5.0
    for plage, bas, haut in (((8.0, 2.0), 2.0, 8.0),                    # bornes inversées
                             ((1.0, 50.0, 3.0), 1.0, 3.0),              # mode au-dessus de la borne haute
                             ((1.0, -50.0, 3.0), 1.0, 3.0),             # mode au-dessous de la borne basse
                             ((3.0, 2.0, 1.0), 1.0, 3.0),               # triangle à l'envers
                             ([2.0, 4.0], 2.0, 4.0), ([2.0, 3.0, 4.0], 2.0, 4.0)):      # listes : modèle relu d'un fichier JSON
        tirages = np.array([L._tirer(plage, rng) for _ in range(300)])
        assert tirages.min() >= bas and tirages.max() <= haut and tirages.std() > 0, plage
        assert all(isinstance(v, float) for v in tirages.tolist())
    haut_seulement = np.array([L._tirer((1.0, 50.0, 3.0), rng) for _ in range(2000)])
    assert haut_seulement.mean() == pytest.approx((1 + 3 + 3) / 3, abs=0.05)         # mode ramené à la borne haute
    assert np.mean([L._tirer((2.0, 8.0), rng) for _ in range(4000)]) == pytest.approx(5.0, abs=0.1)
    assert np.mean([L._tirer((0.0, 3.0, 12.0), rng) for _ in range(4000)]) == pytest.approx(5.0, abs=0.2)
    # borne ou mode inconnu : pas de tirage, la valeur centrale si elle existe, sinon inconnu
    assert L._tirer((None, 4.0), rng) is None and L._tirer((2.0, float("nan")), rng) is None and L._tirer((1.0, None, 3.0), rng) is None
    assert L._tirer((None, 5.0, None), rng) == 5.0 and L._tirer((None, 5.0, 9.0), rng) == 5.0
    assert L._tirer((1.0, 2.0, 3.0, 4.0), rng) is None and L._tirer((), rng) is None and L._tirer((7.0,), rng) is None
    # le reste est rendu tel quel, les dictionnaires sont parcourus
    assert L._tirer(None, rng) is None and L._tirer(3.5, rng) == 3.5 and L._tirer("Atelier", rng) == "Atelier"
    d = L._tirer({"a": (1.0, 1.0), "b": {"c": (4.0, 2.0, 4.0), "d": "texte", "e": None}}, rng)
    assert d["a"] == 1.0 and d["b"]["d"] == "texte" and d["b"]["e"] is None and 2.0 <= d["b"]["c"] <= 4.0


def test_milieu_des_plages():
    m = L._milieu
    assert m((2.0, 4.0)) == 3.0 and m((4.0, 2.0)) == 3.0 and m((1.0, 2.0, 9.0)) == 2.0 and m([1.0, 2.0, 9.0]) == 2.0
    assert m((1.0, 50.0, 3.0)) == 3.0 and m((1.0, -50.0, 3.0)) == 1.0 and m((5.0, 5.0)) == 5.0
    assert m((None, 4.0)) is None and m((1.0, None, 3.0)) is None and m((None, 5.0, None)) == 5.0 and m((1.0, 2.0, 3.0, 4.0)) is None
    assert m(None) is None and m(7) == 7 and m("x") == "x" and m({"a": (0.0, 1.0), "b": {"c": None}}) == {"a": 0.5, "b": {"c": None}}


def test_meme_graine_memes_tirages():
    ligne, frus = modele_plages()
    modele = {"ligne": ligne, "frus": frus}
    a, b = L._tirer(modele, np.random.default_rng(3)), L._tirer(modele, np.random.default_rng(3))
    assert a == b and a != L._tirer(modele, np.random.default_rng(4))
    assert modele == {"ligne": modele_plages()[0], "frus": modele_plages()[1]}, "un tirage ne modifie pas le modèle"


# --------------------------------------------------------------------------- Monte-Carlo
def test_monte_carlo_reproductible():
    ligne, frus = modele_plages()
    a = L.monte_carlo_ligne(ligne, frus, n=40, rng=np.random.default_rng(11))
    b = L.monte_carlo_ligne(ligne, frus, n=40, rng=np.random.default_rng(11))
    c = L.monte_carlo_ligne(ligne, frus, n=40, rng=11)                    # une graine entière vaut le générateur de cette graine
    autre = L.monte_carlo_ligne(ligne, frus, n=40, rng=np.random.default_rng(12))
    pd.testing.assert_frame_equal(a["tirages"], b["tirages"])
    pd.testing.assert_frame_equal(a["tirages"], c["tirages"])
    assert a["P(ligne rentable)"] == b["P(ligne rentable)"] and a["Résultat P5 / médiane / P95 (€)"] == b["Résultat P5 / médiane / P95 (€)"]
    assert a["Fréquence de traitement par type de FRU"] == b["Fréquence de traitement par type de FRU"]
    assert not a["tirages"][RESULTAT].equals(autre["tirages"][RESULTAT])
    assert len(a["tirages"]) == 40 and list(a["tirages"].columns) == CLES_RESUME
    x = a["tirages"][RESULTAT]
    assert a["P(ligne rentable)"] == vaut(float((x > 0).mean())) and 0.0 <= a["P(ligne rentable)"] <= 1.0
    p5, mediane, p95 = a["Résultat P5 / médiane / P95 (€)"]
    assert x.min() - 1 <= p5 <= mediane <= p95 <= x.max() + 1 and mediane == vaut(round(float(np.median(x))))
    frequence = a["Fréquence de traitement par type de FRU"]
    assert set(frequence) <= set(frus) and all(0.0 < v <= 1.0 for v in frequence.values()) and frequence["FRU-T1"] > 0.5
    assert x.std() > 0 and (a["tirages"][MARGE] >= 0).all() and (a["tirages"][HEURES] <= 60.0 * (1 + 1e-9)).all()


def test_monte_carlo_sans_plage_tous_les_tirages_sont_le_calcul_central():
    ligne, frus = modele_matrice()
    mc = L.monte_carlo_ligne(ligne, frus, n=5, rng=1)
    centre = L.optimiser_ligne(ligne, frus)["resume"]
    assert all(pareil(v, centre[c]) for c in CLES_RESUME for v in mc["tirages"][c])
    assert mc["P(ligne rentable)"] == 1.0 and mc["Résultat P5 / médiane / P95 (€)"] == (vaut(round(centre[RESULTAT])),) * 3
    perdant = L.monte_carlo_ligne(dict(ligne, couts_fixes_annuels_eur=1e6), frus, n=3, rng=1)
    assert perdant["P(ligne rentable)"] == 0.0


def test_monte_carlo_tirages_dans_les_bornes():
    """Une seule plage, sur la valeur de réemploi de P-1 : chaque marge tirée est entre celles des deux bornes."""
    ligne, frus = _sans_limite()

    def avec_valeur(valeur):
        f = copy.deepcopy(frus)
        f["FRU-T1"]["pieces"]["P-1"]["valeur_eur"] = valeur
        return f
    bas, haut = (L.optimiser_ligne(ligne, avec_valeur(v))["resume"][MARGE] for v in (30.0, 55.0))
    mc = L.monte_carlo_ligne(ligne, avec_valeur((30.0, 40.0, 55.0)), n=60, rng=5)
    assert bas < haut and mc["tirages"][MARGE].between(bas, haut).all() and mc["tirages"][MARGE].nunique() > 50


def test_monte_carlo_quand_tout_est_inconnu():
    _, frus = modele_matrice()
    vide = {k: None for k in ligne_main()}
    for ligne, types in ((vide, frus), (vide, {}), ({}, None), (ligne_main(cout_installation_eur=None), frus)):
        mc = L.monte_carlo_ligne(ligne, types, n=4, rng=0)
        assert inconnu(mc["P(ligne rentable)"]), "aucun résultat calculable : la probabilité est inconnue, pas nulle"
        assert len(mc["Résultat P5 / médiane / P95 (€)"]) == 3 and all(inconnu(v) for v in mc["Résultat P5 / médiane / P95 (€)"])
        assert len(mc["tirages"]) == 4 and mc["tirages"][RESULTAT].isna().all()
    assert mc["Fréquence de traitement par type de FRU"] == {"FRU-T1": 1.0, "FRU-T2": 1.0}     # le plan, lui, reste connu
    aucun = L.monte_carlo_ligne(*modele_matrice(), n=0, rng=0)
    assert inconnu(aucun["P(ligne rentable)"]) and len(aucun["tirages"]) == 0 and aucun["Fréquence de traitement par type de FRU"] == {}


# --------------------------------------------------------------------------- période par période
def flux(lignes) -> pd.DataFrame:
    return pd.DataFrame(lignes, columns=["Semaine", "FRU", "FRU scrapées"])


def modele_periodes() -> tuple:
    """Le cas à une pièce (19,5 € et 0,5 h par FRU) avec 520 h par an : 10 h, soit 20 FRU au plus, par semaine."""
    return ligne_main(heures_operateur_an=520.0), {"FRU-T1": fru_main()}


def test_periode_par_periode_calcule_a_la_main():
    """Quatre semaines : 0, 10, 30 et 0 FRU. La troisième n'en traite que 20 ; les dix autres sont perdues (pas de stock)."""
    ligne, frus = modele_periodes()
    f = flux([("2026-S01", "FRU-T1", 0), ("2026-S02", "FRU-T1", 10), ("2026-S03", "FRU-T1", 30), ("2026-S04", "FRU-T1", 0),
              ("2026-S02", "FRU-HORS-MODELE", 500), ("2026-S03", "FRU-T1", 0)])
    t = L.resultat_par_periode(ligne, frus, f)
    assert list(t.columns) == L.COLONNES_PERIODE and list(t["Semaine"]) == ["2026-S01", "2026-S02", "2026-S03", "2026-S04"]
    fixe = 1400.0 / 52
    assert list(t["FRU arrivées"]) == [0.0, 10.0, 30.0, 0.0] and list(t["FRU traitées"]) == [vaut(0.0), vaut(10.0), vaut(20.0), vaut(0.0)]
    assert list(t["Heures utilisées"]) == [vaut(0.0), vaut(5.0), vaut(10.0), vaut(0.0)] and (t["Capacité (h)"] == 10.0).all()
    assert list(t["Marge variable (€)"]) == [vaut(0.0), vaut(195.0), vaut(390.0), vaut(0.0)]
    assert list(t["Coût fixe (€)"]) == [vaut(fixe)] * 4
    assert list(t["Résultat (€)"]) == [vaut(-fixe), vaut(195.0 - fixe), vaut(390.0 - fixe), vaut(-fixe)]
    assert list(t["Valeur d'une heure en plus (€)"]) == [vaut(0.0), vaut(0.0), vaut(39.0, rel=1e-9), vaut(0.0)]
    assert list(t["Résultat cumulé (€)"]) == [vaut(v) for v in np.cumsum([-fixe, 195.0 - fixe, 390.0 - fixe, -fixe])]
    a = t.attrs
    assert a["Périodes"] == 4 and a["Périodes en perte"] == 2
    assert a["Résultat annualisé, période par période (€)"] == vaut(585.0 / 4 * 52 - 1400.0)          # 6 205 €
    assert a["Résultat du modèle annuel au flux moyen (€)"] == vaut(520 * 19.5 - 1400.0)              # 10 FRU par semaine : 8 740 €
    # coût de la variabilité = annuel au flux moyen − annualisé période par période = 10 FRU perdues × 19,5 € × 52 / 4
    assert a["Coût de la variabilité du flux (€/an)"] == vaut(2535.0)
    assert a["Coût de la variabilité du flux (€/an)"] == vaut(a["Résultat du modèle annuel au flux moyen (€)"] - a["Résultat annualisé, période par période (€)"])


def test_periode_par_periode_mois_et_semaines_datees():
    ligne, frus = modele_periodes()
    mois = [pd.Timestamp(2026, m, 1) for m in (3, 1, 2)]
    t = L.resultat_par_periode(ligne, frus, flux([(mois[0], "FRU-T1", 100), (mois[1], "FRU-T1", 20), (mois[2], "FRU-T1", 0)]), periodes_par_an=12)
    assert list(t["Semaine"]) == sorted(mois)
    assert list(t["Capacité (h)"]) == [vaut(520.0 / 12)] * 3 and list(t["Coût fixe (€)"]) == [vaut(1400.0 / 12)] * 3
    traitees = [20.0, 0.0, 520.0 / 12 / 0.5]
    assert list(t["FRU traitées"]) == [vaut(v) for v in traitees]
    assert t.attrs["Résultat annualisé, période par période (€)"] == vaut(sum(traitees) * 19.5 / 3 * 12 - 1400.0)
    assert t.attrs["Résultat du modèle annuel au flux moyen (€)"] == vaut(480 * 19.5 - 1400.0)        # 40 FRU par mois, 240 h sur 520
    assert t.attrs["Coût de la variabilité du flux (€/an)"] == vaut((100 - 520.0 / 6) * 19.5 * 4)


def test_periode_par_periode_flux_hors_modele_semaines_incompletes_et_valeurs_manquantes():
    ligne, frus = modele_periodes()
    fixe = 1400.0 / 52
    # un flux dont aucun FRU n'est dans le modèle : des semaines à zéro FRU, où seul le coût fixe tombe
    t = L.resultat_par_periode(ligne, frus, flux([("S1", "FRU-AUTRE", 4), ("S2", "FRU-AUTRE", 9)]))
    assert len(t) == 2 and (t["FRU arrivées"] == 0).all() and (t["Marge variable (€)"] == 0).all() and list(t["Résultat (€)"]) == [vaut(-fixe)] * 2
    assert t.attrs["Résultat du modèle annuel au flux moyen (€)"] == vaut(-1400.0) and t.attrs["Coût de la variabilité du flux (€/an)"] == vaut(0.0)
    assert t.attrs["Périodes en perte"] == 2
    # semaine marquée incomplète : écartée, ce n'est pas une semaine creuse
    f = flux([("S1", "FRU-T1", 10), ("S2", "FRU-T1", 2), ("S3", "FRU-T1", 10)])
    f["Semaine complète"] = [True, False, True]
    t = L.resultat_par_periode(ligne, frus, f)
    assert list(t["Semaine"]) == ["S1", "S3"] and t.attrs["Coût de la variabilité du flux (€/an)"] == vaut(0.0, abs_=1e-6)
    f["Semaine complète"] = ["oui", "non", None]
    assert list(L.resultat_par_periode(ligne, frus, f)["Semaine"]) == ["S1", "S3"]
    # semaine non renseignée : la ligne du flux est ignorée ; nombre écrit en texte : lu
    f = flux([("S1", "FRU-T1", 10), (None, "FRU-T1", 99), ("S2", "FRU-T1", "6"), ("S2", "FRU-T1", 1)])
    t = L.resultat_par_periode(ligne, frus, f)
    assert list(t["Semaine"]) == ["S1", "S2"] and list(t["FRU arrivées"]) == [10.0, 7.0]
    # nombre de FRU inconnu pour un type du modèle : la semaine est écartée, un comptage manquant n'est pas un zéro
    f = flux([("S1", "FRU-T1", 10), ("S2", "FRU-T1", None), ("S2", "FRU-T1", 6), ("S3", "FRU-T1", "illisible"), ("S4", "FRU-T1", 10),
              ("S4", "FRU-AUTRE", None)])
    t = L.resultat_par_periode(ligne, frus, f)
    assert list(t["Semaine"]) == ["S1", "S4"] and list(t["FRU arrivées"]) == [10.0, 10.0] and t.attrs["Périodes"] == 2
    assert t.attrs["Coût de la variabilité du flux (€/an)"] == vaut(0.0, abs_=1e-6)
    # flux vide ou absent : table vide aux bonnes colonnes
    for vide in (flux([]), None):
        t = L.resultat_par_periode(ligne, frus, vide)
        assert len(t) == 0 and list(t.columns) == L.COLONNES_PERIODE and not t.attrs
    for mauvais in (0, -4, None, float("nan")):
        with pytest.raises(ValueError, match="periodes_par_an"):
            L.resultat_par_periode(ligne, frus, flux([("S1", "FRU-T1", 1)]), periodes_par_an=mauvais)


def test_periode_par_periode_heures_et_couts_inconnus():
    ligne, frus = modele_periodes()
    f = flux([("S1", "FRU-T1", 10), ("S2", "FRU-T1", 30)])
    # heures inconnues : pas de limite, donc pas de FRU perdue et pas de coût de variabilité
    t = L.resultat_par_periode(dict(ligne, heures_operateur_an=None), frus, f)
    assert list(t["FRU traitées"]) == [vaut(10.0), vaut(30.0)] and t["Capacité (h)"].isna().all() and (t["Valeur d'une heure en plus (€)"] == 0).all()
    assert t.attrs["Coût de la variabilité du flux (€/an)"] == vaut(0.0, abs_=1e-6)
    # aucune heure : rien n'est traité (et non « pas de limite »)
    t = L.resultat_par_periode(dict(ligne, heures_operateur_an=0.0), frus, f)
    assert (t["FRU traitées"] == 0).all() and (t["Capacité (h)"] == 0).all() and (t["Marge variable (€)"] == 0).all()
    assert t.attrs["Résultat annualisé, période par période (€)"] == vaut(-1400.0)
    # coût fixe inconnu : la marge de chaque semaine reste connue, pas le résultat
    t = L.resultat_par_periode(dict(ligne, couts_fixes_annuels_eur=None), frus, f)
    assert list(t["Marge variable (€)"]) == [vaut(195.0), vaut(390.0)]
    assert t["Coût fixe (€)"].isna().all() and t["Résultat (€)"].isna().all() and t["Résultat cumulé (€)"].isna().all()
    assert all(inconnu(t.attrs[c]) for c in ("Résultat annualisé, période par période (€)", "Résultat du modèle annuel au flux moyen (€)",
                                              "Coût de la variabilité du flux (€/an)")) and t.attrs["Périodes en perte"] == 0
    # un type de FRU incomplet (sans temps) arrive mais n'est pas traité ; scrap annuel inconnu : le flux de la semaine le remplace
    frus2 = {"FRU-T1": fru_main(scrap_an=None), "FRU-T9": fru_main({"P-1": piece_main(extraction_min=None, tri_min=None)})}
    t = L.resultat_par_periode(ligne, frus2, flux([("S1", "FRU-T1", 10), ("S1", "FRU-T9", 5)]))
    assert t.at[0, "FRU arrivées"] == 15.0 and t.at[0, "FRU traitées"] == vaut(10.0) and t.at[0, "Marge variable (€)"] == vaut(195.0)


@pytest.mark.parametrize("graine", range(6))
def test_cout_de_la_variabilite_jamais_negatif(graine):
    """La marge optimale est concave en (FRU, heures) : la moyenne des semaines ne peut pas battre la semaine moyenne.
    L'écart est nul si le flux est constant ou si les heures ne manquent jamais."""
    rng = np.random.default_rng(900 + graine)
    ligne, frus = modele_matrice()
    ligne["heures_operateur_an"] = float(rng.uniform(2, 12)) * 13              # 13 périodes par an, 2 à 12 h chacune
    semaines = [f"S{i:02d}" for i in range(8)]
    f = flux([(s, t, float(rng.integers(0, 25))) for s in semaines for t in ("FRU-T1", "FRU-T2", "FRU-AUTRE")])
    t = L.resultat_par_periode(ligne, frus, f, periodes_par_an=13)
    cout = t.attrs["Coût de la variabilité du flux (€/an)"]
    assert cout >= -1e-6 * max(1.0, abs(t.attrs["Résultat du modèle annuel au flux moyen (€)"]))
    assert (t["FRU traitées"] <= t["FRU arrivées"] + 1e-9).all() and (t["Heures utilisées"] <= t["Capacité (h)"] * (1 + 1e-9)).all()
    assert t["Résultat cumulé (€)"].iloc[-1] == vaut(t["Résultat (€)"].sum())
    assert t.attrs["Résultat annualisé, période par période (€)"] == vaut(t["Résultat (€)"].mean() * 13)
    constant = flux([(s, t, 7.0) for s in semaines for t in ("FRU-T1", "FRU-T2")])
    assert L.resultat_par_periode(ligne, frus, constant, periodes_par_an=13).attrs["Coût de la variabilité du flux (€/an)"] == vaut(0.0, abs_=1e-6)
    libre = L.resultat_par_periode(dict(ligne, heures_operateur_an=None), frus, f, periodes_par_an=13)
    assert libre.attrs["Coût de la variabilité du flux (€/an)"] == vaut(0.0, abs_=1e-6)
    if graine == 0:
        assert cout > 1.0, "avec ce flux irrégulier et ces heures comptées, des FRU sont perdues"


# --------------------------------------------------------------------------- actuel contre ligne
def verifier_comparaison(ligne: dict, frus: dict):
    """Identités de « Actuel contre ligne », avec M la marge variable, F les coûts fixes, E le traitement évité
    (coût de traitement × masse détournée, compris dans M) et C le coût actuel de traitement :
        actuel    = −C                       avec la ligne = (−C + E) + (M − E) − F
        écart     = avec la ligne − actuel = E + (M − E) − F = M − F = « Résultat / an (€) »
    et, comme dans le document (§7), coût total avec la ligne = C − Z."""
    r = L.optimiser_ligne(ligne, frus)["resume"]
    t = L.comparer_scenarios(ligne, frus)
    assert list(t.columns) == ["Poste (€/an)", "Actuel", "Avec la ligne", "Écart"] and len(t) == 4 and t["Poste (€/an)"].iloc[-1] == "TOTAL"
    c = L._milieu(ligne.get("cout_traitement_eur_kg"))
    evite = math.nan if inconnu(c) or inconnu(r[DETOURNEE]) else c * r[DETOURNEE]
    lignes = t.set_index("Poste (€/an)").to_dict("index")
    traitement, marge, fixes, total = lignes.values()
    assert pareil(traitement["Actuel"], -r[ACTUEL]) and pareil(traitement["Avec la ligne"], -r[ACTUEL] + evite) and pareil(traitement["Écart"], evite)
    assert marge["Actuel"] == 0.0 and pareil(marge["Avec la ligne"], r[MARGE] - evite) and pareil(marge["Écart"], r[MARGE] - evite)
    assert fixes["Actuel"] == 0.0 and pareil(fixes["Avec la ligne"], -r[FIXES]) and pareil(fixes["Écart"], -r[FIXES])
    assert pareil(total["Actuel"], -r[ACTUEL]) and pareil(total["Avec la ligne"], -r[ACTUEL] + r[RESULTAT], abs_=1e-6)
    assert pareil(total["Écart"], r[RESULTAT], abs_=1e-6), "l'écart total est le résultat annuel du résumé"
    if not inconnu(total["Actuel"]) and not inconnu(total["Écart"]):
        assert total["Avec la ligne"] - total["Actuel"] == vaut(total["Écart"], abs_=1e-6)
    for colonne in ("Actuel", "Avec la ligne", "Écart"):
        somme = sum(l[colonne] for l in (traitement, marge, fixes))
        assert pareil(total[colonne], somme, abs_=1e-6)
    assert pareil(t.attrs["Masse scrapée (kg/an)"], r[MASSE]) and pareil(t.attrs["Masse détournée (kg/an)"], r[DETOURNEE])
    assert pareil(t.attrs["Part détournée"], r[DETOURNEE] / r[MASSE] if r[MASSE] else math.nan)
    return t


def test_actuel_contre_ligne_calcule_a_la_main():
    """Cas à une pièce : coût actuel 1 000 kg × 0,5 = 500 € ; 100 kg détournés, soit 50 € évités ; marge 1 950 € dont ces
    50 € ; coûts fixes 1 400 €. Actuel −500 € ; avec la ligne −450 + 1 900 − 1 400 = 50 € ; écart 550 € = résultat."""
    t = verifier_comparaison(ligne_main(), {"FRU-T1": fru_main()})
    assert t.attrs["Part détournée"] == vaut(0.1) and t.attrs["Masse scrapée (kg/an)"] == vaut(1000.0) and t.attrs["Masse détournée (kg/an)"] == vaut(100.0)
    assert list(t["Actuel"]) == [vaut(-500.0), 0.0, 0.0, vaut(-500.0)]
    assert list(t["Avec la ligne"]) == [vaut(-450.0), vaut(1900.0), vaut(-1400.0), vaut(50.0)]
    assert list(t["Écart"]) == [vaut(50.0), vaut(1900.0), vaut(-1400.0), vaut(550.0)]


def test_actuel_contre_ligne_identites():
    verifier_comparaison(*modele_matrice())
    verifier_comparaison(*modele_plages())
    verifier_comparaison(*modele_deux_types())
    ligne, frus = modele_matrice()
    for remplace in ({"cout_traitement_eur_kg": -0.3}, {"cout_traitement_eur_kg": 0.0}, {"cout_traitement_eur_kg": None},
                     {"taux_horaire_eur": None}, {"cout_installation_eur": None}, {"heures_operateur_an": 0.0}, {"heures_operateur_an": None}):
        verifier_comparaison(dict(ligne, **remplace), frus)
    verifier_comparaison(ligne, {})
    verifier_comparaison(ligne, {"FRU-T1": dict(frus["FRU-T1"], poids_fru_kg=None), "FRU-T2": frus["FRU-T2"]})
    rng = np.random.default_rng(31)
    for _ in range(25):
        ligne, frus = ligne_aleatoire(rng, types=(2, 4), pieces=(1, 3))
        ligne["heures_operateur_an"] = capacite_aleatoire(rng, ligne, frus)
        verifier_comparaison(ligne, frus)


# --------------------------------------------------------------------------- probabilités tirées de la consommation
def test_p_defaut_depuis_conso():
    p = L.p_defaut_depuis_conso
    assert p(10, 100) == vaut(0.1) and p(10, 100, 2) == vaut(0.05) and p(10, 100, 1, 0.5) == vaut(0.05) and p(0, 100) == 0.0
    assert p(500, 100) == 1.0 and p(-5, 100) == 0.0                           # borné entre 0 et 1
    assert p(10, 100, 1, 1.5) == 0.0 and p(10, 100, 1, -2.0) == vaut(0.1)      # part préventive ramenée entre 0 et 1
    for conso, fru, n, part in ((None, 100, 1, 0.0), (10, None, 1, 0.0), (10, 100, None, 0.0), (10, 100, 1, None), (float("nan"), 100, 1, 0.0),
                                (10, 0, 1, 0.0), (10, -3, 1, 0.0), (10, 100, 0, 0.0), (10, 100, -1, 0.0), (pd.NA, 100, 1, 0.0)):
        assert inconnu(p(conso, fru, n, part)), (conso, fru, n, part)
    rng = np.random.default_rng(8)
    for _ in range(300):
        conso, fru, n, part = rng.uniform(0, 400), rng.uniform(1, 300), float(rng.integers(1, 6)), rng.uniform(0, 1)
        v = p(conso, fru, n, part)
        assert isinstance(v, float) and 0.0 <= v <= 1.0
        assert p(conso * 1.5, fru, n, part) >= v >= p(conso * 0.5, fru, n, part)           # croît avec la consommation
        assert p(conso, fru * 2, n, part) <= v and p(conso, fru, n + 1, part) <= v           # décroît avec les réparations et le nombre par FRU
        assert p(conso, fru, n, min(part + 0.2, 1.0)) <= v                                   # et avec la part préventive


def test_p_reutilisable():
    q = L.p_reutilisable
    assert q(0.1) == vaut(0.9) and q(0.1, 2.0) == vaut(0.8) and q(0.1, 2.0, 0.1) == vaut(0.72) and q(0.1, 2.0, 0.1, 0.5) == vaut(0.36)
    assert q(0.0) == 1.0 and q(1.0) == 0.0 and q(0.6, 3.0) == 0.0 and q(-0.5) == 1.0                # chaque facteur borné entre 0 et 1
    assert q(0.1, 1.0, 2.0) == 0.0 and q(0.1, 1.0, -1.0) == vaut(0.9) and q(0.1, 1.0, 0.0, 7.0) == vaut(0.9) and q(0.1, 1.0, 0.0, -1.0) == 0.0
    for args in ((None,), (float("nan"),), (float("inf"),), (0.1, None), (0.1, 1.0, None), (0.1, 1.0, 0.0, None), (pd.NA,), (0.1, float("nan"))):
        assert inconnu(q(*args)), args
    assert inconnu(q(L.p_defaut_depuis_conso(10, None)))                       # l'inconnu se propage d'une fonction à l'autre
    rng = np.random.default_rng(9)
    for _ in range(300):
        d, f, casse, rendement = rng.uniform(-0.2, 1.2), rng.uniform(0, 4), rng.uniform(-0.2, 1.2), rng.uniform(-0.2, 1.2)
        v = q(d, f, casse, rendement)
        assert isinstance(v, float) and 0.0 <= v <= 1.0
        assert q(d + 0.1, f, casse, rendement) <= v and q(max(d, 0.0), f + 0.5, casse, rendement) <= q(max(d, 0.0), f, casse, rendement)    # décroît avec le défaut et le facteur scrap
        assert q(d, f, casse + 0.1, rendement) <= v and q(d, f, casse, rendement + 0.1) >= v              # décroît avec la casse, croît avec le rendement


# --------------------------------------------------------------------------- plus de 8 pièces
def fru_nombreuses_pieces(valeurs: dict) -> dict:
    """Un type de FRU sans temps d'ouverture dont chaque pièce, réemployée, rapporte net la valeur donnée (en 0,1 h)."""
    pieces = {p: {"n_par_fru": 1.0, "extraction_min": 6.0, "test_min": 0.0, "p_reutilisable": 1.0, "valeur_eur": v + 6.0} for p, v in valeurs.items()}
    return {"scrap_an": 10.0, "poids_fru_kg": 3.0, "ouverture_min": 0.0, "pieces": pieces}


def test_au_dela_de_huit_pieces_toutes_sont_examinees_et_le_plan_est_l_optimum():
    """Dix pièces : aucune n'est écartée. Le plan est l'optimum du document, heures illimitées ou non."""
    assert L.MAX_PIECES_ENUM == 8
    ligne = ligne_main(cout_traitement_eur_kg=0.0)
    valeurs = {f"P{i:02d}": float(v) for i, v in enumerate([50, 10, 90, 30, 70, 20, 100, 40, 80, 60], start=1)}      # dix pièces, 10 à 100 €
    frus = {"FRU-GROS": fru_nombreuses_pieces(valeurs), "FRU-T1": fru_main()}
    res = L.optimiser_ligne(ligne, frus)
    d = res["detail"].set_index("Type de FRU")
    assert d.at["FRU-GROS", "Pièces non examinées"] == "" and d.at["FRU-T1", "Pièces non examinées"] == ""
    assert ensemble(d.at["FRU-GROS", "1 Réemploi"]) == frozenset(valeurs)
    assert d.at["FRU-GROS", "Marge par FRU (€)"] == vaut(550.0) and d.at["FRU-GROS", "Heures par FRU"] == vaut(1.0)
    assert res["resume"][MARGE] == vaut(5500.0 + 100 * (31.0 - 12.0))
    for heures in (None, 12.0, 3.0, 0.5):
        r = controler(dict(ligne, heures_operateur_an=heures), frus)
        assert heures is None or r["heures"] <= heures * (1 + 1e-9)
    # heures comptées : les pièces les moins rentables à l'heure sont laissées, les autres gardées (toutes prennent 0,1 h)
    d3 = L.optimiser_ligne(dict(ligne, heures_operateur_an=3.0), {"FRU-GROS": frus["FRU-GROS"]})["detail"]
    assert all(e == "" for e in d3["Pièces non examinées"])
    assert d3["Heures / an"].sum() == vaut(3.0)
    o = L.Options(dict(frus["FRU-GROS"], _c_trait=0.0), 60.0)
    assert o.separable and o.noms == list(valeurs) and o.noms_ignores == [] and o.ignorees == 0 and o.M is None
    # l'énumération demandée explicitement garde les huit pièces les plus rentables et nomme les deux autres
    e = L.Options(dict(frus["FRU-GROS"], _c_trait=0.0), 60.0, separable=False)
    assert not e.separable and e.noms_ignores == ["P02", "P06"] and e.ignorees == 2 and len(e.noms) == 8 and len(e.M) == 3 ** 8


def test_pieces_sans_option_calculable_ne_comptent_pas_dans_le_seuil():
    """Onze pièces dont trois sans donnée : huit calculables, donc énumération ; rien n'est signalé et le plan est
    l'optimum. Une neuvième pièce calculable, perdante seule, fait passer à la méthode sans énumération : même marge."""
    ligne = ligne_main(cout_traitement_eur_kg=0.0)
    valeurs = {f"P{i:02d}": 10.0 * i for i in range(1, 9)}
    fru = fru_nombreuses_pieces(valeurs)
    pieces = {"U1": {}, **{p: fru["pieces"][p] for p in list(valeurs)[:4]}, "U2": {"n_par_fru": 1.0}, **{p: fru["pieces"][p] for p in list(valeurs)[4:]}, "U3": None}
    assert not L.Options(dict(fru, pieces=pieces, _c_trait=0.0), 60.0).separable
    res = L.optimiser_ligne(ligne, {"F": dict(fru, pieces=pieces)})
    d = res["detail"].iloc[0]
    assert d["Pièces non examinées"] == "" and ensemble(d["1 Réemploi"]) == frozenset(valeurs) and d["Marge par FRU (€)"] == vaut(360.0)
    perdante = dict(pieces, N1={"n_par_fru": 1.0, "extraction_min": 6.0, "test_min": 0.0, "p_reutilisable": 1.0, "valeur_eur": 1.0})    # −5 € seule
    assert L.Options(dict(fru, pieces=perdante, _c_trait=0.0), 60.0).separable
    d = L.optimiser_ligne(ligne, {"F": dict(fru, pieces=perdante)})["detail"].iloc[0]
    assert d["Pièces non examinées"] == "" and ensemble(d["1 Réemploi"]) == frozenset(valeurs) and d["Marge par FRU (€)"] == vaut(360.0)
    controler(ligne, {"F": dict(fru, pieces={p: e for p, e in perdante.items() if e is not None})})     # la référence des tests ne lit pas une pièce vide


@pytest.mark.parametrize("graine", range(6))
def test_methode_sans_enumeration_egale_a_l_enumeration(graine):
    """Proposition 1 du cadre formel : pour tout prix de l'heure, le meilleur plan trouvé pièce par pièce vaut celui de
    l'énumération. Les cas tirés comprennent des options non calculables, un coût de traitement négatif et une
    ouverture sommaire plus longue que l'ouverture soignée (l'hypothèse d'emboîtement du document n'est pas requise)."""
    rng = np.random.default_rng(700 + graine)
    inverses = 0
    for essai in range(250):
        ligne, frus = ligne_aleatoire(rng, types=(1, 2), pieces=(1, 7))
        for f, d in frus.items():
            if rng.random() < 0.3 and d.get("ouverture_min") is not None:
                d["ouverture_tri_min"] = d["ouverture_min"] + float(rng.uniform(1, 30))
                inverses += 1
            taux = ligne["taux_horaire_eur"]
            avec = dict(d, _c_trait=ligne["cout_traitement_eur_kg"])
            a, b = L.Options(avec, taux, separable=False), L.Options(avec, taux, separable=True)
            assert a.ignorees == 0
            for mu in (0.0, 1.0, 17.0, 60.0, 400.0, float(rng.uniform(0, 300))):
                ea, ha, ma, ka = a.meilleur(mu)
                eb, hb, mb, kb = b.meilleur(mu)
                va, vb = ma - mu * ha, mb - mu * hb
                assert abs(va - vb) <= 1e-9 * max(1.0, abs(va)), f"essai {essai}, {f}, prix de l'heure {mu} : énumération {va}, sans énumération {vb}"
                plans = plans_document(ligne, d)                # le plan rendu existe dans le document, avec ces heures et cette marge
                cle = (frozenset(p for p, o in eb if o == "réemploi"), frozenset(p for p, o in eb if o == "recyclage"))
                if eb:
                    h, g, k = plans[cle]
                    assert hb == vaut(h) and mb == vaut(g) and kb == vaut(k)
    assert inverses >= 20


@pytest.mark.parametrize("graine", range(4))
def test_gros_types_optimum_du_document_et_du_solveur_exact(graine):
    """Types de 9 à 10 pièces (méthode sans énumération) : plan réalisable, marge égale à la borne duale du document,
    et égale à l'optimum du solveur exact quand scipy est installé."""
    rng = np.random.default_rng(900 + graine)
    try:
        from scipy.optimize import linprog
    except ImportError:
        linprog = None
    for essai in range(3):
        ligne, frus = ligne_aleatoire(rng, types=(1, 2), pieces=(9, 10))
        ligne["heures_operateur_an"] = capacite_aleatoire(rng, ligne, frus)
        res = L.optimiser_ligne(ligne, frus)
        assert all(e in ("", None) or (isinstance(e, float) and math.isnan(e)) for e in res["detail"]["Pièces non examinées"])
        controler(ligne, frus, res)
        if linprog is not None:
            exact = optimum_solveur_exact(linprog, ligne, frus)
            marge = 0.0 if inconnu(res["resume"][MARGE]) else res["resume"][MARGE]
            assert abs(marge - exact) <= REL * max(1.0, abs(exact)), f"graine {graine}, essai {essai} : marge {marge}, optimum exact {exact}"


# =========================================================================== 6. interface et compatibilité
def test_interface_stable():
    """Noms lus par les notebooks, les figures et l'outil des décideurs : on peut en ajouter, pas en retirer."""
    res = L.optimiser_ligne(*modele_matrice())
    assert set(CLES_RESUME) <= set(res["resume"]) and set(COLONNES_DETAIL) <= set(res["detail"].columns) == set(L.COLONNES_DETAIL)
    t = L.valeurs_options(fru_main(), 60.0)
    assert {"Pièce", RE, RC, "3 Jeté (€/FRU)", "Heures réemploi", "Heures recyclage", "Kg détournés réemploi", "Kg détournés recyclage",
            "Manque réemploi", "Manque recyclage", "Non compté faute de donnée", "Meilleure option seule"} <= set(t.columns)
    assert {"Ouverture soignée (€/FRU)", "Ouverture sommaire (€/FRU)"} <= set(t.attrs)
    assert L.OPTIONS == ("réemploi", "recyclage", "jeté")
    for nom in ("p_defaut_depuis_conso", "p_reutilisable", "options_disponibles", "manques", "valeurs_options", "Options", "options_fru",
                "optimiser_ligne", "comparer_scenarios", "monte_carlo_ligne", "point_milieu", "resultat_par_periode", "_milieu", "_tirer", "_bilan"):
        assert callable(getattr(L, nom)), nom
    vide = L.valeurs_options({"pieces": {}}, 60.0)
    assert len(vide) == 0 and "Ouverture soignée (€/FRU)" in vide.attrs


def test_module_lisible_par_python_3_9_et_sans_dependance_en_plus():
    """Le poste de travail a Python 3.9, pandas 1.5 et numpy 1.23 : pas de syntaxe plus récente, et seuls numpy et pandas
    sont importés (ni scipy, ni autre module du dossier)."""
    source = Path(L.__file__).read_text(encoding="utf-8")
    arbre = ast.parse(source, feature_version=(3, 9))
    importes = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            importes |= {a.name.split(".")[0] for a in noeud.names}
        elif isinstance(noeud, ast.ImportFrom):
            importes.add((noeud.module or ".").split(".")[0])
        elif isinstance(noeud, ast.Call) and getattr(noeud.func, "id", "") == "zip":
            assert not any(k.arg == "strict" for k in noeud.keywords), "zip(strict=...) demande Python 3.10"
    assert importes == {"__future__", "numpy", "pandas"}, importes
    assert "from __future__ import annotations" in source                  # annotations « dict | None » non évaluées sous 3.9
