"""« Modèle de Rex » — le modèle qui choisit réemploi ou recyclage pour chaque pièce d'une FRU démontée.

Le choix se ramène à une probabilité : q = P(la pièce extraite est réutilisable). Réemploi si
    q × (valeur + délai évité) + (1 − q) × valeur au kg − coût d'extraction et de test  >  valeur au kg − coût de tri.
Le modèle à choisir, justifier, entraîner et mesurer est donc celui qui estime q.

Modèle retenu : Bêta-binomial bayésien par (type de FRU, pièce).
  a priori  : q0 tiré de la consommation (erc.ligne.p_reutilisable), de force N0 pseudo-observations ;
  données   : résultats de l'audit de démontage (pièces testées, pièces bonnes), ajoutés chaque semaine ;
  a posteriori : Bêta(q0·N0 + bonnes ; (1 − q0)·N0 + mauvaises) → moyenne et intervalle, passés à la ligne de tri.
Justification : peu de données au départ (quelques FRU auditées), besoin d'une incertitude pour le Monte-Carlo,
mise à jour sans ré-entraînement, lisible par l'atelier. Il est comparé à deux références plus simples ; un modèle
plus riche (régression logistique ou gradient boosting sur l'âge, le motif de rebut, l'atelier) ne le remplace
que s'il le bat sur les métriques ci-dessous.

Entraînement et métriques : évaluation « prequentielle » — chaque lot d'audit est d'abord prédit avec ce que le
modèle savait avant, puis sert à le mettre à jour. Aucune donnée ne sert à la fois à apprendre et à noter.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RNG = np.random.default_rng(2026)
N0 = 10            # force de l'a priori, en pièces équivalentes ; hyperparamètre réglé sur la log-perte prequentielle
CLES = ["Type de FRU", "Pièce"]


def posterieur(q0, bonnes, testees, n0=N0, n_tirages=20000):
    """Moyenne et intervalle à 90 % de q. q0 inconnu → a priori de Jeffreys Bêta(0,5 ; 0,5)."""
    a0, b0 = (0.5, 0.5) if q0 is None or not np.isfinite(q0) else (max(q0, 1e-3) * n0, max(1 - q0, 1e-3) * n0)
    a, b = a0 + bonnes, b0 + (testees - bonnes)
    x = RNG.beta(a, b, n_tirages)
    return {"q moyen": a / (a + b), "q bas (5 %)": float(np.quantile(x, 0.05)), "q haut (95 %)": float(np.quantile(x, 0.95)),
            "Pièces testées": testees, "Poids des données": testees / (testees + a0 + b0), "a": a, "b": b}


def entrainer(audit: pd.DataFrame, a_priori: pd.DataFrame, n0=N0) -> pd.DataFrame:
    """audit : Date, Type de FRU, Pièce, Pièces testées, Pièces bonnes (une ligne par lot).
    a_priori : Type de FRU, Pièce, q0 (issu de la consommation ; NaN accepté)."""
    g = audit.groupby(CLES)[["Pièces testées", "Pièces bonnes"]].sum() if len(audit) else \
        pd.DataFrame(columns=["Pièces testées", "Pièces bonnes"], index=pd.MultiIndex.from_arrays([[], []], names=CLES), dtype=float)
    t = a_priori.set_index(CLES).join(g, how="outer").fillna({"Pièces testées": 0, "Pièces bonnes": 0})
    res = [posterieur(r.get("q0"), r["Pièces bonnes"], r["Pièces testées"], n0) for _, r in t.iterrows()]
    return pd.concat([t.reset_index(), pd.DataFrame(res).drop(columns="Pièces testées")], axis=1)


def plage_pour_ligne(r) -> tuple:
    """Triangle (bas, mode, haut) à mettre dans p_reutilisable de erc.ligne."""
    return (r["q bas (5 %)"], float(np.clip(r["q moyen"], r["q bas (5 %)"], r["q haut (95 %)"])), r["q haut (95 %)"])


def evaluer(audit: pd.DataFrame, a_priori: pd.DataFrame, n0=N0) -> dict:
    """Évaluation prequentielle, lot par lot dans l'ordre des dates, du modèle et de deux références.

    Références : « a priori seul » (consommation, jamais mise à jour) et « fréquence observée » (bonnes / testées,
    sans a priori ; 0,5 avant toute donnée).
    Métriques, pondérées par les pièces testées :
      Brier        : (prédit − observé)², 0 = parfait ; 0,25 = pile ou face
      Log-perte    : pénalise les prédictions sûres et fausses
      Écart absolu : |taux prédit − taux observé| du lot, lisible en points de %
      Couverture   : part des lots dont le nombre de pièces bonnes tombe dans l'intervalle prédictif à 90 % (cible ≈ 90 %)
    """
    q0 = a_priori.set_index(CLES)["q0"].to_dict()
    etat, lignes = {}, []
    for _, r in audit.sort_values("Date").iterrows():
        k, n, b = (r["Type de FRU"], r["Pièce"]), r["Pièces testées"], r["Pièces bonnes"]
        if n <= 0:
            continue
        bb, nn = etat.get(k, (0, 0))
        prior = q0.get(k, np.nan)
        post = posterieur(prior, bb, nn, n0, 4000)
        pred = {"Bêta-binomial": post["q moyen"], "A priori seul": prior if np.isfinite(prior) else 0.5,
                "Fréquence observée": bb / nn if nn else 0.5}
        obs = b / n
        # Intervalle PRÉDICTIF du lot : incertitude sur q + hasard du tirage de n pièces (loi bêta-binomiale).
        lo, hi = np.quantile(RNG.binomial(int(n), RNG.beta(post["a"], post["b"], 4000)), [0.05, 0.95])
        for m, p in pred.items():
            pc = float(np.clip(p, 1e-6, 1 - 1e-6))
            lignes.append({"Modèle": m, "Date": r["Date"], "Type de FRU": k[0], "Pièce": k[1], "n": n, "Prédit": p, "Observé": obs,
                           "Brier": obs * (1 - p) ** 2 + (1 - obs) * p ** 2, "Log-perte": -(obs * np.log(pc) + (1 - obs) * np.log(1 - pc)),
                           "Écart absolu": abs(p - obs),
                           "Dans IC90": (lo <= b <= hi) if m == "Bêta-binomial" else np.nan})
        etat[k] = (bb + b, nn + n)
    d = pd.DataFrame(lignes)
    if not len(d):
        return {"detail": d, "metriques": pd.DataFrame()}
    w = lambda c: lambda g: np.average(g[c], weights=g["n"])
    met = d.groupby("Modèle").apply(lambda g: pd.Series({"Lots": len(g), "Pièces": g["n"].sum(), "Brier": w("Brier")(g), "Log-perte": w("Log-perte")(g),
                                                          "Écart absolu moyen": w("Écart absolu")(g), "Couverture IC90": g["Dans IC90"].astype(float).mean()}),
                                    include_groups=False).reset_index().sort_values("Log-perte")
    return {"detail": d, "metriques": met}


def regler_n0(audit, a_priori, grille=(2, 5, 10, 20, 50)) -> pd.DataFrame:
    """Réglage de l'hyperparamètre N0 sur la log-perte prequentielle."""
    out = []
    for n0 in grille:
        m = evaluer(audit, a_priori, n0)["metriques"]
        if len(m):
            r = m[m["Modèle"].eq("Bêta-binomial")].iloc[0]
            out.append({"N0": n0, "Log-perte": r["Log-perte"], "Brier": r["Brier"], "Couverture IC90": r["Couverture IC90"]})
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# Décision : exploration par échantillonnage de Thompson
# ---------------------------------------------------------------------------
# Le modèle n'apprend que sur les pièces qu'on TESTE. S'il décide « recyclage » sur la foi d'un a priori trop
# pessimiste, il ne testera jamais la pièce et ne découvrira jamais son erreur. Thompson : chaque période, on tire
# un q plausible dans l'a posteriori de chaque pièce et on optimise la ligne avec ces tirages. Une pièce incertaine
# est ainsi essayée de temps en temps, d'autant moins que l'audit a tranché. C'est un bandit (apprentissage par
# renforcement à un état), la forme la plus simple qui règle ce problème.
def plan_thompson(ligne: dict, frus: dict, post: pd.DataFrame, rng=RNG) -> dict:
    """Plan de la période : q tirés dans l'a posteriori, puis optimisation de la ligne. `post` vient de entrainer()."""
    from . import ligne as elt
    fr = elt._milieu(frus)
    for _, r in post.iterrows():
        f, p = r["Type de FRU"], r["Pièce"]
        if f in fr and p in fr[f].get("pieces", {}) and (r["Pièces testées"] > 0 or pd.notna(r.get("q0"))):
            fr[f]["pieces"][p] = dict(fr[f]["pieces"][p], p_reutilisable=float(rng.beta(r["a"], r["b"])))
    return elt.optimiser_ligne(elt._milieu(ligne), fr)


def simuler_politiques(q_vrai, q0, gain_bonne, gain_mauvaise, gain_recyclage, n_pieces=400, n0=N0, n_sim=300, rng=RNG) -> pd.DataFrame:
    """Banc d'essai SYNTHÉTIQUE du choix réemploi / recyclage pour une pièce, vérité q_vrai connue du simulateur seul.

    gain_bonne / gain_mauvaise : gain net du réemploi selon que la pièce passe ou non le test ; gain_recyclage : gain net du tri.
    Politiques : « A priori seul » (q0, jamais mis à jour), « Glouton » (moyenne a posteriori), « Thompson » (tirage).
    Métrique : regret cumulé = gain de l'oracle (qui connaît q_vrai) − gain espéré de la politique.
    """
    esp = lambda q: q * gain_bonne + (1 - q) * gain_mauvaise
    oracle = max(esp(q_vrai), gain_recyclage)
    a0, b0 = max(q0, 1e-3) * n0, max(1 - q0, 1e-3) * n0
    out = []
    for pol in ("A priori seul", "Glouton", "Thompson"):
        a, b = np.full(n_sim, a0), np.full(n_sim, b0)
        regret, tests, cum = np.zeros(n_sim), np.zeros(n_sim), []
        for _ in range(n_pieces):
            q = np.full(n_sim, q0) if pol == "A priori seul" else a / (a + b) if pol == "Glouton" else rng.beta(a, b)
            re = esp(q) > gain_recyclage
            bonne = rng.random(n_sim) < q_vrai
            if pol != "A priori seul":
                a, b = a + (re & bonne), b + (re & ~bonne)
            tests += re
            regret += oracle - np.where(re, esp(q_vrai), gain_recyclage)
            cum.append(regret.mean())
        out.append({"Politique": pol, "Regret cumulé moyen (€)": regret.mean(), "Regret par pièce (€)": regret.mean() / n_pieces,
                    "Part de pièces testées": tests.mean() / n_pieces, "q estimé final": float(np.mean(a / (a + b))) if pol != "A priori seul" else q0,
                    "Courbe": cum})
    t = pd.DataFrame(out)
    t.attrs.update({"q vrai": q_vrai, "q0": q0, "Seuil q* (réemploi si q > q*)": (gain_recyclage - gain_mauvaise) / (gain_bonne - gain_mauvaise),
                    "Gain oracle par pièce (€)": oracle})
    return t
