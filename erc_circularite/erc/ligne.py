"""Économie d'une ligne de tri / démontage des FRU rebutées (et non plus pièce par pièce).

Idées du modèle
---------------
1. La probabilité qu'une pièce soit défectueuse dans une FRU se lit dans la consommation :
       p_défaut ≈ pièces consommées / (FRU réparées × nombre de cette pièce par FRU).
   Une pièce saine extraite d'une FRU rebutée a donc une probabilité (1 − p_défaut) d'être réutilisable,
   corrigée par un facteur « rebut » (une FRU rebutée est souvent plus abîmée qu'une FRU réparée) et
   par la casse au démontage. Ces corrections se calibrent avec l'audit de démontage.
2. Le coût se raisonne au niveau d'une LIGNE :
     - coûts fixes : installation (postes, outillage ESD, banc de test) amortie + coûts fixes annuels ;
     - capacité : heures opérateur disponibles par an (heures en plus du plan de charge) ;
     - coûts variables par FRU : temps d'ouverture propre au type de FRU + temps d'extraction et de test
       de chaque pièce retenue, au taux horaire du type de FRU (opérateur plus ou moins qualifié).
   L'ouverture est payée une fois par FRU quel que soit le nombre de pièces extraites : extraire
   plusieurs pièces d'une même FRU partage ce coût.
3. Décision : pour chaque type de FRU, quelles pièces extraire (ou aucune), sous la contrainte d'heures.
   Résolution exacte du relâché continu par multiplicateur de Lagrange sur les heures ; le multiplicateur
   est la VALEUR NETTE D'UNE HEURE OPÉRATEUR SUPPLÉMENTAIRE (argument direct pour négocier des heures).
4. Incertitude : toute valeur peut être une plage (bas, haut) ou un triangle (bas, mode, haut) ; Monte-Carlo
   sur l'ensemble de la ligne → probabilité que la ligne soit rentable, pas seulement une moyenne.

None = inconnu : le type de FRU concerné est signalé « incomplet » et exclu, jamais calculé avec un zéro.
"""
from __future__ import annotations


import numpy as np
import pandas as pd

RNG = np.random.default_rng(2026)


# ---------------------------------------------------------------------------
# 1. Probabilité de défaut tirée de la consommation
# ---------------------------------------------------------------------------
def p_defaut_depuis_conso(conso_piece, fru_reparees, n_par_fru=1, part_preventive=0.0):
    """Probabilité qu'un exemplaire de la pièce soit défectueux dans une FRU de ce type.

    conso_piece     : pièces consommées sur la période (réparations de ce type de FRU)
    fru_reparees    : FRU de ce type réparées sur la même période
    n_par_fru       : exemplaires de la pièce dans une FRU
    part_preventive : part des remplacements faits par précaution sur une pièce saine
                      (ex. les deux IGBT changés quand un seul a lâché : jusqu'à 0,5)
    """
    if not fru_reparees or not n_par_fru or conso_piece is None:
        return np.nan
    return float(np.clip(conso_piece * (1 - part_preventive) / (fru_reparees * n_par_fru), 0, 1))


def p_reutilisable(p_defaut, facteur_rebut=1.0, casse_demontage=0.0, rendement_test=1.0):
    """P(un exemplaire extrait d'une FRU REBUTÉE est réutilisable)."""
    if p_defaut is None or not np.isfinite(p_defaut):
        return np.nan
    return float(np.clip(1 - p_defaut * facteur_rebut, 0, 1) * (1 - casse_demontage) * rendement_test)


# ---------------------------------------------------------------------------
# 2. Tirage des plages
# ---------------------------------------------------------------------------
def _tirer(x, rng):
    if isinstance(x, tuple):
        return rng.uniform(x[0], x[1]) if len(x) == 2 else rng.triangular(*x)
    if isinstance(x, dict):
        return {k: _tirer(v, rng) for k, v in x.items()}
    return x


def _milieu(x):
    if isinstance(x, tuple):
        return float(np.mean(x[:2])) if len(x) == 2 else float(x[1])
    if isinstance(x, dict):
        return {k: _milieu(v) for k, v in x.items()}
    return x


# ---------------------------------------------------------------------------
# 3. Options par type de FRU
# ---------------------------------------------------------------------------
# Trois options pour chaque pièce de chaque FRU rebutée, valeurs nettes PAR FRU, comparées à l'option 3 :
#   1 « réemploi »  : démontage soigné + test → pièce réutilisée ; un exemplaire qui échoue au test part au recyclage
#                     si le recyclage de cette pièce est renseigné, sinon à la benne (sans coût).
#                     Valeur = n × [p_réut × (valeur + délai évité) + (1 − p_réut) × kg × prix − transport]
#                              − n × (extraction + test) × taux horaire
#   2 « recyclage » : tri de la pièce dans le bon flux → vendue au kg.  Valeur = n × kg × prix − n × tri × taux horaire
#   3 « jeté »      : la pièce reste dans la FRU, qui part chez le recycleur actuel. Valeur 0 (référence).
# Référence = situation actuelle : la FRU entière part dans la benne DEEE du recycleur actuel, au coût de traitement
# ligne["cout_traitement_eur_kg"] (0 si le contrat est gratuit, négatif s'il paie). Chaque kg sorti de cette benne
# par les options 1 et 2 évite ce coût : il est ajouté à leur valeur (« traitement évité »).
# Ouverture de la FRU, payée UNE fois : soignée (ouverture_min) dès qu'une pièce part en réemploi, sinon
# sommaire (ouverture_tri_min, à défaut ouverture_min) dès qu'une pièce part au recyclage. Option 3 partout = pas d'ouverture.
# Délai d'approvisionnement : seul critère supply retenu. Chaque pièce réemployée évite delai_semaines d'attente,
# valorisées à valeur_semaine_eur (= coût d'une semaine d'immobilisation × probabilité de rupture, à fixer).
OPTIONS = ("réemploi", "recyclage", "jeté")
CHAMPS_REEMPLOI = ["n_par_fru", "extraction_min", "test_min", "p_reutilisable", "valeur_eur"]
CHAMPS_RECYCLAGE = ["n_par_fru", "poids_kg", "prix_recycleur_eur_kg", "tri_min"]
MAX_PIECES_ENUM = 8                      # 3^8 = 6 561 combinaisons par type de FRU


def _inconnu(v):
    return v is None or (isinstance(v, float) and np.isnan(v))


def options_disponibles(fru: dict) -> dict:
    """Pour chaque pièce : options calculables et entrées manquantes des autres."""
    out = {}
    ouv_tri = fru.get("ouverture_tri_min", fru.get("ouverture_min"))
    for p, d in fru.get("pieces", {}).items():
        m_re = [c for c in CHAMPS_REEMPLOI if _inconnu(d.get(c))] + (["ouverture_min"] if _inconnu(fru.get("ouverture_min")) else [])
        m_rc = [c for c in CHAMPS_RECYCLAGE if _inconnu(d.get(c))] + (["ouverture_tri_min"] if _inconnu(ouv_tri) else [])
        out[p] = {"réemploi": m_re, "recyclage": m_rc}
    return out


def manques(fru: dict, taux_defaut) -> list[str]:
    m = [c for c in ("rebut_an",) if _inconnu(fru.get(c))]
    if _inconnu(fru.get("taux_horaire_eur", taux_defaut)):
        m.append("taux_horaire_eur")
    dispo = options_disponibles(fru)
    if not any(not v for o in dispo.values() for v in o.values()):
        m.append("aucune option calculable : " + "; ".join(f"{p} réemploi[{', '.join(o['réemploi'])}] recyclage[{', '.join(o['recyclage'])}]"
                                                      for p, o in dispo.items()))
    return m


def valeurs_options(fru: dict, taux_defaut) -> pd.DataFrame:
    """Une ligne par pièce : valeur nette par FRU de chaque option, HORS ouverture (partagée, donnée à part)."""
    taux = fru.get("taux_horaire_eur", taux_defaut)
    c_trait = fru.get("_c_trait") or 0.0
    dispo, lignes = options_disponibles(fru), []
    for p, d in fru.get("pieces", {}).items():
        n = d.get("n_par_fru")
        kg = d.get("poids_kg") if not _inconnu(d.get("poids_kg")) else 0.0     # poids inconnu : aucun traitement évité compté
        kgv = None if dispo[p]["recyclage"] else d["poids_kg"] * d["prix_recycleur_eur_kg"]
        k_re = k_rc = 0.0
        if dispo[p]["réemploi"]:
            v_re, h_re = np.nan, np.nan
        else:
            k_re = n * kg * (d["p_reutilisable"] + (1 - d["p_reutilisable"]) * (kgv is not None))
            bonus = (d.get("delai_semaines") or 0) * (d.get("valeur_semaine_eur") or 0)
            echec = kgv if kgv is not None else 0.0
            h_re = n * (d["extraction_min"] + d["test_min"]) / 60
            v_re = n * (d["p_reutilisable"] * (d["valeur_eur"] + bonus) + (1 - d["p_reutilisable"]) * echec
                        - (d.get("transport_eur") or 0)) - h_re * taux + k_re * c_trait
        if dispo[p]["recyclage"]:
            v_rc, h_rc = np.nan, np.nan
        else:
            h_rc = n * d["tri_min"] / 60
            k_rc = n * kg
            v_rc = n * kgv - h_rc * taux + k_rc * c_trait
        lignes.append({"Pièce": p, "1 Réemploi (€/FRU)": v_re, "2 Recyclage (€/FRU)": v_rc, "3 Jeté (€/FRU)": 0.0,
                       "Heures réemploi": h_re, "Heures recyclage": h_rc, "Kg détournés réemploi": k_re, "Kg détournés recyclage": k_rc,
                       "Manque réemploi": ", ".join(dispo[p]["réemploi"]), "Manque recyclage": ", ".join(dispo[p]["recyclage"])})
    t = pd.DataFrame(lignes)
    if len(t):
        t["Meilleure option seule"] = t[["1 Réemploi (€/FRU)", "2 Recyclage (€/FRU)", "3 Jeté (€/FRU)"]].idxmax(axis=1).str[2:].str.replace(" (€/FRU)", "", regex=False)
    t.attrs["Ouverture soignée (€/FRU)"] = (fru.get("ouverture_min") or np.nan) / 60 * taux if not _inconnu(taux) else np.nan
    t.attrs["Ouverture sommaire (€/FRU)"] = (fru.get("ouverture_tri_min", fru.get("ouverture_min")) or np.nan) / 60 * taux if not _inconnu(taux) else np.nan
    return t


_CODES: dict[int, np.ndarray] = {}


def _codes(n: int) -> np.ndarray:
    """Toutes les affectations de n pièces : matrice (3^n, n), 0 = réemploi, 1 = recyclage, 2 = jeté."""
    if n not in _CODES:
        _CODES[n] = np.indices((3,) * n).reshape(n, -1).T if n else np.zeros((1, 0), dtype=int)
    return _CODES[n]


class Options:
    """Toutes les affectations pièce → option d'un type de FRU : heures, marge et kg détournés par FRU (tableaux numpy)."""

    def __init__(self, fru: dict, taux_defaut):
        taux = fru.get("taux_horaire_eur", taux_defaut)
        t = valeurs_options(fru, taux_defaut)
        if len(t):
            t = t.assign(meilleur=t[["1 Réemploi (€/FRU)", "2 Recyclage (€/FRU)"]].max(axis=1)).sort_values("meilleur", ascending=False).head(MAX_PIECES_ENUM)
        self.noms = list(t["Pièce"]) if len(t) else []
        self.ignorees = max(len(fru.get("pieces", {})) - len(self.noms), 0)      # pièces au-delà de MAX_PIECES_ENUM : laissées dans le FRU
        C = _codes(len(self.noms))
        col = lambda c: t[c].to_numpy(float) if len(t) else np.zeros(0)
        v = np.stack([col("1 Réemploi (€/FRU)"), col("2 Recyclage (€/FRU)"), np.zeros(len(self.noms))])      # (3, n)
        h = np.stack([col("Heures réemploi"), col("Heures recyclage"), np.zeros(len(self.noms))])
        k = np.stack([col("Kg détournés réemploi"), col("Kg détournés recyclage"), np.zeros(len(self.noms))])
        j = np.arange(len(self.noms))
        valide = ~np.isnan(v[C, j]).any(axis=1)                                 # une option non calculable n'est jamais choisie
        ouv = (fru.get("ouverture_min") or 0) / 60
        ouv_tri = (fru.get("ouverture_tri_min", fru.get("ouverture_min")) or 0) / 60
        o = np.where((C == 0).any(axis=1), ouv, np.where((C == 1).any(axis=1), ouv_tri, 0.0))
        self.C = C
        self.H = np.where(valide, np.nan_to_num(h[C, j]).sum(axis=1) + o, 0.0)
        self.M = np.where(valide, np.nan_to_num(v[C, j]).sum(axis=1) - o * taux, -np.inf)
        self.K = np.where(valide, np.nan_to_num(k[C, j]).sum(axis=1), 0.0)

    def etiquette(self, i: int) -> tuple:
        """(pièce, option) hors « jeté » ; tuple vide = FRU laissé tel quel."""
        nom = ("réemploi", "recyclage")
        return tuple((p, nom[c]) for p, c in zip(self.noms, self.C[i]) if c < 2)

    def meilleur(self, mu: float):
        """Plan qui maximise marge − mu × heures : (étiquette, heures, marge, kg). Plan vide si rien n'est rentable."""
        i = int(np.argmax(self.M - mu * self.H))
        e = self.etiquette(i)
        if e and self.M[i] - mu * self.H[i] > 1e-12:
            return e, float(self.H[i]), float(self.M[i]), float(self.K[i])
        return (), 0.0, 0.0, 0.0


def options_fru(fru: dict, taux_defaut):
    """Compatibilité : (étiquettes, heures/FRU, marge/FRU, kg par étiquette) de toutes les affectations valides."""
    o = Options(fru, taux_defaut)
    ok = np.isfinite(o.M)
    etiq = [o.etiquette(i) for i in np.flatnonzero(ok)]
    return etiq, o.H[ok], o.M[ok], {e: float(k) for e, k in zip(etiq, o.K[ok])}


# ---------------------------------------------------------------------------
# 4. Optimisation de la ligne
# ---------------------------------------------------------------------------
def optimiser_ligne(ligne: dict, frus: dict) -> dict:
    """Choix des FRU à démonter et des pièces à extraire, sous la capacité en heures. Valeurs ponctuelles.

    Relâché continu résolu par multiplicateur de Lagrange mu sur les heures : chaque type de FRU prend le plan qui
    maximise marge − mu × heures ; mu est trouvé par dichotomie. Au point de rupture, les heures restantes sont
    données aux types de FRU dont le plan change, dans l'ordre du gain par heure supplémentaire.
    """
    taux = ligne.get("taux_horaire_eur")
    incomplets = {f: manques(d, taux) for f, d in frus.items()}
    ok = {f: dict(d, _c_trait=ligne.get("cout_traitement_eur_kg")) for f, d in frus.items() if not incomplets[f]}
    opts = {f: Options(d, taux) for f, d in ok.items()}
    cap = ligne.get("heures_operateur_an")
    cap = np.inf if cap is None else float(cap)

    def choix(mu):
        return {f: o.meilleur(mu) for f, o in opts.items()}

    def heures(c):
        return sum(ok[f]["rebut_an"] * x[1] for f, x in c.items())

    mu_lo, mu_hi = 0.0, 0.0
    c_hi = choix(0.0)
    c_lo = c_hi
    if heures(c_hi) > cap:
        mu_hi = 1.0
        while heures(choix(mu_hi)) > cap:
            mu_hi *= 2
        for _ in range(60):
            mid = (mu_lo + mu_hi) / 2
            mu_lo, mu_hi = (mid, mu_hi) if heures(choix(mid)) > cap else (mu_lo, mid)
        c_hi, c_lo = choix(mu_hi), choix(mu_lo)
    # c_hi tient dans la capacité ; c_lo la dépasse. Les heures restantes basculent une partie des FRU de c_hi vers c_lo.
    bascule = {}
    if mu_hi > 0:
        reste = cap - heures(c_hi)
        candidats = [(f, (c_lo[f][2] - c_hi[f][2]) / (c_lo[f][1] - c_hi[f][1])) for f in ok
                     if c_lo[f][0] != c_hi[f][0] and c_lo[f][1] > c_hi[f][1]]
        for f, _ in sorted(candidats, key=lambda x: -x[1]):
            if reste <= 1e-12:
                break
            x = min(float(ok[f]["rebut_an"]), reste / (c_lo[f][1] - c_hi[f][1]))
            reste -= x * (c_lo[f][1] - c_hi[f][1])
            bascule[f] = x
    lignes = []
    for f in ok:
        S, h, m, k = c_hi[f]
        n = float(ok[f]["rebut_an"])
        x = bascule.get(f, 0.0)
        if x > 0:                                 # x FRU au plan plus gourmand, le reste au plan sobre
            S2, h2, m2, k2 = c_lo[f]
            lignes.append(_ligne_res(f, S2, x, h2, m2, ok[f], k2))
            if n - x > 1e-9:
                lignes.append(_ligne_res(f, S, n - x if S else 0.0, h, m, ok[f], k))
        else:
            lignes.append(_ligne_res(f, S, n if S else 0.0, h, m, ok[f], k))
    detail = pd.DataFrame(lignes)
    for f, m in incomplets.items():
        if m:
            detail = pd.concat([detail, pd.DataFrame([{"Type de FRU": f, "Décision": "incomplet", "Entrées manquantes": ", ".join(m)}])], ignore_index=True)
    return _bilan(ligne, detail, mu_hi, cap, frus)


def _ligne_res(f, S, n, h, m, d, k=0.0):
    return {"Type de FRU": f, "Décision": "traiter" if S and n > 0 else "jeter telle quelle",
            "1 Réemploi": ", ".join(p for p, o in S if o == "réemploi"),
            "2 Recyclage": ", ".join(p for p, o in S if o == "recyclage"), "FRU traitées / an": n, "FRU rebutées / an": d["rebut_an"],
            "Heures par FRU": h, "Marge par FRU (€)": m, "Marge par heure (€)": m / h if h else np.nan,
            "Heures / an": n * h, "Marge variable / an (€)": n * m, "Kg détournés / an": n * k, "Entrées manquantes": ""}


def _bilan(ligne, detail, mu, cap, frus=None):
    """Résultat de la ligne. Coût fixe ou marge inconnus → NaN (jamais 0)."""
    c = ligne.get("cout_traitement_eur_kg")
    masses = [d["rebut_an"] * d["poids_fru_kg"] for d in (frus or {}).values()
              if not _inconnu(d.get("rebut_an")) and not _inconnu(d.get("poids_fru_kg"))]
    masse = float(sum(masses)) if masses and len(masses) == len(frus) else np.nan
    cout_actuel = masse * c if c is not None else np.nan
    inv, fix = ligne.get("cout_installation_eur"), ligne.get("couts_fixes_annuels_eur")
    fixes = inv / max(ligne.get("amortissement_ans") or 1, 1) + fix if inv is not None and fix is not None else np.nan
    calc = detail[detail["Décision"].ne("incomplet")] if len(detail) else detail
    marge = float(calc["Marge variable / an (€)"].sum()) if len(calc) else np.nan
    h = float(calc["Heures / an"].sum()) if len(calc) else np.nan
    n = float(calc["FRU traitées / an"].sum()) if len(calc) else np.nan
    moy = marge / n if n else np.nan
    excedent = marge - fix if fix is not None else np.nan
    return {"detail": detail, "resume": {
        "Marge variable / an (€)": marge, "Coûts fixes annualisés (€)": fixes, "Résultat / an (€)": marge - fixes,
        "Heures utilisées / an": h, "Capacité (h/an)": cap, "Taux d'occupation": h / cap if np.isfinite(cap) and cap else np.nan,
        "FRU traitées / an": n, "Marge moyenne par FRU (€)": moy,
        "Seuil de rentabilité (FRU / an)": fixes / moy if moy and moy > 0 else np.nan,
        "Retour sur investissement (ans)": inv / excedent if inv is not None and excedent > 0 else np.nan,
        "Valeur d'une heure opérateur en plus (€ net)": mu if len(calc) else np.nan,
        "Types de FRU incomplets": int(detail["Décision"].eq("incomplet").sum()) if len(detail) else 0,
        "Masse des FRU rebutées (kg/an)": masse, "Masse détournée de la benne (kg/an)": float(calc["Kg détournés / an"].sum()) if len(calc) else np.nan,
        "Coût actuel de traitement (€/an)": cout_actuel}}


def comparer_scenarios(ligne: dict, frus: dict) -> pd.DataFrame:
    """Situation actuelle (tout chez le recycleur actuel) contre ligne de démontage + tri. Flux annuels, € ; coût = négatif."""
    r = point_milieu(ligne, frus)["resume"]
    c = ligne.get("cout_traitement_eur_kg")
    c = _milieu(c) if c is not None else np.nan
    evite = r["Masse détournée de la benne (kg/an)"] * c
    actuel = -r["Coût actuel de traitement (€/an)"]
    marge_hors_evite = r["Marge variable / an (€)"] - evite
    lignes = [
        ("Traitement des FRU par le recycleur actuel", actuel, actuel + evite),
        ("Marge de la ligne : réemploi + vente au kg − main-d'œuvre", 0.0, marge_hors_evite),
        ("Coûts fixes de la ligne (installation amortie + annuels)", 0.0, -r["Coûts fixes annualisés (€)"]),
    ]
    t = pd.DataFrame(lignes, columns=["Poste (€/an)", "Actuel", "Avec la ligne"])
    tot = pd.DataFrame([("TOTAL", t["Actuel"].sum(skipna=False), t["Avec la ligne"].sum(skipna=False))], columns=t.columns)
    t = pd.concat([t, tot], ignore_index=True)
    t["Écart"] = t["Avec la ligne"] - t["Actuel"]
    t.attrs.update({"Masse rebutée (kg/an)": r["Masse des FRU rebutées (kg/an)"], "Masse détournée (kg/an)": r["Masse détournée de la benne (kg/an)"],
                    "Part détournée": r["Masse détournée de la benne (kg/an)"] / r["Masse des FRU rebutées (kg/an)"] if r["Masse des FRU rebutées (kg/an)"] else np.nan})
    return t


def monte_carlo_ligne(ligne: dict, frus: dict, n=500, rng=RNG) -> dict:
    """Tire toutes les plages, ré-optimise la ligne à chaque tirage."""
    res, choix = [], {}
    for _ in range(n):
        r = optimiser_ligne(_tirer(ligne, rng), _tirer(frus, rng))
        res.append(r["resume"])
        d = r["detail"]
        for f in (d.loc[d["Décision"].eq("traiter"), "Type de FRU"].unique() if len(d) else []):
            choix[f] = choix.get(f, 0) + 1
    R = pd.DataFrame(res)
    x = R["Résultat / an (€)"].dropna()
    out = {"tirages": R, "P(ligne rentable)": float((x > 0).mean()) if len(x) else np.nan,
           "Résultat P5 / médiane / P95 (€)": tuple(np.quantile(x, [0.05, 0.5, 0.95]).round(0)) if len(x) else (np.nan,) * 3,
           "Fréquence de traitement par type de FRU": {f: c / n for f, c in choix.items()}}
    return out


def point_milieu(ligne, frus):
    """Version déterministe au centre des plages, pour lire le détail."""
    return optimiser_ligne(_milieu(ligne), _milieu(frus))


def resultat_par_periode(ligne: dict, frus: dict, flux: pd.DataFrame, periodes_par_an=52) -> pd.DataFrame:
    """Le modèle rejoué période par période sur le flux RÉEL des FRU rebutées (colonnes Semaine, FRU, FRU rebutées).

    Chaque période : capacité = heures annuelles / périodes ; coût fixe = (installation amortie + fixes annuels) / périodes,
    payé même si peu de FRU arrivent ; pas de stock d'une période à l'autre (hypothèse 10 du modèle).
    Les attributs du tableau comparent avec le modèle annuel au flux moyen : l'écart est le COÛT DE LA VARIABILITÉ
    du flux (heures perdues les semaines creuses, FRU non traitées les semaines chargées).
    """
    lg, fr = _milieu(ligne), _milieu(frus)
    H, inv, fix = lg.get("heures_operateur_an"), lg.get("cout_installation_eur"), lg.get("couts_fixes_annuels_eur")
    fixe_p = (inv / max(lg.get("amortissement_ans") or 1, 1) + fix) / periodes_par_an if inv is not None and fix is not None else np.nan
    piv = flux[flux["FRU"].isin(fr)].pivot_table(index="Semaine", columns="FRU", values="FRU rebutées", aggfunc="sum", fill_value=0)
    piv = piv.reindex(sorted(flux["Semaine"].unique()), fill_value=0)
    lignes = []
    for sem, n in piv.iterrows():
        fr_t = {f: dict(d, rebut_an=float(n.get(f, 0))) for f, d in fr.items()}
        r = optimiser_ligne(dict(lg, heures_operateur_an=H / periodes_par_an if H else None), fr_t)["resume"]
        lignes.append({"Semaine": sem, "FRU arrivées": float(n.sum()), "FRU traitées": r["FRU traitées / an"], "Heures utilisées": r["Heures utilisées / an"],
                       "Capacité (h)": H / periodes_par_an if H else np.nan, "Marge variable (€)": r["Marge variable / an (€)"],
                       "Coût fixe (€)": fixe_p, "Résultat (€)": r["Marge variable / an (€)"] - fixe_p,
                       "Valeur d'une heure en plus (€)": r["Valeur d'une heure opérateur en plus (€ net)"]})
    t = pd.DataFrame(lignes)
    if len(t):
        t["Résultat cumulé (€)"] = t["Résultat (€)"].cumsum()
        moyen = {f: dict(d, rebut_an=float(piv[f].mean()) * periodes_par_an if f in piv else 0.0) for f, d in fr.items()}
        annuel = optimiser_ligne(lg, moyen)["resume"]["Résultat / an (€)"]
        par_periode = t["Résultat (€)"].mean() * periodes_par_an
        t.attrs.update({"Périodes": len(t), "Résultat annualisé, période par période (€)": par_periode,
                        "Résultat du modèle annuel au flux moyen (€)": annuel, "Coût de la variabilité du flux (€/an)": annuel - par_periode,
                        "Périodes en perte": int((t["Résultat (€)"] < 0).sum())})
    return t
