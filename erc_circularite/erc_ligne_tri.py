"""ERC : économie d'une ligne de tri / démontage des FRU rebutées (et non plus pièce par pièce).

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

from itertools import product

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
#   3 « jeté »      : la pièce reste dans la FRU, qui part en benne sans coût. Valeur 0 (référence).
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
    dispo, lignes = options_disponibles(fru), []
    for p, d in fru.get("pieces", {}).items():
        n = d.get("n_par_fru")
        kgv = None if dispo[p]["recyclage"] else d["poids_kg"] * d["prix_recycleur_eur_kg"]
        if dispo[p]["réemploi"]:
            v_re, h_re = np.nan, np.nan
        else:
            bonus = (d.get("delai_semaines") or 0) * (d.get("valeur_semaine_eur") or 0)
            echec = kgv if kgv is not None else 0.0
            h_re = n * (d["extraction_min"] + d["test_min"]) / 60
            v_re = n * (d["p_reutilisable"] * (d["valeur_eur"] + bonus) + (1 - d["p_reutilisable"]) * echec
                        - (d.get("transport_eur") or 0)) - h_re * taux
        if dispo[p]["recyclage"]:
            v_rc, h_rc = np.nan, np.nan
        else:
            h_rc = n * d["tri_min"] / 60
            v_rc = n * kgv - h_rc * taux
        lignes.append({"Pièce": p, "1 Réemploi (€/FRU)": v_re, "2 Recyclage (€/FRU)": v_rc, "3 Jeté (€/FRU)": 0.0,
                       "Heures réemploi": h_re, "Heures recyclage": h_rc,
                       "Manque réemploi": ", ".join(dispo[p]["réemploi"]), "Manque recyclage": ", ".join(dispo[p]["recyclage"])})
    t = pd.DataFrame(lignes)
    if len(t):
        t["Meilleure option seule"] = t[["1 Réemploi (€/FRU)", "2 Recyclage (€/FRU)", "3 Jeté (€/FRU)"]].idxmax(axis=1).str[2:].str.replace(" (€/FRU)", "", regex=False)
    t.attrs["Ouverture soignée (€/FRU)"] = (fru.get("ouverture_min") or np.nan) / 60 * taux if not _inconnu(taux) else np.nan
    t.attrs["Ouverture sommaire (€/FRU)"] = (fru.get("ouverture_tri_min", fru.get("ouverture_min")) or np.nan) / 60 * taux if not _inconnu(taux) else np.nan
    return t


def options_fru(fru: dict, taux_defaut):
    """Toutes les affectations pièce → option. Renvoie (étiquettes, heures/FRU, marge/FRU) en tableaux numpy.
    L'étiquette est le tuple des (pièce, option) hors « jeté » ; tuple vide = FRU jetée telle quelle."""
    taux = fru.get("taux_horaire_eur", taux_defaut)
    t = valeurs_options(fru, taux_defaut).set_index("Pièce")
    t["meilleur"] = t[["1 Réemploi (€/FRU)", "2 Recyclage (€/FRU)"]].max(axis=1)
    noms = list(t.sort_values("meilleur", ascending=False).index[:MAX_PIECES_ENUM])
    choix_p = [[o for o, col in (("réemploi", "1 Réemploi (€/FRU)"), ("recyclage", "2 Recyclage (€/FRU)")) if pd.notna(t.at[p, col])] + ["jeté"]
               for p in noms]
    ouv = (fru.get("ouverture_min") or 0) / 60
    ouv_tri = (fru.get("ouverture_tri_min", fru.get("ouverture_min")) or 0) / 60
    etiq, H, M = [], [], []
    for combo in product(*choix_p):
        h = m = 0.0
        for p, o in zip(noms, combo):
            if o == "réemploi":
                h += t.at[p, "Heures réemploi"]; m += t.at[p, "1 Réemploi (€/FRU)"]
            elif o == "recyclage":
                h += t.at[p, "Heures recyclage"]; m += t.at[p, "2 Recyclage (€/FRU)"]
        o_ = ouv if "réemploi" in combo else ouv_tri if "recyclage" in combo else 0.0
        etiq.append(tuple((p, o) for p, o in zip(noms, combo) if o != "jeté"))
        H.append(h + o_); M.append(m - o_ * taux)
    return etiq, np.array(H), np.array(M)


# ---------------------------------------------------------------------------
# 4. Optimisation de la ligne
# ---------------------------------------------------------------------------
def optimiser_ligne(ligne: dict, frus: dict) -> dict:
    """Choix des FRU à démonter et des pièces à extraire, sous la capacité en heures. Valeurs ponctuelles."""
    taux = ligne.get("taux_horaire_eur")
    incomplets = {f: manques(d, taux) for f, d in frus.items()}
    ok = {f: d for f, d in frus.items() if not incomplets[f]}
    opts = {f: options_fru(d, taux) for f, d in ok.items()}
    cap = ligne.get("heures_operateur_an") or np.inf

    def choix(mu):
        c = {}
        for f, (E, H, M) in opts.items():
            i = int(np.argmax(M - mu * H))
            c[f] = (E[i], H[i], M[i]) if M[i] - mu * H[i] > 1e-12 and E[i] else ((), 0.0, 0.0)
        return c

    def heures(c):
        return sum(ok[f]["rebut_an"] * h for f, (S, h, m) in c.items())

    mu_lo, mu_hi = 0.0, 0.0
    c_hi = choix(0.0)
    if heures(c_hi) > cap:
        mu_hi = 1.0
        while heures(choix(mu_hi)) > cap:
            mu_hi *= 2
        for _ in range(60):
            mid = (mu_lo + mu_hi) / 2
            mu_lo, mu_hi = (mid, mu_hi) if heures(choix(mid)) > cap else (mu_lo, mid)
        c_hi, c_lo = choix(mu_hi), choix(mu_lo)
    volumes = {f: float(ok[f]["rebut_an"]) if c_hi[f][0] else 0.0 for f in ok}
    # Heures restantes : on bascule une partie des FRU vers le choix plus gourmand de mu_lo (point de rupture).
    if mu_hi > 0:
        reste = cap - heures(c_hi)
        for f in ok:
            S_lo, h_lo, m_lo = c_lo[f]
            S_hi, h_hi, m_hi = c_hi[f]
            if S_lo != S_hi and h_lo > h_hi and reste > 0:
                x = min(ok[f]["rebut_an"], reste / (h_lo - h_hi))
                reste -= x * (h_lo - h_hi)
                volumes[f] = (f, x)            # marque de mélange
    lignes = []
    for f in ok:
        S, h, m = c_hi[f]
        v = volumes[f]
        if isinstance(v, tuple):              # mélange : x FRU au choix gourmand, le reste au choix sobre
            x = v[1]
            S_lo, h_lo, m_lo = c_lo[f]
            n_hi = ok[f]["rebut_an"] - x if S else 0.0
            lignes.append(_ligne_res(f, S_lo, x, h_lo, m_lo, ok[f]))
            if n_hi > 0:
                lignes.append(_ligne_res(f, S, n_hi, h, m, ok[f]))
        else:
            lignes.append(_ligne_res(f, S, v, h, m, ok[f]))
    detail = pd.DataFrame(lignes)
    for f, m in incomplets.items():
        if m:
            detail = pd.concat([detail, pd.DataFrame([{"Type de FRU": f, "Décision": "incomplet", "Entrées manquantes": ", ".join(m)}])])
    return _bilan(ligne, detail, mu_hi, cap)


def _ligne_res(f, S, n, h, m, d):
    return {"Type de FRU": f, "Décision": "traiter" if S and n > 0 else "jeter telle quelle",
            "1 Réemploi": ", ".join(p for p, o in S if o == "réemploi"),
            "2 Recyclage": ", ".join(p for p, o in S if o == "recyclage"), "FRU traitées / an": n, "FRU rebutées / an": d["rebut_an"],
            "Heures par FRU": h, "Marge par FRU (€)": m, "Marge par heure (€)": m / h if h else np.nan,
            "Heures / an": n * h, "Marge variable / an (€)": n * m, "Entrées manquantes": ""}


def _bilan(ligne, detail, mu, cap):
    """Résultat de la ligne. Coût fixe ou marge inconnus → NaN (jamais 0)."""
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
        "Types de FRU incomplets": int(detail["Décision"].eq("incomplet").sum()) if len(detail) else 0}}


def monte_carlo_ligne(ligne: dict, frus: dict, n=500, rng=RNG) -> dict:
    """Tire toutes les plages, ré-optimise la ligne à chaque tirage."""
    res, choix = [], {}
    for _ in range(n):
        r = optimiser_ligne(_tirer(ligne, rng), _tirer(frus, rng))
        res.append(r["resume"])
        d = r["detail"]
        for f in d.loc[d["Décision"].eq("traiter"), "Type de FRU"].unique():
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
