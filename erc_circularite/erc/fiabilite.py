"""Fiabilité opérationnelle : Kaplan-Meier, Weibull avec censure et troncature, taux bayésien, vie résiduelle.

Le fichier de fiabilité ne contient que des défaillances (pas de survivants) : il donne la FORME de la défaillance
et, avec le nombre de pièces posées sur la même période, un taux de défaillance précoce par origine de pièce.
Il ne donne pas une durée de vie absolue.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .sources import base_ref, origine

RNG = np.random.default_rng(2026)

# ---------------------------------------------------------------------------
# 3. Fiabilité : estimateurs (numpy seul)
# ---------------------------------------------------------------------------
def kaplan_meier(t, evenement):
    """Survie de Kaplan-Meier. t : durées, evenement : 1 = défaillance, 0 = censuré."""
    t, e = np.asarray(t, float), np.asarray(evenement, int)
    ordre = np.argsort(t)
    t, e = t[ordre], e[ordre]
    temps = np.unique(t[e == 1])
    s, out = 1.0, []
    for u in temps:
        n = (t >= u).sum()
        d = ((t == u) & (e == 1)).sum()
        s *= 1 - d / n
        out.append((u, n, d, s))
    return pd.DataFrame(out, columns=["t", "à risque", "défaillances", "S(t)"])


def _nelder_mead(f, x0, iters=400, tol=1e-9):
    x0 = np.asarray(x0, float)
    pts = [x0] + [x0 + np.eye(len(x0))[i] * 0.5 for i in range(len(x0))]
    vals = [f(p) for p in pts]
    for _ in range(iters):
        o = np.argsort(vals)
        pts, vals = [pts[i] for i in o], [vals[i] for i in o]
        if abs(vals[-1] - vals[0]) < tol:
            break
        c = np.mean(pts[:-1], axis=0)
        r = c + (c - pts[-1]); fr = f(r)
        if fr < vals[0]:
            e = c + 2 * (c - pts[-1]); fe = f(e)
            pts[-1], vals[-1] = (e, fe) if fe < fr else (r, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = r, fr
        else:
            k = c + 0.5 * (pts[-1] - c); fk = f(k)
            if fk < vals[-1]:
                pts[-1], vals[-1] = k, fk
            else:
                pts = [pts[0] + 0.5 * (p - pts[0]) for p in pts]
                vals = [f(p) for p in pts]
    i = int(np.argmin(vals))
    return pts[i], vals[i]


def weibull_mle(t, evenement=None, troncature=None):
    """Weibull (forme k, échelle λ) par maximum de vraisemblance.

    evenement : 1 défaillance, 0 censure à droite (pièce encore en service à t). Défaut : toutes défaillances.
    troncature : fenêtre W si l'on n'observe QUE les défaillances survenues avant W (cas d'un fichier ELF,
                 early life failure) ; la vraisemblance devient f(t)/F(W). Sans survivants ni dénominateur,
                 seule la forme k est alors informative : λ reste mal identifié.
    """
    t = np.clip(np.asarray(t, float), 0.5, None)          # elf_days = 0 → demi-journée (défaillance à la pose)
    e = np.ones_like(t) if evenement is None else np.asarray(evenement, float)
    if e.sum() < 3:
        return {"k": np.nan, "lambda": np.nan, "n": len(t), "défaillances": int(e.sum()), "note": "moins de 3 défaillances"}

    def nll(p):
        k, lam = np.exp(p)
        z = (t / lam) ** k
        ll = e * (np.log(k / lam) + (k - 1) * np.log(t / lam)) - z
        if troncature:
            FW = 1 - np.exp(-(troncature / lam) ** k)
            ll = ll - e * np.log(max(FW, 1e-300))
        return -ll.sum()

    p, v = _nelder_mead(nll, [0.0, np.log(np.median(t) + 1)])
    k, lam = np.exp(p)
    return {"k": k, "lambda": lam, "n": len(t), "défaillances": int(e.sum()), "-logL": v,
            "note": "tronqué à W : λ indicatif" if troncature else ""}


def lecture_forme(k):
    if not np.isfinite(k):
        return "inconnu"
    if k < 0.9:
        return "mortalité infantile : une pièce qui a déjà tourné est plus sûre qu'une neuve ; test/déverminage utile"
    if k <= 1.1:
        return "aléatoire : l'âge ne change pas le risque ; réemploi neutre"
    return "usure : le risque croît avec l'âge ; réemploi seulement si l'âge du donneur est connu et faible"


def survie_weibull(t, k, lam):
    return np.exp(-(np.asarray(t, float) / lam) ** k)


def survie_conditionnelle(age, duree, k, lam):
    """P(la pièce survit `duree` de plus | elle a déjà `age`) = R(age+duree)/R(age)."""
    return survie_weibull(age + duree, k, lam) / survie_weibull(age, k, lam)


def vie_residuelle_moyenne(age, k, lam, horizon_mult=20, n=4000):
    """Durée de vie résiduelle moyenne MRL(a) = ∫ R(a+u) du / R(a), intégrée numériquement."""
    u = np.linspace(0, lam * horizon_mult, n)
    return np.trapezoid(survie_conditionnelle(age, u, k, lam), u) if hasattr(np, "trapezoid") \
        else np.trapz(survie_conditionnelle(age, u, k, lam), u)


def taux_bayes(defaillances, poses, prior_moy=None, prior_force=20, n_tirages=20000):
    """Taux de défaillance précoce (ELF / pièces posées) : loi Bêta.

    Sans a priori : Jeffreys Bêta(0,5 ; 0,5). Avec a priori de famille (moyenne m, force n0) :
    Bêta(m·n0 ; (1−m)·n0) — les références à faible effectif sont tirées vers leur famille.
    """
    if poses is None or not np.isfinite(poses) or poses <= 0:
        return {"Taux ELF moyen": np.nan, "IC90 bas": np.nan, "IC90 haut": np.nan}
    a0, b0 = (0.5, 0.5) if prior_moy is None or not np.isfinite(prior_moy) else (prior_moy * prior_force, (1 - prior_moy) * prior_force)
    a, b = a0 + defaillances, b0 + max(poses - defaillances, 0)
    x = RNG.beta(a, b, n_tirages)
    return {"Taux ELF moyen": a / (a + b), "IC90 bas": np.quantile(x, 0.05), "IC90 haut": np.quantile(x, 0.95)}


# A priori physiques (physics-of-failure), à confirmer par la fiche technique de chaque référence.
def vie_condensateur_h(vie_nominale_h, t_nominale_c, t_service_c):
    """Règle d'Arrhenius des électrolytiques : la vie double tous les 10 °C sous la température nominale."""
    return vie_nominale_h * 2 ** ((t_nominale_c - t_service_c) / 10)


def cycles_igbt(delta_tj, A=None, n=5.0):
    """Coffin-Manson (LESIT) : Nf = A·ΔTj^-n. A dépend du module : fiche fabricant ou essai. Sans A : rapport relatif."""
    return (A or 1.0) * float(delta_tj) ** (-n)


# ---------------------------------------------------------------------------
# 4. Agrégation fiabilité depuis le cache ELF
# ---------------------------------------------------------------------------
def fiabilite_par_reference(elf: pd.DataFrame, fenetre_elf=None, poses: pd.Series | None = None) -> pd.DataFrame:
    """Une ligne par (référence de base, origine de la pièce posée).

    elf    : cache du fichier Parts_DI_ULS (colonnes replacement_part_no, elf_days, …)
    poses  : pièces posées sur la MÊME période que le fichier ELF, indexées par (base, origine). Sans elle,
             aucun taux n'est calculé (le fichier ne contient que des défaillances).
    """
    d = elf.copy()
    d["Base"] = d["replacement_part_no"].map(base_ref)
    d["Origine"] = d["replacement_part_no"].map(origine)
    d["elf_days"] = pd.to_numeric(d["elf_days"], errors="coerce")
    if poses is not None:                               # clés normalisées : une référence lue comme nombre doit joindre
        poses = poses.copy()
        poses.index = pd.MultiIndex.from_tuples([(base_ref(re.sub(r"\.0$", "", str(b))), str(o)) for b, o in poses.index])
        poses = poses.groupby(level=[0, 1]).sum()
    W = fenetre_elf or (np.nanmax(d["elf_days"]) if d["elf_days"].notna().any() else None)
    lignes = []
    for (b, o), g in d.groupby(["Base", "Origine"]):
        t = g["elf_days"].dropna().to_numpy()
        w = weibull_mle(t, troncature=W) if len(t) else {"k": np.nan, "lambda": np.nan, "n": 0, "défaillances": 0, "note": "aucune durée"}
        ligne = {"Référence": b, "Origine posée": o, "Défaillances ELF": len(g), "elf_days renseigné": len(t),
                 "elf_days médiane": np.median(t) if len(t) else np.nan,
                 "Part à J0 (DOA)": float(np.mean(t == 0)) if len(t) else np.nan,
                 "Forme Weibull k": w["k"], "Lecture de la forme": lecture_forme(w["k"]), "Note": w.get("note", "")}
        n_pose = poses.get((b, o), np.nan) if poses is not None else np.nan
        ligne["Pièces posées (même période)"] = n_pose
        ligne.update(taux_bayes(len(g), n_pose))
        lignes.append(ligne)
    out = pd.DataFrame(lignes)
    if len(out):
        neuf = out[out["Origine posée"].eq("Neuve")].set_index("Référence")["Taux ELF moyen"]
        out["Rapport au neuf (taux)"] = out["Taux ELF moyen"] / out["Référence"].map(neuf)
    return out


