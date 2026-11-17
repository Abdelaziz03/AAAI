"""Fiabilité opérationnelle : Kaplan-Meier, forme de Weibull, taux de défaillance précoce, vie résiduelle.

Le fichier de fiabilité ne contient que des défaillances survenues dans une fenêtre de quelques semaines après la
pose (défaillances précoces), avec leur délai en jours entiers ; il ne contient aucune pièce encore en service.
Il donne donc :
  - la FORME k de la défaillance (le risque baisse-t-il, reste-t-il constant ou monte-t-il avec l'âge ?), avec un
    intervalle d'incertitude : sans cet intervalle, k seul ne permet aucune lecture ;
  - avec le nombre de pièces posées sur la même période, un taux de défaillance précoce par origine de pièce, et le
    rapport de ce taux à celui de la pièce neuve, lui aussi avec son intervalle.
Il ne donne pas une durée de vie : l'échelle λ de la loi de Weibull n'est pas identifiable sur des données tronquées,
et aucune durée de vie n'est jamais tirée de ce fichier.

Aucun tirage aléatoire ne dépend de l'ordre des appels : les quantiles de la loi Bêta sont calculés exactement, et
le seul calcul par tirages (rapport de deux taux) part d'une graine propre à chaque ligne.
Dépendances : numpy et pandas seulement (scipy ne sert qu'aux tests, pour vérifier les formules).
"""
from __future__ import annotations

import math
import re
import zlib
from statistics import NormalDist

import numpy as np
import pandas as pd

from .sources import base_ref, origine

GRAINE = 2026
# Nombre minimal de défaillances datées pour estimer une forme. Choix du projet : en dessous de 10, l'intervalle à
# 90 % sur k couvre plus d'un facteur 3 (écart-type relatif de k voisin de 1/√n) et la simulation de
# tests/test_fiabilite.py ne valide la couverture de l'intervalle qu'à partir de 10 défaillances.
MIN_DEFAILLANCES_FORME = 10
# Plage explorée pour k. Hors de cette plage, la forme est déclarée non estimable (délais tous au même endroit).
K_MIN, K_MAX = 0.05, 20.0
# Zones d'équivalence, conventions du projet (± 20 % environ, bornes inverses l'une de l'autre) :
# « aléatoire » ou « équivalent au neuf » ne sont écrits que si tout l'intervalle tient dans la zone.
ZONE_K_ALEATOIRE = (0.8, 1.25)
ZONE_RAPPORT_EQUIVALENT = (0.8, 1.25)
# Niveaux des intervalles sur k : 90 % (colonnes « k bas (5 %) », « k haut (95 %) », tracées sur la figure) et
# 95 % (colonnes « k bas (2,5 %) », « k haut (97,5 %) », sur lesquelles repose la lecture de la forme).
NIVEAUX_K = (0.90, 0.95)
NIVEAU_LECTURE = 0.95


# ---------------------------------------------------------------------------
# 1. Loi Bêta et fonction gamma incomplète (numpy seul, résultats exacts et reproductibles)
# ---------------------------------------------------------------------------
def _stirling(z):
    """Terme correctif de la formule de Stirling de ln Γ(z), précis à 1e-16 près pour z ≥ 100."""
    return 1.0 / (12 * z) - 1.0 / (360 * z ** 3) + 1.0 / (1260 * z ** 5)


def _log_beta(a, b):
    """ln B(a, b) = ln Γ(a) + ln Γ(b) − ln Γ(a + b), sans perte de précision quand a ou b est grand
    (la différence directe de deux ln Γ voisins de 1e6 perdrait dix chiffres)."""
    a, b = (a, b) if a <= b else (b, a)
    if b < 100:
        return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    if a < 100:                                               # ln Γ(a + b) − ln Γ(b) par Stirling
        return math.lgamma(a) - ((b - 0.5) * math.log1p(a / b) + a * math.log(a + b) - a + _stirling(a + b) - _stirling(b))
    return (0.5 * math.log(2 * math.pi) - (a - 0.5) * math.log1p(b / a) - (b - 0.5) * math.log1p(a / b) - 0.5 * math.log(a + b)
            + _stirling(a) + _stirling(b) - _stirling(a + b))


def _fraction_beta(a, b, x, eps=1e-15, iters=20000):
    """Fraction continue de la fonction bêta incomplète (méthode de Lentz modifiée)."""
    mini = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > mini else mini)
    h = d
    for m in range(1, iters + 1):
        m2 = 2 * m
        for aa in (m * (b - m) * x / ((qam + m2) * (a + m2)), -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d = 1.0 + aa * d
            d = 1.0 / (d if abs(d) > mini else mini)
            c = 1.0 + aa / c
            c = c if abs(c) > mini else mini
            h *= d * c
        if abs(d * c - 1.0) < eps:
            break
    return h


def beta_cdf(x, a, b) -> float:
    """P(X ≤ x) pour X de loi Bêta(a, b) (fonction bêta incomplète régularisée)."""
    x, a, b = float(x), float(a), float(b)
    if not (a > 0 and b > 0) or math.isnan(x):
        return math.nan
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lf = a * math.log(x) + b * math.log1p(-x) - _log_beta(a, b)
    if x < (a + 1.0) / (a + b + 2.0):
        return min(1.0, math.exp(lf) * _fraction_beta(a, b, x) / a)
    return max(0.0, 1.0 - math.exp(lf) * _fraction_beta(b, a, 1.0 - x) / b)


def beta_quantile(p, a, b) -> float:
    """Quantile d'ordre p de la loi Bêta(a, b) : dichotomie gardée, accélérée par des pas de Newton."""
    p, a, b = float(p), float(a), float(b)
    if not (a > 0 and b > 0) or not 0 <= p <= 1:
        return math.nan
    if p in (0.0, 1.0):
        return p
    bas, haut = 0.0, 1.0
    x = a / (a + b)
    lc = -_log_beta(a, b)
    for _ in range(300):
        f = beta_cdf(x, a, b) - p
        if f == 0:
            return x
        if f > 0:
            haut = x
        else:
            bas = x
        try:
            suivant = x - f / math.exp(lc + (a - 1) * math.log(x) + (b - 1) * math.log1p(-x))
        except (ValueError, ZeroDivisionError, OverflowError):
            suivant = -1.0
        if not bas < suivant < haut:
            suivant = 0.5 * (bas + haut)
        if abs(suivant - x) <= 1e-14 * max(suivant, 1e-300) or haut - bas <= 1e-15 * max(haut, 1e-300):
            return suivant
        x = suivant
    return x


def _gamma_sup_echelle(s, z, eps=1e-15, iters=100000) -> float:
    """exp(z) × Γ(s, z), Γ(s, z) = fonction gamma incomplète supérieure. Série si z < s + 1, fraction continue sinon."""
    if z <= 0:
        return math.gamma(s)
    if z < s + 1.0:
        terme = somme = 1.0 / s
        for n in range(1, iters):
            terme *= z / (s + n)
            somme += terme
            if abs(terme) < abs(somme) * eps:
                break
        return math.exp(z) * math.gamma(s) - z ** s * somme
    mini = 1e-300
    b = z + 1.0 - s
    c, d = 1.0 / mini, 1.0 / b
    h = d
    for i in range(1, iters):
        an = -i * (i - s)
        b += 2.0
        d = an * d + b
        d = 1.0 / (d if abs(d) > mini else mini)
        c = b + an / c
        c = c if abs(c) > mini else mini
        h *= d * c
        if abs(d * c - 1.0) < eps:
            break
    return z ** s * h


# ---------------------------------------------------------------------------
# 2. Kaplan-Meier
# ---------------------------------------------------------------------------
def kaplan_meier(t, evenement=None) -> pd.DataFrame:
    """Survie de Kaplan-Meier. t : durées ; evenement : 1 = défaillance, 0 = censuré (pièce encore en service à t).
    Sans `evenement`, toutes les durées sont des défaillances. Une pièce censurée à la date u est encore comptée
    « à risque » à u (convention usuelle). Une ligne par date de défaillance : t, à risque, défaillances, S(t)."""
    t = np.asarray(t, float)
    e = np.ones(len(t), int) if evenement is None else np.asarray(evenement, float)
    ok = np.isfinite(t) & np.isfinite(e)
    t, e = t[ok], e[ok].astype(int)
    s, out = 1.0, []
    for u in np.unique(t[e == 1]):
        n = int((t >= u).sum())
        d = int(((t == u) & (e == 1)).sum())
        s *= 1 - d / n
        out.append((u, n, d, s))
    return pd.DataFrame(out, columns=["t", "à risque", "défaillances", "S(t)"])


# ---------------------------------------------------------------------------
# 3. Forme de Weibull
# ---------------------------------------------------------------------------
def _seuil_vraisemblance(niveau: float) -> float:
    """Chute de log-vraisemblance qui borne l'intervalle : la moitié du quantile du khi-deux à 1 degré de liberté."""
    return 0.5 * NormalDist().inv_cdf(0.5 + niveau / 2.0) ** 2


def _pct(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def _noms_bornes(niveau: float) -> tuple[str, str]:
    """Noms des colonnes d'un intervalle : 0,90 → (« k bas (5 %) », « k haut (95 %) »)."""
    q = 100 * (1 - niveau) / 2
    return f"k bas ({_pct(round(q, 4))} %)", f"k haut ({_pct(round(100 - q, 4))} %)"


def weibull_mle(t, evenement=None, troncature=None, n_min=None) -> dict:
    """Weibull (forme k, échelle λ) par maximum de vraisemblance, avec intervalles sur k.

    evenement  : 1 défaillance, 0 censure à droite (pièce encore en service à t). Défaut : toutes défaillances.
    troncature : fenêtre W en jours si l'on n'observe QUE les défaillances survenues dans les W jours après la pose
                 (fichier de défaillances précoces, sans survivants). Le calcul est alors celui de `weibull_tronque` :
                 délais en jours entiers, vraisemblance discrète tronquée, λ non rapporté.
    n_min      : nombre minimal de défaillances (défaut : 3 sans troncature, MIN_DEFAILLANCES_FORME avec).

    Sans troncature (données complètes ou censurées à droite, le cas où des survivants seront fournis) :
    vraisemblance continue. Pour k fixé, λ a une solution explicite, λ(k) = (Σ t^k / r)^(1/k) avec r défaillances ;
    il reste une équation à une inconnue en k, strictement décroissante, résolue par dichotomie (solution unique).
    L'intervalle sur k est celui de la vraisemblance profilée. Une durée nulle est comptée une demi-journée
    (défaillance le jour de la pose) : la densité continue n'est pas définie en 0.
    Renvoie k, lambda, n, défaillances, -logL, les bornes de k (« k bas (5 %) », « k haut (95 %) », « k bas (2,5 %) »,
    « k haut (97,5 %) ») et une note.
    """
    if troncature is not None and np.isfinite(troncature) and troncature > 0:
        if evenement is not None and np.any(np.asarray(evenement, float) == 0):
            raise ValueError("troncature et censure ne se combinent pas : un fichier tronqué ne contient pas de survivants")
        return weibull_tronque(t, troncature, n_min=MIN_DEFAILLANCES_FORME if n_min is None else n_min)
    n_min = 3 if n_min is None else n_min
    t = np.asarray(t, float)
    e = np.ones(len(t)) if evenement is None else np.asarray(evenement, float)
    ok = np.isfinite(t) & np.isfinite(e) & (t >= 0)
    t, e = t[ok], (e[ok] > 0).astype(float)
    r = int(e.sum())
    res = {"k": np.nan, "lambda": np.nan, "n": int(len(t)), "défaillances": r, "-logL": np.nan, "note": ""}
    for niveau in NIVEAUX_K:
        res.update(dict.fromkeys(_noms_bornes(niveau), np.nan))
    if r < n_min:
        res["note"] = f"moins de {n_min} défaillances"
        return res
    nuls = int((t == 0).sum())
    t = np.where(t == 0, 0.5, t)
    tmax = float(t.max())
    ls = np.log(t / tmax)                                    # durées rapportées à la plus longue : pas de dépassement
    m = float((e * ls).sum() / r)                            # moyenne des log-durées des défaillances

    def score(k):                                            # dérivée de la log-vraisemblance profilée, à un facteur r près
        w = np.exp(k * ls)
        return 1.0 / k + m - float((w * ls).sum() / w.sum())

    def profil(k):
        return r * math.log(k) + (k - 1) * r * m - r * math.log(float(np.exp(k * ls).sum()) / r)

    bas, haut = 1e-3, 1e3
    if not (score(bas) > 0 > score(haut)):
        res["note"] = "durées de défaillance toutes identiques : forme non estimable"
        return res
    for _ in range(200):
        mil = math.sqrt(bas * haut)
        bas, haut = (mil, haut) if score(mil) > 0 else (bas, mil)
        if haut / bas < 1 + 1e-13:
            break
    k = math.sqrt(bas * haut)
    lam = tmax * (float(np.exp(k * ls).sum()) / r) ** (1.0 / k)
    logl = r * math.log(k) - r * k * math.log(lam) + (k - 1) * float((e * np.log(t)).sum()) - r
    res.update({"k": k, "lambda": lam, "-logL": -logl})
    sommet = profil(k)
    for niveau in NIVEAUX_K:
        cible = sommet - _seuil_vraisemblance(niveau)
        bornes = []
        for dedans, dehors in ((k, 1e-3), (k, 1e3)):         # le profil monte jusqu'à k puis descend : une racine de chaque côté
            if profil(dehors) >= cible:                      # intervalle non borné de ce côté dans la plage explorée
                bornes.append(dehors)
                continue
            for _ in range(200):
                mil = math.sqrt(dedans * dehors)
                if profil(mil) >= cible:
                    dedans = mil
                else:
                    dehors = mil
                if abs(math.log(dehors / dedans)) < 1e-12:
                    break
            bornes.append(math.sqrt(dedans * dehors))
        res.update(dict(zip(_noms_bornes(niveau), bornes)))
    notes = []
    if nuls:
        notes.append(f"{nuls} durée(s) nulle(s) comptée(s) une demi-journée")
    if r < len(t):
        notes.append(f"{len(t) - r} pièce(s) encore en service (censure à droite)")
    res["note"] = " ; ".join(notes)
    return res


_V_GRILLE = np.linspace(math.log(1e-5), math.log(1e6), 26)     # grille de u = ((W + 1) / λ)^k, en logarithme


def _profil_tronque(logk, lx, ly, c, iters=16):
    """Pour chaque k : maximum sur λ de la log-vraisemblance discrète tronquée.

    λ est parcouru par u = ((W + 1) / λ)^k, de 1e-5 à 1e6 sur une grille log-espacée, puis affiné par section dorée
    autour du meilleur point ; la limite u → 0 (λ infini devant la fenêtre) est ajoutée explicitement.
    Renvoie (maximum, log u du maximum [−inf à la limite], valeur à la limite λ infini)."""
    k = np.exp(np.atleast_1d(np.asarray(logk, float)))
    n = float(c.sum())
    grille = _V_GRILLE
    with np.errstate(all="ignore"):
        xk = np.exp(k[:, None] * lx[None, :])                                         # (d / T)^k, 0 pour d = 0
        delta = np.exp(k[:, None] * ly[None, :]) * -np.expm1(k[:, None] * (lx - ly)[None, :])   # ((d+1)/T)^k − (d/T)^k
        l0 = np.log(delta) @ c
        l0 = np.where(np.isfinite(l0), l0, -np.inf)

        def f(v):                                                                     # v (K, U) → log-vraisemblance (K, U)
            u = np.exp(v)
            ll = (-u[:, :, None] * xk[:, None, :] + np.log(-np.expm1(-u[:, :, None] * delta[:, None, :]))) @ c - n * np.log(-np.expm1(-u))
            return np.where(np.isfinite(ll), ll, -np.inf)

        g = f(np.broadcast_to(grille, (len(k), len(grille))))
        j = g.argmax(axis=1)
        a, b = grille[np.maximum(j - 1, 0)], grille[np.minimum(j + 1, len(grille) - 1)]
        phi = 0.6180339887498949
        x1, x2 = b - phi * (b - a), a + phi * (b - a)
        f1, f2 = f(x1[:, None])[:, 0], f(x2[:, None])[:, 0]
        for _ in range(iters):
            gauche = f1 >= f2                                                         # le maximum est dans [a, x2]
            a, b = np.where(gauche, a, x1), np.where(gauche, x2, b)
            n1, n2 = np.where(gauche, b - phi * (b - a), x2), np.where(gauche, x1, a + phi * (b - a))
            fe = f(np.where(gauche, n1, n2)[:, None])[:, 0]
            f1, f2 = np.where(gauche, fe, f2), np.where(gauche, f1, fe)
            x1, x2 = n1, n2
    lignes = np.arange(len(k))
    cand_v = np.stack([grille[j], x1, x2], axis=1)
    cand_f = np.stack([g[lignes, j], f1, f2], axis=1)
    m = cand_f.argmax(axis=1)
    best_f, best_v = cand_f[lignes, m], cand_v[lignes, m]
    limite = l0 >= best_f
    return np.where(limite, l0, best_f), np.where(limite, -np.inf, best_v), l0


def weibull_tronque(jours, fenetre, niveaux=NIVEAUX_K, n_min=MIN_DEFAILLANCES_FORME) -> dict:
    """Forme k de Weibull à partir de défaillances précoces seules : délais en jours ENTIERS (0 = le jour de la pose),
    observés uniquement s'ils sont dans la fenêtre 0..W. Aucun survivant, aucun dénominateur.

    Vraisemblance (discrète, tronquée à droite), F étant la fonction de répartition de Weibull(k, λ) :
        P(D = d | D ≤ W) = [F(d + 1) − F(d)] / F(W + 1),   d = 0, 1, …, W.
    Un délai de 0 jour est un intervalle [0, 1[ comme les autres : il n'est ni déplacé ni écarté.

    Estimation : vraisemblance profilée. Pour chaque k, la vraisemblance est maximisée sur λ, parcouru sur une grille
    log-espacée très large (de λ très petit devant la fenêtre jusqu'à λ infini), puis affinée par section dorée ;
    le profil est ensuite maximisé en k sur une grille log-espacée de K_MIN à K_MAX, affinée deux fois. Pas de
    simplexe ni de point de départ : la recherche sur grille ne peut pas rester sur un optimum local.

    λ n'est PAS identifiable : quand λ est grand devant W, la loi tronquée ne dépend plus de λ
    (P(D = d) tend vers [(d+1)^k − d^k] / (W+1)^k). λ n'est donc jamais rapporté, et aucune durée de vie n'en est tirée.

    Intervalles sur k : ceux de la vraisemblance profilée (ensemble des k dont la log-vraisemblance profilée est à
    moins d'un demi-quantile du khi-deux du maximum). Choisi plutôt qu'un bootstrap paramétrique parce qu'il tient
    compte de λ inconnu sans le fixer à son estimation (le bootstrap simulerait à λ estimé, justement non
    identifiable), qu'il est asymétrique comme l'incertitude sur une forme, et qu'il coûte un seul ajustement.
    Sa couverture est vérifiée par simulation dans tests/test_fiabilite.py. Si le profil passe sous le seuil puis
    repasse au-dessus, l'intervalle rendu est l'enveloppe (le plus large).

    Renvoie k, lambda (toujours NaN), n, défaillances, fenêtre, -logL, « échelle » (ce que les données disent de λ),
    les bornes de k pour chaque niveau et une note.
    """
    d = np.asarray(jours, float)
    d = np.floor(d[np.isfinite(d)])
    W = int(math.floor(float(fenetre)))
    hors = int(((d < 0) | (d > W)).sum())
    d = d[(d >= 0) & (d <= W)].astype(int)
    n = int(len(d))
    res = {"k": np.nan, "lambda": np.nan, "n": n, "défaillances": n, "fenêtre": W, "-logL": np.nan, "échelle": "", "note": ""}
    for niveau in niveaux:
        res.update(dict.fromkeys(_noms_bornes(niveau), np.nan))
    notes = [f"{hors} délai(s) hors de la fenêtre 0 à {W} j écarté(s)"] if hors else []
    if n < n_min:
        res["note"] = " ; ".join([f"moins de {n_min} défaillances datées : forme non estimée"] + notes)
        return res
    vals, c = np.unique(d, return_counts=True)
    if len(vals) < 2:
        res["note"] = " ; ".join(["délais tous identiques : forme non estimable"] + notes)
        return res
    T = W + 1.0
    c = c.astype(float)
    with np.errstate(divide="ignore"):
        lx, ly = np.log(vals / T), np.log((vals + 1.0) / T)

    def profil(g):
        return _profil_tronque(g, lx, ly, c)

    g = np.linspace(math.log(K_MIN), math.log(K_MAX), 49)
    p, v, l0 = profil(g)
    for _ in range(2):                                       # deux affinages autour du meilleur point
        i = int(p.argmax())
        if i in (0, len(g) - 1):
            break
        ajout = np.linspace(g[i - 1], g[i + 1], 18)[1:-1]
        pa, va, la = profil(ajout)
        ordre = np.argsort(np.r_[g, ajout], kind="stable")
        g, p, v, l0 = np.r_[g, ajout][ordre], np.r_[p, pa][ordre], np.r_[v, va][ordre], np.r_[l0, la][ordre]
    i = int(p.argmax())
    if i in (0, len(g) - 1) or not np.isfinite(p[i]):
        res["note"] = " ; ".join([f"forme en butée de la plage explorée ({_pct(K_MIN)} à {_pct(K_MAX)}) : non estimable"] + notes)
        return res
    # Sommet d'une parabole par les trois meilleurs points : dernier affinage du maximum.
    den = (g[i - 1] - g[i]) * (g[i - 1] - g[i + 1]) * (g[i] - g[i + 1])
    A = (g[i + 1] * (p[i] - p[i - 1]) + g[i] * (p[i - 1] - p[i + 1]) + g[i - 1] * (p[i + 1] - p[i])) / den
    B = (g[i + 1] ** 2 * (p[i - 1] - p[i]) + g[i] ** 2 * (p[i + 1] - p[i - 1]) + g[i - 1] ** 2 * (p[i] - p[i + 1])) / den
    if A < 0 and g[i - 1] < -B / (2 * A) < g[i + 1] and abs(-B / (2 * A) - g[i]) > 1e-12:
        ps, vs, ls_ = profil(np.array([-B / (2 * A)]))
        ordre = np.argsort(np.r_[g, -B / (2 * A)], kind="stable")
        g, p, v, l0 = np.r_[g, -B / (2 * A)][ordre], np.r_[p, ps][ordre], np.r_[v, vs][ordre], np.r_[l0, ls_][ordre]
        i = int(p.argmax())
    sommet, gk = float(p[i]), float(g[i])
    res.update({"k": math.exp(gk), "-logL": -sommet})

    # Bornes : pour chaque niveau et de chaque côté, le point le plus éloigné encore au-dessus du seuil, puis trois
    # resserrements (8 points) de l'intervalle où le profil traverse le seuil, et une interpolation linéaire.
    taches = []                                              # [niveau, côté, intérieur g, valeur, extérieur g, valeur, en butée]
    for niveau in niveaux:
        cible = sommet - _seuil_vraisemblance(niveau)
        dedans = np.flatnonzero(p >= cible)
        for cote, m in (("bas", int(dedans[0])), ("haut", int(dedans[-1]))):
            ext = m - 1 if cote == "bas" else m + 1
            if ext < 0 or ext >= len(g):
                taches.append([niveau, cote, g[m], p[m], g[m], p[m], True, cible])
            else:
                taches.append([niveau, cote, g[m], p[m], g[ext], p[ext], False, cible])
    for _ in range(3):
        actives = [t for t in taches if not t[6]]
        if not actives:
            break
        points = np.concatenate([np.linspace(t[2], t[4], 10)[1:-1] for t in actives])   # de l'intérieur vers l'extérieur
        valeurs = profil(points)[0]
        for q, t in enumerate(actives):
            gs = np.r_[t[2], points[8 * q: 8 * q + 8], t[4]]
            ps = np.r_[t[3], valeurs[8 * q: 8 * q + 8], t[5]]
            m = int(np.flatnonzero(ps >= t[7])[-1])          # le plus éloigné encore dedans (enveloppe)
            m = min(m, len(gs) - 2)
            t[2], t[3], t[4], t[5] = gs[m], ps[m], gs[m + 1], ps[m + 1]
    butees = []
    for niveau, cote, gi, pi, ge, pe, butee, cible in taches:
        if butee:
            borne = K_MIN if cote == "bas" else K_MAX
            butees.append(cote)
        else:
            borne = math.exp(gi + (ge - gi) * (pi - cible) / (pi - pe)) if pi > pe else math.exp(gi)
        res[_noms_bornes(niveau)[0 if cote == "bas" else 1]] = borne
    # Ce que les données disent de l'échelle : λ infini est-il aussi vraisemblable que le maximum ?
    limite = float(np.max(l0))
    if sommet - limite <= _seuil_vraisemblance(0.90):
        res["échelle"] = "non identifiable"
        notes.insert(0, "échelle λ non identifiable (données compatibles avec une durée de vie très grande devant la fenêtre) : aucune durée de vie n'en est tirée")
    else:
        res["échelle"] = "faiblement identifiable"
        notes.insert(0, "échelle λ faiblement identifiable (fenêtre tronquée, pas de survivants) : aucune durée de vie n'en est tirée")
    if butees:
        notes.append(f"intervalle sur k non borné dans la plage explorée (côté {' et '.join(sorted(set(butees)))})")
    res["note"] = " ; ".join(notes)
    return res


def lecture_forme(k, k_bas=None, k_haut=None, n=None, n_min=MIN_DEFAILLANCES_FORME) -> str:
    """Lecture de la forme k de Weibull.

    Avec un intervalle (k_bas, k_haut), la lecture ne s'engage que si l'intervalle le permet :
      « mortalité infantile » seulement si la borne haute est sous 1 ;
      « usure » seulement si la borne basse est au-dessus de 1 ;
      « aléatoire (compatible avec k = 1) » seulement si l'intervalle contient 1 et tient dans ZONE_K_ALEATOIRE ;
      sinon « indéterminé : pas assez de défaillances pour conclure ».
    `n` (nombre de défaillances), s'il est donné et inférieur à n_min, donne « inconnu ».
    Sans intervalle (appel à un seul argument, pour une valeur théorique de k) : lecture de la valeur seule,
    « aléatoire » entre 0,9 et 1,1.
    """
    if k is None or not np.isfinite(k):
        return "inconnu"
    infantile = "mortalité infantile : une pièce qui a déjà tourné est plus sûre qu'une neuve ; test/déverminage utile"
    usure = "usure : le risque croît avec l'âge ; réemploi seulement si l'âge du donneur est connu et faible"
    if k_bas is None and k_haut is None:
        if k < 0.9:
            return infantile
        if k <= 1.1:
            return "aléatoire : l'âge ne change pas le risque ; réemploi neutre"
        return usure
    if n is not None and np.isfinite(n) and n < n_min:
        return "inconnu"
    indetermine = "indéterminé : pas assez de défaillances pour conclure"
    if k_bas is None or k_haut is None or not (np.isfinite(k_bas) and np.isfinite(k_haut)):
        return indetermine
    if k_haut < 1:
        return infantile
    if k_bas > 1:
        return usure
    if ZONE_K_ALEATOIRE[0] <= k_bas and k_haut <= ZONE_K_ALEATOIRE[1]:
        return "aléatoire (compatible avec k = 1) : l'âge ne change pas le risque ; réemploi neutre"
    return indetermine


def survie_weibull(t, k, lam):
    return np.exp(-(np.asarray(t, float) / lam) ** k)


def survie_conditionnelle(age, duree, k, lam):
    """P(la pièce survit `duree` de plus | elle a déjà `age`) = R(age+duree)/R(age).
    Calculée dans l'exposant : reste définie quand R(age) est trop petit pour être représenté."""
    age, duree = np.asarray(age, float), np.asarray(duree, float)
    return np.exp((age / lam) ** k - ((age + duree) / lam) ** k)


def vie_residuelle_moyenne(age, k, lam, horizon_mult=None, n=None):
    """Durée de vie résiduelle moyenne MRL(a) = ∫ R(a+u) du / R(a) d'une loi de Weibull(k, λ).

    Forme exacte : MRL(a) = (λ / k) · exp(z) · Γ(1/k, z), avec z = (a/λ)^k et Γ la fonction gamma incomplète
    supérieure. Pour k = 1 elle vaut λ quel que soit l'âge ; à l'âge 0 elle vaut λ·Γ(1 + 1/k).
    `horizon_mult` et `n` (ancienne intégration numérique) sont acceptés et ignorés.
    """
    def une(a):
        if not (np.isfinite(a) and a >= 0 and k > 0 and lam > 0):
            return np.nan
        return lam / k * _gamma_sup_echelle(1.0 / k, (a / lam) ** k)
    if np.ndim(age) == 0:
        return float(une(float(age)))
    return np.array([une(float(a)) for a in np.ravel(age)]).reshape(np.shape(age))


# ---------------------------------------------------------------------------
# 4. Taux de défaillance précoce et rapport au neuf
# ---------------------------------------------------------------------------
def _beta_du_taux(defaillances, poses, prior_moy=None, prior_force=20):
    """Paramètres (a, b) de la loi Bêta a posteriori du taux, ou None si le taux n'est pas calculable."""
    if poses is None or defaillances is None:
        return None
    try:
        d, p = float(defaillances), float(poses)
    except (TypeError, ValueError):
        return None
    if not (np.isfinite(p) and p > 0 and np.isfinite(d) and 0 <= d <= p):
        return None                                           # plus de défaillances que de pièces posées : dénominateur incohérent
    if prior_moy is None or not np.isfinite(prior_moy) or not 0 < prior_moy < 1:
        a0, b0 = 0.5, 0.5
    else:
        a0, b0 = prior_moy * prior_force, (1 - prior_moy) * prior_force
    return a0 + d, b0 + p - d


def taux_bayes(defaillances, poses, prior_moy=None, prior_force=20, n_tirages=None) -> dict:
    """Taux de défaillance précoce (défaillances / pièces posées) : loi Bêta a posteriori, moyenne et intervalle à 90 %.

    Sans a priori : Jeffreys Bêta(0,5 ; 0,5). Avec a priori de famille (moyenne m, force n0) :
    Bêta(m·n0 ; (1−m)·n0) — les références à faible effectif sont tirées vers leur famille.
    Les bornes sont les quantiles exacts à 5 % et 95 % (aucun tirage : `n_tirages` est accepté et ignoré).
    Dénominateur absent, nul, ou plus petit que le nombre de défaillances : taux inconnu (NaN), jamais 0 ni 100 %.
    """
    ab = _beta_du_taux(defaillances, poses, prior_moy, prior_force)
    if ab is None:
        return {"Taux ELF moyen": np.nan, "IC90 bas": np.nan, "IC90 haut": np.nan}
    a, b = ab
    return {"Taux ELF moyen": a / (a + b), "IC90 bas": beta_quantile(0.05, a, b), "IC90 haut": beta_quantile(0.95, a, b)}


def _generateur(rng, *cle):
    """Générateur aléatoire : un Generator est rendu tel quel ; un entier (ou None = GRAINE) donne un générateur
    neuf, propre à `cle` : le résultat ne dépend ni de l'ordre des appels ni des autres lignes."""
    if isinstance(rng, np.random.Generator):
        return rng
    graine = GRAINE if rng is None else int(rng)
    return np.random.default_rng([graine] + [zlib.crc32(str(x).encode("utf-8")) for x in cle])


def lecture_rapport(bas, haut) -> str:
    """Lecture du rapport des taux (origine / neuve) d'après son intervalle à 90 %."""
    if bas is None or haut is None or not (np.isfinite(bas) and np.isfinite(haut)):
        return "inconnu"
    if bas > 1:
        return "moins fiable que le neuf"
    if haut < 1:
        return "plus fiable que le neuf"
    if ZONE_RAPPORT_EQUIVALENT[0] <= bas and haut <= ZONE_RAPPORT_EQUIVALENT[1]:
        return "équivalent au neuf"
    return "indéterminé"


def rapport_taux(defaillances, poses, defaillances_neuf, poses_neuf, n_tirages=20000, rng=None) -> dict:
    """Rapport du taux de défaillance précoce d'une origine à celui de la pièce neuve, avec son incertitude.

    Les deux taux ont chacun leur loi Bêta a posteriori (a priori de Jeffreys) ; on tire `n_tirages` couples
    indépendants et on lit les quantiles du rapport. `rng` : graine entière ou Generator (défaut : GRAINE).
    « Rapport au neuf (taux) » reste le rapport des deux taux moyens ; les bornes sont les quantiles à 5 % et 95 % du
    rapport, et la probabilité est celle que le taux de l'origine dépasse celui du neuf.
    """
    vide = {"Rapport au neuf (taux)": np.nan, "Rapport bas (5 %)": np.nan, "Rapport haut (95 %)": np.nan,
            "Probabilité d'être moins fiable que le neuf": np.nan, "Lecture du rapport": "inconnu"}
    x, y = _beta_du_taux(defaillances, poses), _beta_du_taux(defaillances_neuf, poses_neuf)
    if x is None or y is None:
        return vide
    g = _generateur(rng, "rapport", defaillances, poses, defaillances_neuf, poses_neuf)
    r = g.beta(x[0], x[1], n_tirages) / g.beta(y[0], y[1], n_tirages)
    bas, haut = (float(q) for q in np.quantile(r, [0.05, 0.95]))
    return {"Rapport au neuf (taux)": (x[0] / (x[0] + x[1])) / (y[0] / (y[0] + y[1])), "Rapport bas (5 %)": bas, "Rapport haut (95 %)": haut,
            "Probabilité d'être moins fiable que le neuf": float(np.mean(r > 1)), "Lecture du rapport": lecture_rapport(bas, haut)}


# A priori physiques (physics-of-failure), à confirmer par la fiche technique de chaque référence.
def vie_condensateur_h(vie_nominale_h, t_nominale_c, t_service_c):
    """Règle d'Arrhenius des électrolytiques : la vie double tous les 10 °C sous la température nominale."""
    return vie_nominale_h * 2 ** ((t_nominale_c - t_service_c) / 10)


def cycles_igbt(delta_tj, A=None, n=5.0):
    """Coffin-Manson (LESIT) : Nf = A·ΔTj^-n. A dépend du module : fiche fabricant ou essai. Sans A : rapport relatif.
    Une amplitude ΔTj nulle ou négative n'a pas de sens : NaN."""
    if delta_tj is None or not np.isfinite(delta_tj) or delta_tj <= 0:
        return np.nan
    return (A or 1.0) * float(delta_tj) ** (-n)


# ---------------------------------------------------------------------------
# 5. Agrégation fiabilité depuis le cache ELF
# ---------------------------------------------------------------------------
COLONNES_FIABILITE = ["Référence", "Origine posée", "Défaillances ELF", "elf_days renseigné", "elf_days médiane", "Part à J0 (DOA)",
                      "Forme Weibull k", "k bas (5 %)", "k haut (95 %)", "k bas (2,5 %)", "k haut (97,5 %)", "Lecture de la forme", "Note",
                      "Fenêtre (j)", "Pièces posées (même période)", "Taux ELF moyen", "IC90 bas", "IC90 haut", "Rapport au neuf (taux)",
                      "Rapport bas (5 %)", "Rapport haut (95 %)", "Probabilité d'être moins fiable que le neuf", "Lecture du rapport"]


def fiabilite_par_reference(elf: pd.DataFrame, fenetre_elf=None, poses: pd.Series | None = None, graine: int = GRAINE) -> pd.DataFrame:
    """Une ligne par (référence de base, origine de la pièce posée).

    elf         : cache du fichier de fiabilité (colonnes replacement_part_no, elf_days en jours entiers, …)
    fenetre_elf : fenêtre W du fichier, en jours. Non fournie, elle est prise égale au plus grand délai du fichier
                  (signalé dans la note) : la fournir dès qu'elle est connue.
    poses       : pièces posées sur la MÊME période que le fichier, indexées par (base, origine). Sans elle, aucun
                  taux n'est calculé (le fichier ne contient que des défaillances).
    graine      : graine des tirages du rapport au neuf ; chaque ligne a son propre générateur, déduit de la graine
                  et de la référence, donc le résultat d'une ligne ne dépend pas des autres.

    Forme : `weibull_tronque` (vraisemblance discrète tronquée) ; intervalle à 90 % dans « k bas (5 %) » et
    « k haut (95 %) ». La « Lecture de la forme » repose sur l'intervalle à 95 % (« k bas (2,5 %) »,
    « k haut (97,5 %) »), plus large : quand le risque est en réalité constant (k = 1), elle n'annonce à tort une
    mortalité infantile ou une usure que dans 5 % des cas environ, et non 10 %.
    Rapport au neuf : `rapport_taux` ; lecture d'après l'intervalle à 90 % du rapport (probabilité d'au moins 95 %
    que l'origine soit moins fiable, ou plus fiable, que le neuf).
    """
    if elf is None or not len(elf) or "replacement_part_no" not in elf:
        return pd.DataFrame(columns=COLONNES_FIABILITE)
    d = elf.copy()
    d["Base"] = d["replacement_part_no"].map(base_ref)
    d["Origine"] = d["replacement_part_no"].map(origine)
    d["elf_days"] = pd.to_numeric(d["elf_days"], errors="coerce") if "elf_days" in d else np.nan
    d.loc[d["elf_days"] < 0, "elf_days"] = np.nan             # un délai négatif est une erreur de date : délai inconnu
    if poses is not None:                               # clés normalisées : une référence lue comme nombre doit joindre
        poses = poses.copy()
        poses.index = pd.MultiIndex.from_tuples([(base_ref(re.sub(r"\.0$", "", str(b))), str(o)) for b, o in poses.index])
        poses = poses.groupby(level=[0, 1]).sum()
    fournie = fenetre_elf is not None and np.isfinite(fenetre_elf) and fenetre_elf > 0
    W = float(fenetre_elf) if fournie else (float(np.nanmax(d["elf_days"])) if d["elf_days"].notna().any() else None)
    lignes = []
    for (b, o), g in d.groupby(["Base", "Origine"]):
        t = g["elf_days"].dropna().to_numpy()
        if len(t) and W is not None:
            w = weibull_tronque(t, W)
        else:
            w = {"k": np.nan, "note": "aucun délai renseigné"}
        b90, b95 = _noms_bornes(0.90), _noms_bornes(NIVEAU_LECTURE)
        notes = [w.get("note", "")]
        if np.isfinite(w["k"]):
            if not fournie:
                notes.append(f"fenêtre non fournie : prise égale au plus grand délai du fichier ({W:g} j)")
            if (np.isfinite(w[b90[1]]) and w[b90[1]] < 1 <= w[b95[1]]) or (np.isfinite(w[b90[0]]) and w[b95[0]] <= 1 < w[b90[0]]):
                notes.append("tendance visible sur l'intervalle à 90 %, non retenue par la lecture (intervalle à 95 %)")
        ligne = {"Référence": b, "Origine posée": o, "Défaillances ELF": len(g), "elf_days renseigné": len(t),
                 "elf_days médiane": np.median(t) if len(t) else np.nan,
                 "Part à J0 (DOA)": float(np.mean(t == 0)) if len(t) else np.nan,
                 "Forme Weibull k": w["k"], b90[0]: w.get(b90[0], np.nan), b90[1]: w.get(b90[1], np.nan),
                 b95[0]: w.get(b95[0], np.nan), b95[1]: w.get(b95[1], np.nan),
                 "Lecture de la forme": lecture_forme(w["k"], w.get(b95[0]), w.get(b95[1])) if np.isfinite(w["k"]) else "inconnu",
                 "Fenêtre (j)": W if W is not None else np.nan}
        n_pose = poses.get((b, o), np.nan) if poses is not None else np.nan
        ligne["Pièces posées (même période)"] = n_pose
        ligne.update(taux_bayes(len(g), n_pose))
        if pd.notna(n_pose) and n_pose > 0 and len(g) > n_pose:
            notes.append("plus de défaillances que de pièces posées : dénominateur à vérifier, taux non calculé")
        ligne["Note"] = " ; ".join(x for x in notes if x)
        lignes.append(ligne)
    out = pd.DataFrame(lignes)
    if not len(out):
        return pd.DataFrame(columns=COLONNES_FIABILITE)
    neuf = out[out["Origine posée"].eq("Neuve")].set_index("Référence")
    rapports = []
    for _, r in out.iterrows():
        if r["Origine posée"] == "Neuve":
            connu = pd.notna(r["Taux ELF moyen"])
            rapports.append({"Rapport au neuf (taux)": 1.0 if connu else np.nan, "Rapport bas (5 %)": np.nan, "Rapport haut (95 %)": np.nan,
                             "Probabilité d'être moins fiable que le neuf": np.nan,
                             "Lecture du rapport": "référence (pièce neuve)" if connu else "inconnu"})
        elif r["Référence"] in neuf.index:
            n = neuf.loc[r["Référence"]]
            rapports.append(rapport_taux(r["Défaillances ELF"], r["Pièces posées (même période)"], n["Défaillances ELF"],
                                         n["Pièces posées (même période)"], rng=_generateur(graine, r["Référence"], r["Origine posée"])))
        else:
            rapports.append(rapport_taux(None, None, None, None))
    out = pd.concat([out, pd.DataFrame(rapports, index=out.index)], axis=1)
    return out[COLONNES_FIABILITE]
