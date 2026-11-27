"""Chiffres, tableaux et figures du manuscrit : du dossier vers LaTeX.

    python -m erc.papier               vos données : écrit papier/site/ (jamais versionné, jamais dans l'archive)
    python -m erc.papier --demo        données de démonstration : écrit papier/genere/
    python -m erc.papier --compiler    compile ensuite le manuscrit (manuscrit_site.pdf, ou manuscrit.pdf en démonstration)
    python -m erc.papier --demo --overleaf   fabrique en plus l'archive à déposer sur Overleaf pour modifier le texte
    python -m erc.papier --echelle 0.4 multiplie tous les montants de l'étude de cas par un facteur que vous ne publiez pas

Deux familles de chiffres, que le manuscrit ne mélange jamais :

  expériences synthétiques   instances tirées au hasard, graine fixe. Elles vérifient les résultats mathématiques et
                             mesurent les algorithmes ; elles ne disent rien du site.
  étude de cas               ce que le dossier calcule sur les données du site. Tant qu'il tourne sur les données de
                             démonstration, le manuscrit porte un bandeau qui le dit.

Rien de nominatif ne sort : ni code article, ni description, ni nom de type d'unité. Une valeur que le dossier ne sait
pas calculer s'écrit « n/a », jamais zéro.
"""
from __future__ import annotations

import math
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from . import ligne as mod_ligne

GRAINE = 2026
TAUX = 45.0                                    # € par heure opérateur, expériences synthétiques
COULEURS = ("#257de0", "#f47230", "#00b894")   # palette vérifiée (daltonisme) ; chaque série a aussi son trait et son marqueur
TRAITS = ("-", "--", ":")
MARQUEURS = ("o", "s", "^")
METHODES = {"moyenne": "Historical mean", "croston": "Croston", "sba": "Syntetos--Boylan", "tsb": "Teunter--Syntetos--Babai",
            "gamma_poisson": "Pooled Gamma--Poisson", "structurel": "Structural (Beta--binomial)"}


# --------------------------------------------------------------------------- mise en forme
def _fini(v) -> bool:
    try:
        return v is not None and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def nombre(v, decimales: int = 0) -> str:
    """12 345,6 → « 12\\,345.6 » ; inconnu → « n/a »."""
    return f"{float(v):,.{decimales}f}".replace(",", r"\,") if _fini(v) else "n/a"


def pourcent(v, decimales: int = 0) -> str:
    return f"{100 * float(v):.{decimales}f}\\%" if _fini(v) else "n/a"


def duree(ms) -> str:
    """Une durée en millisecondes, à deux chiffres significatifs."""
    if not _fini(ms):
        return "---"
    return f"{ms:.2g}" if ms < 100 else nombre(ms)


def petit(v, decimales: int = 4) -> str:
    """Une probabilité : décimale, ou en puissance de dix quand elle s'écrirait 0,0000."""
    if not _fini(v):
        return "n/a"
    if v == 0:
        return "0"
    if v >= 0.5 * 10 ** (-decimales):
        return f"{v:.{decimales}f}"
    m, e = f"{v:.1e}".split("e")
    return f"${m}\\times10^{{{int(e)}}}$"


def signe(v, decimales: int = 3) -> str:
    """Un écart avec son signe : « $+0.012$ », « $-0.045$ »."""
    return f"${float(v):+.{decimales}f}$" if _fini(v) else "n/a"


def _lignes(rangs) -> str:
    return "\n".join(" & ".join(map(str, r)) + r" \\" for r in rangs) + "\n"


# --------------------------------------------------------------------------- A. expériences synthétiques
def type_synthetique(rng, n: int) -> dict:
    """Un type d'unité à n composants, données complètes."""
    pieces = {f"C{j}": {"n_par_fru": float(rng.integers(1, 4)), "extraction_min": float(rng.uniform(1, 30)), "test_min": float(rng.uniform(0, 20)),
                        "tri_min": float(rng.uniform(0.5, 8)), "p_reutilisable": float(rng.uniform(0, 1)), "valeur_eur": float(rng.uniform(0, 120)),
                        "poids_kg": float(rng.uniform(0.01, 3)), "prix_recycleur_eur_kg": float(rng.uniform(0, 6)),
                        "transport_eur": float(rng.uniform(0, 3)), "delai_semaines": 0.0, "valeur_semaine_eur": 0.0} for j in range(n)}
    return {"scrap_an": float(rng.integers(20, 200)), "poids_fru_kg": float(rng.uniform(5, 30)), "ouverture_min": float(rng.uniform(5, 40)),
            "ouverture_tri_min": float(rng.uniform(1, 15)), "pieces": pieces}


def exp_prix(graine: int = GRAINE, tailles_enum=(4, 8, 10, 12), tailles=(50, 200, 1000), prix: int = 20) -> dict:
    """Proposition 1 : le meilleur plan d'un type sans énumération. Écart avec l'énumération, et temps de calcul
    (mise en place comprise) pour `prix` valeurs du prix de l'heure. Le seuil au-delà duquel le dossier cesse d'énumérer
    est levé le temps de la mesure."""
    rng = np.random.default_rng(graine)
    rangs, ecart, seuil = [], 0.0, mod_ligne.MAX_PIECES_ENUM
    try:
        for n in sorted(set(tailles_enum) | set(tailles)):
            frus = [dict(type_synthetique(rng, n), _c_trait=0.25) for _ in range(20 if n <= 8 else 3)]
            mus = rng.uniform(0, 80, prix)
            t0 = time.perf_counter()
            sep = [[o.meilleur(mu) for mu in mus] for o in (mod_ligne.Options(f, TAUX, separable=True) for f in frus)]
            t_sep, t_enum = (time.perf_counter() - t0) / len(frus), float("nan")
            if n in tailles_enum:
                mod_ligne.MAX_PIECES_ENUM = max(seuil, n)
                t0 = time.perf_counter()
                enu = [[o.meilleur(mu) for mu in mus] for o in (mod_ligne.Options(f, TAUX, separable=False) for f in frus)]
                t_enum = (time.perf_counter() - t0) / len(frus)
                ecart = max(ecart, max(abs((a[2] - mu * a[1]) - (b[2] - mu * b[1])) for x, y in zip(sep, enu) for a, b, mu in zip(x, y, mus)))
            rangs.append({"n": n, "plans": 3 ** n, "enum_ms": 1e3 * t_enum, "sep_ms": 1e3 * t_sep})
    finally:
        mod_ligne.MAX_PIECES_ENUM = seuil
        for n in [k for k in mod_ligne._CODES if k > seuil]:
            del mod_ligne._CODES[n]                              # tableaux d'énumération volumineux : rendus
    return {"rangs": rangs, "ecart": float(ecart), "prix": prix}


def exp_variabilite(graine: int = GRAINE, semaines: int = 52, types: int = 4, parts=(0.5, 0.8, 1.2)) -> dict:
    """Proposition 5 : l'écart de variabilité Γ, en part du résultat au flux moyen, selon la dispersion des arrivées
    et les heures disponibles (en part du besoin au flux moyen)."""
    rng = np.random.default_rng(graine)
    frus = {f"T{i}": type_synthetique(rng, int(rng.integers(3, 7))) for i in range(types)}
    moyennes = {f: float(rng.uniform(2, 8)) for f in frus}
    ligne = {"heures_operateur_an": None, "taux_horaire_eur": TAUX, "cout_traitement_eur_kg": 0.25, "cout_installation_eur": 0.0,
             "amortissement_ans": 5.0, "couts_fixes_annuels_eur": 0.0}
    besoin = mod_ligne.optimiser_ligne(ligne, {f: dict(d, scrap_an=moyennes[f] * semaines) for f, d in frus.items()})["resume"]["Heures utilisées / an"]
    lois = {"Constant": None, "Poisson": math.inf, "Negative binomial, $k=2$": 2.0, "Negative binomial, $k=0.5$": 0.5}
    rangs = []
    for nom, k in lois.items():
        tirage = lambda m: m if k is None else float(rng.poisson(m)) if math.isinf(k) else float(rng.negative_binomial(k, k / (k + m)))
        flux = pd.DataFrame([{"Semaine": s, "FRU": f, "FRU scrapées": tirage(m)} for s in range(semaines) for f, m in moyennes.items()])
        total = flux.groupby("Semaine")["FRU scrapées"].sum()
        r = {"loi": nom, "cv": float(total.std(ddof=0) / total.mean())}
        for part in parts:
            a = mod_ligne.resultat_par_periode(dict(ligne, heures_operateur_an=part * besoin), frus, flux, periodes_par_an=semaines).attrs
            fluide = a["Résultat du modèle annuel au flux moyen (€)"]
            r[part] = a["Coût de la variabilité du flux (€/an)"] / fluide if fluide > 0 else float("nan")
        rangs.append(r)
    return {"rangs": rangs, "parts": list(parts), "semaines": semaines, "types": types}


def borne_fusion(r: float, n: int, k: int) -> float:
    """Proposition 9 : probabilité au plus que la classe la plus probable ne soit pas la vraie après k affirmations
    indépendantes d'une source de fiabilité connue r, parmi n valeurs possibles."""
    q = (1.0 - r) / (n - 1)
    return min(1.0, (n - 1) * (1.0 - (math.sqrt(r) - math.sqrt(q)) ** 2) ** k)


def assertions_suffisantes(r: float, n: int, delta: float) -> int:
    """Plus petit nombre d'affirmations pour lequel la borne de la proposition 9 passe sous delta."""
    q = (1.0 - r) / (n - 1)
    rho = 1.0 - (math.sqrt(r) - math.sqrt(q)) ** 2
    return 1 if rho <= 0 else int(math.ceil(math.log((n - 1) / delta) / math.log(1.0 / rho)))


def exp_fusion(graine: int = GRAINE, n: int = 9, fiabilites=(0.6, 0.75, 0.9), nombres=(1, 3, 5, 9, 15), essais: int = 20000) -> dict:
    """Erreur simulée de la règle de fusion (classe la plus souvent nommée ; une égalité compte pour une erreur),
    contre la borne de la proposition 9."""
    rng = np.random.default_rng(graine)
    rangs = []
    for r in fiabilites:
        p = np.r_[r, np.full(n - 1, (1 - r) / (n - 1))]
        for k in nombres:
            c = rng.multinomial(k, p, size=essais)
            rangs.append({"r": r, "k": k, "erreur": float(np.mean(c[:, 0] <= c[:, 1:].max(axis=1))), "borne": borne_fusion(r, n, k)})
    return {"rangs": rangs, "n": n, "essais": essais}


def exp_strates(graine: int = GRAINE, n_acc: int = 800, n_file: int = 200, r_acc: float = 0.95, r_file: float = 0.55,
                k_acc: int = 20, k_file: int = 60, essais: int = 20000) -> dict:
    """Proposition 10 : fiabilité d'une source estimée sur les validations. Compter toutes les validations ensemble
    sous-estime la source quand la file de revue est plus visitée que les pièces acceptées ; par strates, non."""
    rng = np.random.default_rng(graine)
    vraie = (n_acc * r_acc + n_file * r_file) / (n_acc + n_file)
    j_acc = rng.hypergeometric(round(n_acc * r_acc), n_acc - round(n_acc * r_acc), k_acc, size=essais)
    j_file = rng.hypergeometric(round(n_file * r_file), n_file - round(n_file * r_file), k_file, size=essais)
    ensemble = (j_acc + j_file) / (k_acc + k_file)
    strates = (n_acc * j_acc / k_acc + n_file * j_file / k_file) / (n_acc + n_file)
    eqm = lambda x: float(np.sqrt(np.mean((x - vraie) ** 2)))
    return {"vraie": vraie, "ensemble": float(ensemble.mean()), "strates": float(strates.mean()), "eqm_ensemble": eqm(ensemble), "eqm_strates": eqm(strates),
            "attendu_ensemble": (k_acc * r_acc + k_file * r_file) / (k_acc + k_file),
            "n_acc": n_acc, "n_file": n_file, "r_acc": r_acc, "r_file": r_file, "k_acc": k_acc, "k_file": k_file, "essais": essais}


def exp_apprentissage() -> dict:
    """Section 5 : la règle qui suit l'a priori, la règle gloutonne et le tirage a posteriori, sur un composant."""
    from . import rex
    t = rex.simuler_politiques(q_vrai=0.6, q0=0.2, gain_bonne=40.0, gain_mauvaise=-12.0, gain_recyclage=2.0)
    noms = {"A priori seul": "Prior mean, never updated", "Glouton": "Greedy (posterior mean)", "Thompson": "Posterior sampling (TS-LP)"}
    rangs = [{"politique": noms[r["Politique"]], "regret": r["Regret par pièce (€)"], "testees": r["Part de pièces testées"], "q": r["q estimé final"],
              "courbe": list(r["Courbe"])} for _, r in t.iterrows()]
    return {"rangs": rangs, "q_vrai": t.attrs["q vrai"], "q0": t.attrs["q0"], "seuil": t.attrs["Seuil q* (réemploi si q > q*)"], "oracle": t.attrs["Gain oracle par pièce (€)"]}


class _LecteurSimule:
    """Doublure de modèle de langage, de fiabilité connue du seul simulateur. Le numéro de la pièce est lu dans le texte."""
    prive, modele = True, "modèle simulé"

    def __init__(self, verite: dict, classes: list, rng, r_description=0.70, r_document=0.85, r_controle=0.85):
        self.verite, self.classes, self.rng = verite, classes, rng
        self.r = {"description": r_description, "document": r_document, "controle": r_controle}

    def _vraie(self, texte_: str) -> str:
        return self.verite[int(texte_.rsplit(" ", 1)[-1])]

    def _dire(self, vraie: str, r: float) -> str:
        return vraie if self.rng.random() < r else str(self.rng.choice([c for c in self.classes if c != vraie]))

    def classer(self, description, classes, contexte=""):
        return self._dire(self._vraie(description), self.r["description"]), "simulé"

    def extraire(self, contenu, classes):
        return self._dire(self._vraie(contenu), self.r["document"]), "simulé"

    def valider(self, classe, contenu):
        juste = self.rng.random() < self.r["controle"]
        return (classe == self._vraie(contenu)) == juste


def exp_chaine(graine: int = GRAINE, pieces: int = 300) -> dict:
    """Section 8 : la chaîne d'acquisition sur une nomenclature synthétique. Où vont les appels au modèle, ce qu'ils
    coûtent au regard de l'enjeu, et l'invariant de budget (lemme 1)."""
    from . import composition as C, cortex as K
    rng = np.random.default_rng(graine)
    classes = [f"K{i}" for i in range(8)]
    prix = dict(zip(classes, [8.0, 5.0, 3.0, 2.0, 1.0, 0.5, 0.2, 0.05]))
    tau, g = 0.25, C.Reglages()
    mots = {c: f"mot{i}" for i, c in enumerate(classes)}
    regles = pd.DataFrame({"Motif": list(mots.values()), "Classe": list(mots)})
    verite = {i: str(rng.choice(classes)) for i in range(pieces)}
    masses = np.exp(rng.normal(-2.5, 2.0, pieces))                        # kg par an : beaucoup de pièces légères, quelques lourdes
    modele = _LecteurSimule(verite, classes, rng)

    def collecteur(requete):
        i = int(requete["reference_fabricant"].split("-")[-1])
        if rng.random() < 0.15:                                           # déclaration structurée du fabricant
            return [{"origine": f"fabricant/{i}", "texte": f"déclaration {i}", "nature": "déclaration fabricant",
                     "classe": verite[i] if rng.random() < 0.95 else str(rng.choice(classes))}]
        return [{"origine": f"site/{i}", "texte": f"fiche {i}"}] if rng.random() < 0.7 else []

    plafond = masses * max(v + tau for v in prix.values())
    rangs = []
    with K.Cortex(":memory:") as cx:
        for i in range(pieces):
            u, c = rng.random(), verite[i]
            indice = mots[c] if u < 0.48 else mots[str(rng.choice([x for x in classes if x != c]))] if u < 0.60 else "piece"
            p = {"PN": f"PN{i:05d}", "Description": f"{indice} ref {i}", "Interne": False, "Fabricant": "Fabricant", "Référence fabricant": f"MPN-{i}", "Poids (kg)": None}
            r = C.resoudre(cx, p, classes, prix, regles, g, masse_annuelle_kg=float(masses[i]), collecteur=collecteur, modele=modele, cout_traitement=tau)
            sort = "acceptée" if r["Statut"] == "acceptée" else "revue" if r["Prochaine action"].startswith("revue humaine") else "laissée"
            rangs.append({"plafond": float(plafond[i]), "cout": float(r["Coût des acquisitions (€)"]), "appels": int(r["Appels au modèle"]), "sort": sort,
                          "juste": r["Classe retenue"] == c})
    t = pd.DataFrame(rangs).sort_values("plafond", ascending=False).reset_index(drop=True)
    acc = t[t["sort"].eq("acceptée")]
    complet = g.cout_description + g.cout_collecte + g.cout_extraction + g.cout_validation
    cinquiemes = []
    for q, indices in enumerate(np.array_split(np.arange(len(t)), 5), start=1):
        bloc = t.iloc[indices]
        cinquiemes.append({"cinquieme": q, "part_enjeu": float(bloc["plafond"].sum() / t["plafond"].sum()), "enjeu_median": float(bloc["plafond"].median()),
                           "appels": float(bloc["appels"].mean()), "cout": float(bloc["cout"].mean()), "acceptees": float(bloc["sort"].eq("acceptée").mean()),
                           "revue": float(bloc["sort"].eq("revue").mean()), "laissees": float(bloc["sort"].eq("laissée").mean())})
    return {"pieces": pieces, "appels": int(t["appels"].sum()), "appels_exhaustif": 3 * pieces, "cout": float(t["cout"].sum()), "cout_exhaustif": complet * pieces,
            "sans_appel": float((t["appels"] == 0).mean()), "exces_max": float((t["cout"] - t["plafond"]).max()),
            "ratio_max": float((t["cout"] / t["plafond"]).max()),
            "appels_sous_le_minimum": int(t.loc[t["plafond"] < min(g.cout_description, g.cout_collecte, g.cout_extraction, g.cout_validation), "appels"].sum()), "enjeu_total": float(t["plafond"].sum()),
            "acceptees": int(len(acc)), "justesse_acceptees": float(acc["juste"].mean()) if len(acc) else float("nan"),
            "revue": int(t["sort"].eq("revue").sum()), "laissees": int(t["sort"].eq("laissée").sum()),
            "enjeu_revue": float(t.loc[t["sort"].eq("revue"), "plafond"].sum() / t["plafond"].sum()),
            "enjeu_acceptees": float(acc["plafond"].sum() / t["plafond"].sum()), "cinquiemes": cinquiemes,
            "couts": {"description": g.cout_description, "collecte": g.cout_collecte, "extraction": g.cout_extraction, "controle": g.cout_validation, "revue": g.cout_revue},
            "seuil": g.seuil_acceptation}


def experiences(graine: int = GRAINE, suivre=None) -> dict:
    """Toutes les expériences synthétiques des trois papiers. `suivre(nom)` est appelée avant chacune (pour dire où l'on en est)."""
    from . import bancs
    plan = [("prix", lambda: exp_prix(graine)), ("variabilite", lambda: exp_variabilite(graine)), ("fusion", lambda: exp_fusion(graine)),
            ("strates", lambda: exp_strates(graine)), ("apprentissage", exp_apprentissage), ("chaine", lambda: exp_chaine(graine)),
            ("politiques", lambda: bancs.exp_politiques(graine)), ("fusion_ablation", lambda: bancs.exp_fusion_ablation(graine)),
            ("boucle", lambda: bancs.exp_boucle(graine)), ("boucle_file", lambda: bancs.exp_boucle(graine, sondage=5, cout_revue=0.5)),
            ("ancrage", lambda: bancs.exp_ancrage(graine)), ("exactitude", lambda: bancs.exp_exactitude(graine)), ("tampon", lambda: bancs.exp_tampon(graine)),
            ("apprentissage_lp", lambda: bancs.exp_apprentissage_lp(graine)), ("confinement", lambda: bancs.exp_confinement(graine))]
    e = {}
    for nom, f in plan:
        if suivre:
            suivre(nom)
        e[nom] = f()
    return e


# --------------------------------------------------------------------------- B. étude de cas
def etude_de_cas(cfg, echelle: float = 1.0) -> dict:
    """Ce que le dossier calcule sur les données du site, réduit à des agrégats. Un calcul qui échoue donne « n/a »."""
    from . import composition
    from .etapes import executer
    ctx = executer("synthese", cfg=cfg, silencieux=True)
    L, R, F = ctx.res.get("ligne", {}), ctx.res.get("rex", {}), ctx.res.get("flux", {})
    notes = L.get("Notes") or {}
    r, pp, mc = notes.get("resume") or {}, notes.get("periode_par_periode") or {}, notes.get("monte_carlo") or {}
    eur = lambda v: float(v) * echelle if _fini(v) else float("nan")
    quantiles = mc.get("Résultat P5 / médiane / P95 (€)") or (float("nan"),) * 3
    plan = L.get("Plan optimal")
    partages = float("nan")
    if isinstance(plan, pd.DataFrame) and len(plan):
        traites = plan[plan["Décision"].eq("traiter")]
        partages = int((traites["Type de FRU"].value_counts() > 1).sum())
    fluide, myope = eur(pp.get("Résultat du modèle annuel au flux moyen (€)")), eur(pp.get("Résultat annualisé, période par période (€)"))
    v = {"types": notes.get("types_de_fru"), "incomplets": notes.get("types_incomplets"), "partages": partages,
         "marge": eur(r.get("Marge variable / an (€)")), "fixes": eur(r.get("Coûts fixes annualisés (€)")), "resultat": eur(r.get("Résultat / an (€)")),
         "heures": r.get("Heures utilisées / an"), "capacite": r.get("Capacité (h/an)"), "mu": eur(r.get("Valeur d'une heure opérateur en plus (€ net)")),
         "unites": r.get("FRU traitées / an"), "seuil": r.get("Seuil de rentabilité (FRU / an)"), "retour": r.get("Retour sur investissement (ans)"),
         "masse": r.get("Masse des FRU scrapées (kg/an)"), "detournee": r.get("Masse détournée de la benne (kg/an)"),
         "cout_actuel": eur(r.get("Coût actuel de traitement (€/an)")), "proba": mc.get("P(ligne rentable)"),
         "p5": eur(quantiles[0]), "mediane": eur(quantiles[1]), "p95": eur(quantiles[2]),
         "periodes": pp.get("Périodes"), "fluide": fluide, "myope": myope, "gamma": eur(pp.get("Coût de la variabilité du flux (€/an)")),
         "gamma_rel": (fluide - myope) / fluide if _fini(fluide) and _fini(myope) and fluide > 0 else float("nan"), "pertes": pp.get("Périodes en perte"),
         "anomalies": len(ctx.anomalies)}
    v["part_detournee"] = v["detournee"] / v["masse"] if _fini(v["detournee"]) and _fini(v["masse"]) and v["masse"] > 0 else float("nan")
    heures = L.get("Sensibilité aux heures")
    v["t_heures"] = [] if not isinstance(heures, pd.DataFrame) else [
        (nombre(x["Heures / an"]), nombre(eur(x["Marge variable / an (€)"])), nombre(eur(x["Résultat / an (€)"])), pourcent(x["Taux d'occupation"]),
         nombre(eur(x["Valeur d'une heure opérateur en plus (€ net)"]), 1)) for _, x in heures.iterrows()]
    met = R.get("Métriques")
    noms = {"Bêta-binomial": "Beta--binomial posterior", "Fréquence observée": "Observed frequency", "A priori seul": "Prior alone"}
    v["t_rendements"] = [] if not isinstance(met, pd.DataFrame) else [
        (noms.get(x["Modèle"], x["Modèle"]), nombre(x["Brier"], 3), nombre(x["Log-perte"], 3), nombre(x["Écart absolu moyen"], 3),
         pourcent(x["Couverture IC90"]) if _fini(x["Couverture IC90"]) else "---") for _, x in met.iterrows()]
    v["lots"], v["copies"] = (int(met["Lots"].iloc[0]), float(met["Pièces"].iloc[0])) if isinstance(met, pd.DataFrame) and len(met) else (None, None)
    prev = F.get("Évaluation des prévisions")
    v["t_previsions"] = [] if not isinstance(prev, pd.DataFrame) else [
        (METHODES.get(x["Méthode"], x["Méthode"]), nombre(x["Prévisions"]), nombre(x["Écart quadratique relatif"], 3), nombre(x["Perte de quantile"], 3),
         pourcent(x["Couverture 80 %"])) for _, x in prev.sort_values("Perte de quantile").iterrows()]
    try:
        compo = composition.executer(ctx)
        n = compo["Notes"]
    except Exception:                                          # composition non calculable : inconnue, pas nulle
        compo, n = {}, {}
    from .bancs import AUTRES_SOURCES, SOURCES
    noms_sources = dict(SOURCES, **AUTRES_SOURCES)
    fiab = compo.get("Fiabilité des sources")
    v["t_sources"] = [] if not isinstance(fiab, pd.DataFrame) else [
        (noms_sources.get(x["Type de source"], x["Type de source"]), nombre(x["A priori (hypothèse)"], 2), nombre(x["Affirmations vérifiées"]), nombre(x["Justes"]),
         nombre(x["Fiabilité"], 2)) for _, x in fiab.sort_values("Affirmations vérifiées", ascending=False).iterrows()]
    st = n.get("statuts") or {}
    v.update({"c_pieces": n.get("pieces"), "c_validees": st.get("validée", 0) if n.get("pieces") else None, "c_acceptees": st.get("acceptée", 0) if n.get("pieces") else None,
              "c_file": (st.get("à valider", 0) + st.get("inconnue", 0)) if n.get("pieces") else None, "c_appels": n.get("appels_au_modele"),
              "c_sans_appel": n.get("pieces_sans_appel_payant"), "c_cout": n.get("cout_des_acquisitions_eur"), "c_modele": n.get("modele_heberge") or "none"})
    return v


# --------------------------------------------------------------------------- C. figures
def _axes(largeur=3.4, hauteur=2.5):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 8, "font.family": "serif", "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.6,
                         "axes.edgecolor": "#555555", "xtick.color": "#555555", "ytick.color": "#555555", "grid.color": "#dddddd", "grid.linewidth": 0.5,
                         "legend.frameon": False, "pdf.fonttype": 42})
    fig, ax = plt.subplots(figsize=(largeur, hauteur))
    ax.grid(True, axis="y")
    ax.set_axisbelow(True)
    return fig, ax


def _garder(fig, chemin: Path) -> None:
    import matplotlib.pyplot as plt
    fig.tight_layout(pad=0.4)
    fig.savefig(chemin)
    plt.close(fig)


def figures(e: dict, dossier: Path) -> list:
    """Trois figures des expériences synthétiques et le schéma d'ensemble, en PDF."""
    faits = []
    # temps de calcul du meilleur plan : énumération contre proposition 1
    fig, ax = _axes()
    rangs = e["prix"]["rangs"]
    enu = [(r["n"], r["enum_ms"]) for r in rangs if _fini(r["enum_ms"])]
    ax.plot([r["n"] for r in rangs], [r["sep_ms"] for r in rangs], TRAITS[0], marker=MARQUEURS[0], ms=4, lw=1.5, color=COULEURS[0])
    ax.plot(*zip(*enu), TRAITS[1], marker=MARQUEURS[1], ms=4, lw=1.5, color=COULEURS[1])
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Components per unit type"); ax.set_ylabel("Time per type (ms)")
    ax.annotate("Enumeration", enu[-1], textcoords="offset points", xytext=(6, 2), color="#333333")
    ax.annotate("Proposition 1", (rangs[-1]["n"], rangs[-1]["sep_ms"]), textcoords="offset points", xytext=(-6, -12), ha="right", color="#333333")
    _garder(fig, dossier / "fig_prix.pdf"); faits.append("fig_prix.pdf")
    # écart de variabilité
    fig, ax = _axes()
    v = e["variabilite"]
    for i, part in enumerate(v["parts"]):
        x, y = [r["cv"] for r in v["rangs"]], [100 * r[part] for r in v["rangs"]]
        ax.plot(x, y, TRAITS[i], marker=MARQUEURS[i], ms=4, lw=1.5, color=COULEURS[i], label=f"Hours = {part:.1f} $\\times$ need")
        ax.annotate(f"{part:.1f}", (x[-1], y[-1]), textcoords="offset points", xytext=(5, -2), color="#333333")
    ax.set_xlabel("Coefficient of variation of weekly arrivals"); ax.set_ylabel(r"Variability gap $\Gamma$ (% of fluid value)")
    ax.set_ylim(bottom=0); ax.margins(x=0.12)
    ax.legend(loc="upper left", handlelength=2.6)
    _garder(fig, dossier / "fig_variabilite.pdf"); faits.append("fig_variabilite.pdf")
    # regret cumulé
    fig, ax = _axes()
    a = e["apprentissage"]["rangs"]
    for i, r in enumerate(a):
        if i == 1:
            continue                                            # la règle gloutonne se confond ici avec l'a priori : dite en légende
        ax.plot(range(1, len(r["courbe"]) + 1), r["courbe"], TRAITS[min(i, 1)], lw=1.5, color=COULEURS[min(i, 1)])
    ax.annotate("Prior mean and greedy", (len(a[0]["courbe"]) * 0.52, a[0]["courbe"][len(a[0]["courbe"]) // 2]), textcoords="offset points", xytext=(-4, 6), ha="right", color="#333333")
    ax.annotate("Posterior sampling", (len(a[2]["courbe"]), a[2]["courbe"][-1]), textcoords="offset points", xytext=(-2, 6), ha="right", color="#333333")
    ax.set_xlabel("Copies processed"); ax.set_ylabel("Cumulative regret (monetary units)")
    _garder(fig, dossier / "fig_regret.pdf"); faits.append("fig_regret.pdf")
    # tirage a posteriori sur le programme complet
    fig, ax = _axes()
    lp = e["apprentissage_lp"]["rangs"]
    for i, r in enumerate(lp):
        ax.plot(range(1, len(r["courbe"]) + 1), np.array(r["courbe"]) / 1e3, TRAITS[i], lw=1.5, color=COULEURS[i])
        ax.annotate(["Prior mean", "Greedy", "Posterior sampling"][i], (len(r["courbe"]), r["courbe"][-1] / 1e3), textcoords="offset points",
                    xytext=(-3, [5, -11, 5][i]), ha="right", color="#333333")
    ax.set_xlabel("Period"); ax.set_ylabel("Cumulative regret (thousands)")
    ax.set_ylim(bottom=0)
    _garder(fig, dossier / "fig_regret_lp.pdf"); faits.append("fig_regret_lp.pdf")
    # politiques d'acquisition : valeur nette, en part de l'oracle (la revue de toutes les pièces, très négative, est dite dans le texte)
    fig, ax = _axes(3.4, 2.3)
    pol = [r for r in e["politiques"]["rangs"] if r["part"] > -0.5][::-1]
    noms = {"Review by prior stake, no automation": "Human review by prior stake", "Free evidence only": "Free evidence only",
            "Chain without the budget screen": "Chain, no budget screen", "Chain with a stake-blind budget": "Chain, stake-blind budget",
            "Budgeted chain (this paper)": "Budgeted chain (ours)"}
    y = np.arange(len(pol))
    ax.barh(y, [100 * r["part"] for r in pol], height=0.55, color=COULEURS[0], zorder=2)
    ax.hlines(y, [100 * r["part_min"] for r in pol], [100 * r["part_max"] for r in pol], color="#333333", lw=0.9, zorder=3)
    for k, r in enumerate(pol):
        ax.annotate(f"{100 * r['part']:.0f}", (100 * r["part_max"], k), textcoords="offset points", xytext=(4, -3), color="#333333")
    ax.set_yticks(y); ax.set_yticklabels([noms.get(r["politique"], r["politique"]) for r in pol])
    ax.set_xlabel("Net value (% of the oracle)"); ax.set_xlim(0, 105)
    ax.grid(True, axis="x"); ax.grid(False, axis="y")
    _garder(fig, dossier / "fig_politiques.pdf"); faits.append("fig_politiques.pdf")
    _schema(dossier / "fig_architecture.pdf"); faits.append("fig_architecture.pdf")
    return faits


def _schema(chemin: Path) -> None:
    """Schéma d'ensemble : données, modèles, base de connaissance, agents. Flèches droites, aucune ne traverse une boîte."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
    fig, ax = plt.subplots(figsize=(6.9, 4.5))
    ax.set_xlim(0, 100); ax.set_ylim(0, 66); ax.axis("off")
    gris, bleu, orange, vert = "#f3f3f3", "#e3eefb", "#fdebe1", "#dff5ef"

    def boite(x, y, w, h, titre, texte_="", fond=gris):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.2,rounding_size=1.0", fc=fond, ec="#555555", lw=0.7))
        ax.text(x + w / 2, y + h - 1.6, titre, ha="center", va="top", fontsize=6.6, weight="bold", family="serif")
        if texte_:
            ax.text(x + w / 2, y + h - 4.9, texte_, ha="center", va="top", fontsize=5.5, family="serif", linespacing=1.3)

    def fleche(a, b, texte_="", dx=0.0, dy=0.0, ha="center"):
        ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=7, lw=0.7, color="#444444", shrinkA=0, shrinkB=0))
        if texte_:
            ax.text((a[0] + b[0]) / 2 + dx, (a[1] + b[1]) / 2 + dy, texte_, ha=ha, va="center", fontsize=5.3, family="serif", color="#333333")

    for y, nom in ((64.6, "Records"), (46.6, "Decision models"), (27.6, "Knowledge acquisition"), (8.6, "Agents on a self-hosted open model")):
        ax.text(1, y, nom, fontsize=5.8, color="#777777", family="serif", va="center")
    # ligne 1 : ce qui entre
    boite(2, 52, 28, 11, "Operational records", "repairs, scrapped units,\nconsumption, weighing,\nearly failures")
    boite(36, 52, 28, 11, "Parameter workbook", "ranges, provenance of each\nvalue, unknown kept unknown")
    boite(70, 52, 28, 11, "Bill of materials", "part number, description,\nmanufacturer reference")
    # ligne 2 : modèles de décision
    boite(2, 33, 28, 12, "Yields and arrivals", "Beta posterior, posterior\nsampling, forecasts,\nearly-failure analysis", bleu)
    boite(36, 33, 28, 12, "Disposition model (P)", "labour price $\\mu^*$, plan of\neach type, threshold rule,\nvariability gap $\\Gamma$", bleu)
    boite(70, 33, 28, 12, "Value of information", "bounds of Propositions 6-7,\nstake of each component", bleu)
    # ligne 3 : connaissance
    boite(2, 14, 18, 12, "Instruction search", "prompt evolution on\nvalidated parts,\nheld-out test", orange)
    boite(25, 14, 18, 12, "Human review", "queue by stake,\nrandom audit of\naccepted classes", orange)
    boite(52, 14, 18, 12, "Knowledge base", "claims, validations,\nreliability by source\ntype, fusion", orange)
    boite(74, 14, 24, 12, "Acquisition chain", "rule, analogy, private reading,\nretrieval, document reading,\nverdict, within the stake", orange)
    # ligne 4 : agents
    boite(2, 1, 96, 6.4, "Pilot, writer, reviewer", "closed list of tools over the modules above; every number of the decision note is checked against tool outputs", vert)
    fleche((16, 52), (16, 45.2)); fleche((50, 52), (50, 45.2)); fleche((84, 52), (84, 45.2))
    fleche((30.2, 39), (35.8, 39)); fleche((64.2, 39), (69.8, 39))
    fleche((86, 33), (86, 26.2), "stake", dx=1.2, ha="left")
    fleche((73.8, 20), (70.2, 20))
    fleche((61, 26.2), (61, 32.8), "classes, hence prices", dx=1.2, ha="left")
    fleche((51.8, 22.5), (43.2, 22.5)); fleche((43.2, 17.5), (51.8, 17.5))
    ax.text(47.5, 24.0, "queue", ha="center", fontsize=5.3, family="serif", color="#333333")
    ax.text(47.5, 16.0, "validations", ha="center", fontsize=5.3, family="serif", color="#333333")
    fleche((24.8, 20), (20.2, 20))
    fig.savefig(chemin, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)


# --------------------------------------------------------------------------- D. écriture
def environnement() -> dict:
    """Machine et versions sur lesquelles les chiffres ont été calculés : à citer dans un papier, jamais à deviner."""
    import platform
    versions = {}
    for nom in ("numpy", "pandas", "scipy", "matplotlib"):
        try:
            versions[nom] = __import__(nom).__version__
        except ImportError:
            versions[nom] = "not installed"
    processeur = platform.processor() or platform.machine()
    try:
        for ligne in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if ligne.lower().startswith("model name"):
                processeur = ligne.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    import os
    return {"python": platform.python_version(), "systeme": f"{platform.system()} {platform.release()}".strip(), "processeur": processeur,
            "coeurs": os.cpu_count() or 0, **versions}


def _latex(t) -> str:
    """Texte libre rendu sûr pour LaTeX."""
    return "".join({"_": r"\_", "%": r"\%", "&": r"\&", "#": r"\#", "$": r"\$", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
                    "\\": r"\textbackslash{}"}.get(c, c) for c in str(t))


def _macros_des_bancs(e: dict) -> dict:
    """Macros des bancs d'essai de `erc.bancs` (papiers KDD et ICAPS)."""
    pol = {r["politique"]: r for r in e["politiques"]["rangs"]}
    budget, sans, aveugle = pol["Budgeted chain (this paper)"], pol["Chain without the budget screen"], pol["Chain with a stake-blind budget"]
    abl = e["fusion_ablation"]["rangs"]
    apprises = [r for r in abl if r["methode"] == "Fusion, learned reliabilities"]
    par = {r["methode"]: r for r in abl}
    fusion, vote, sans_prov, declaree = apprises[-1], par["Majority vote"], par["Fusion, learned, provenance ignored"], par["Fusion, declared reliabilities"]
    b, f, anc, ex, tp, lp, cf = e["boucle"], e["boucle_file"], e["ancrage"], e["exactitude"], e["tampon"], e["apprentissage_lp"], e["confinement"]
    grand = ex["rangs"][-1]
    rec = [r["stock"] for r in tp["rangs"]]
    lpr = {r["politique"]: r for r in lp["rangs"]}
    ecart = "0" if not ex["ecart"] > 0 else f"{ex['ecart']:.0e}".replace("e-0", r"\times 10^{-").replace("e-", r"\times 10^{-") + "}"
    return {
        "SynPolPieces": e["politiques"]["pieces"], "SynPolGraines": e["politiques"]["graines"],
        "SynPolBudgetPart": pourcent(budget["part"]), "SynPolBudgetMin": pourcent(budget["part_min"]), "SynPolBudgetMax": pourcent(budget["part_max"]),
        "SynPolSansBudgetPart": pourcent(sans["part"]), "SynPolAveuglePart": pourcent(aveugle["part"]),
        "SynPolGratuitPart": pourcent(pol["Free evidence only"]["part"]), "SynPolRevuePart": pourcent(pol["Review by prior stake, no automation"]["part"]),
        "SynPolToutPart": pourcent(pol["Review every component"]["part"]),
        "SynPolBudgetAppels": nombre(budget["appels"]), "SynPolSansBudgetAppels": nombre(sans["appels"]),
        "SynPolEconomieAppels": pourcent(1 - budget["appels"] / sans["appels"]) if sans["appels"] else "n/a",
        "SynPolBudgetRevues": nombre(budget["revues"], 1), "SynPolBudgetJustesse": pourcent(budget["justesse"], 1),
        "SynPolGratuitRevues": nombre(pol["Free evidence only"]["revues"], 1),
        "SynAblEssai": e["fusion_ablation"]["essai"], "SynAblCopie": e["fusion_ablation"]["copie"], "SynAblValidations": fusion["validations"],
        "SynAblFusionJustesse": pourcent(fusion["justesse"], 1), "SynAblVoteJustesse": pourcent(vote["justesse"], 1), "SynAblDeclareeJustesse": pourcent(declaree["justesse"], 1),
        "SynAblTrenteJustesse": pourcent(apprises[0]["justesse"], 1), "SynAblTrente": apprises[0]["validations"],
        "SynAblFusionAcc": pourcent(fusion["justesse_acceptees"], 1), "SynAblVoteAcc": pourcent(vote["justesse_acceptees"], 1),
        "SynAblSansProvAcc": pourcent(sans_prov["justesse_acceptees"], 1), "SynAblFusionCouv": pourcent(fusion["couverture"]), "SynAblVoteCouv": pourcent(vote["couverture"]),
        "SynAblSansProvCouv": pourcent(sans_prov["couverture"]), "SynAblFusionEce": nombre(fusion["ece"], 3), "SynAblSansProvEce": nombre(sans_prov["ece"], 3),
        "SynAblVoteEce": nombre(vote["ece"], 3),
        "SynBoucleGraines": b["graines"], "SynBouclePieces": b["pieces"], "SynBoucleTours": b["tours"], "SynBoucleSondage": b["sondage"],
        "SynBoucleRevues": nombre(b["validations_file"], 1),
        "SynBoucleErrDeclaree": nombre(b["erreur_declaree"], 3), "SynBoucleErrStrates": nombre(b["erreur_strates"], 3), "SynBoucleErrEnsemble": nombre(b["erreur_ensemble"], 3),
        "SynBoucleBiaisStrates": signe(b["biais_strates"]), "SynBoucleBiaisEnsemble": signe(b["biais_ensemble"]),
        "SynBoucleJustesseUn": pourcent(b["suivi"][0]["justesse"], 1), "SynBoucleJustesseDeux": pourcent(b["suivi"][1]["justesse"], 1),
        "SynBoucleJustesseTrois": pourcent(b["suivi"][-1]["justesse"], 1), "SynBoucleAccepteesUn": nombre(b["suivi"][0]["acceptees"]),
        "SynBoucleAccepteesDeux": nombre(b["suivi"][1]["acceptees"]), "SynBoucleAccepteesTrois": nombre(b["suivi"][-1]["acceptees"]),
        "SynFileSondage": f["sondage"], "SynFileCoutRevue": f["cout_revue"], "SynFileRevues": nombre(f["validations_file"], 1),
        "SynFileErrStrates": nombre(f["erreur_strates"], 3), "SynFileErrEnsemble": nombre(f["erreur_ensemble"], 3),
        "SynFileBiaisStrates": signe(f["biais_strates"]), "SynFileBiaisEnsemble": signe(f["biais_ensemble"]),
        "SynAncNotes": nombre(anc["notes"]), "SynAncLegitimes": nombre(anc["legitimes"]), "SynAncFaussesAlertes": nombre(anc["fausses_alertes"]),
        "SynAncInventes": nombre(anc["inventes"]), "SynAncManques": nombre(anc["inventes"] - anc["inventes_signales"]),
        "SynAncRappelInventes": pourcent(anc["rappel_inventes"], 1), "SynAncRappelRetouches": pourcent(anc["rappel_retouches"], 1),
        "SynExactEcart": ecart, "SynExactInstances": ex["compares"], "SynExactGrandTypes": nombre(grand["types"]), "SynExactGrandComposants": nombre(grand["composants"]),
        "SynExactGrandSecondes": nombre(grand["secondes"], 1),
        "SynTamponSemaines": tp["semaines"], "SynTamponPart": tp["part"], "SynTamponBorne": nombre(tp["tampon_semaines"]),
        "SynTamponMin": pourcent(min(rec)), "SynTamponMax": pourcent(max(rec)),
        "SynLPPeriodes": lp["periodes"], "SynLPGraines": lp["graines"], "SynLPTypes": lp["types"], "SynLPPart": lp["part"],
        "SynLPPrior": pourcent(lpr["Prior mean, never updated"]["part"], 1), "SynLPGlouton": pourcent(lpr["Greedy (posterior mean)"]["part"], 1),
        "SynLPTS": pourcent(lpr["Posterior sampling (TS-LP)"]["part"], 1),
        "SynConfEpisodes": nombre(cf["episodes"]), "SynConfTours": nombre(cf["tours"]), "SynConfHorsListe": nombre(cf["hors_liste"]),
        "SynConfDansListe": nombre(cf["dans_liste"]), "SynConfExecutees": nombre(cf["hors_liste_executees"]), "SynConfExceptions": nombre(cf["exceptions"]),
        "SynConfDepassements": nombre(cf["depassements"]), "SynConfReplis": nombre(cf["replis"]), "SynConfRefus": nombre(cf.get("refus", 0)),
    }


def _macros(e: dict, c: dict, demo: bool, echelle: float) -> str:
    p, s, a, ch = e["prix"], e["strates"], e["apprentissage"], e["chaine"]
    pire = max(r[part] for r in e["variabilite"]["rangs"] for part in e["variabilite"]["parts"])
    plus_grand = p["rangs"][-1]
    m = {
        "DonneesDemo": "1" if demo else "0", "EchelleMasquee": "0" if echelle == 1.0 else "1",
        # expériences synthétiques
        "SynPrixEcart": f"{p['ecart']:.1e}".replace("e-0", r"\times 10^{-").replace("e-", r"\times 10^{-") + "}" if p["ecart"] > 0 else "0",
        "SynPrixValeurs": p["prix"], "SynPrixGrand": nombre(plus_grand["n"]), "SynPrixGrandTemps": duree(plus_grand["sep_ms"]),
        "SynGammaMax": pourcent(pire), "SynGammaSemaines": e["variabilite"]["semaines"], "SynGammaTypes": e["variabilite"]["types"],
        "SynFusionClasses": e["fusion"]["n"], "SynFusionEssais": nombre(e["fusion"]["essais"]),
        "SynFusionKhaut": assertions_suffisantes(0.9, e["fusion"]["n"], 0.02), "SynFusionKbas": assertions_suffisantes(0.6, e["fusion"]["n"], 0.02),
        "SynStrateVraie": nombre(s["vraie"], 3), "SynStrateEnsemble": nombre(s["ensemble"], 3), "SynStrateAttendu": nombre(s["attendu_ensemble"], 3),
        "SynStrateStrates": nombre(s["strates"], 3), "SynStrateEqmEnsemble": nombre(s["eqm_ensemble"], 3), "SynStrateEqmStrates": nombre(s["eqm_strates"], 3),
        "SynStrateNacc": s["n_acc"], "SynStrateNfile": s["n_file"], "SynStrateRacc": s["r_acc"], "SynStrateRfile": s["r_file"],
        "SynStrateKacc": s["k_acc"], "SynStrateKfile": s["k_file"],
        "SynTSvrai": a["q_vrai"], "SynTSprior": a["q0"], "SynTSseuil": nombre(a["seuil"], 2), "SynTSoracle": nombre(a["oracle"], 1),
        "SynChainePieces": ch["pieces"], "SynChaineAppels": nombre(ch["appels"]), "SynChaineExhaustif": nombre(ch["appels_exhaustif"]),
        "SynChaineSansAppel": pourcent(ch["sans_appel"]), "SynChaineCout": nombre(ch["cout"], 2), "SynChaineCoutExhaustif": nombre(ch["cout_exhaustif"], 2),
        "SynChaineEnjeu": nombre(ch["enjeu_total"]), "SynChaineRatio": nombre(ch["ratio_max"], 2), "SynChaineAcceptees": ch["acceptees"],
        "SynChaineJustesse": pourcent(ch["justesse_acceptees"]), "SynChaineRevue": ch["revue"], "SynChaineLaissees": ch["laissees"],
        "SynChaineEnjeuRevue": pourcent(ch["enjeu_revue"]), "SynChaineEnjeuAcceptees": pourcent(ch["enjeu_acceptees"]),
        "SynChaineEconomie": pourcent(1 - ch["appels"] / ch["appels_exhaustif"]),
        "SynChaineHautTraites": pourcent(ch["cinquiemes"][0]["acceptees"] + ch["cinquiemes"][0]["revue"]),
        "SynChaineBasLaissees": pourcent(ch["cinquiemes"][-1]["laissees"]), "SynChaineBasCout": nombre(ch["cinquiemes"][-1]["cout"], 3),
        "CoutDescription": ch["couts"]["description"], "CoutCollecte": ch["couts"]["collecte"], "CoutExtraction": ch["couts"]["extraction"],
        "CoutControle": ch["couts"]["controle"], "CoutRevue": nombre(ch["couts"]["revue"]), "SeuilAcceptation": ch["seuil"],
        **_macros_des_bancs(e),
        **{"Env" + k.capitalize(): _latex(v) for k, v in environnement().items()},
        # étude de cas
        "CasTypes": nombre(c["types"]), "CasIncomplets": nombre(c["incomplets"]), "CasPartages": nombre(c["partages"]),
        "CasMarge": nombre(c["marge"]), "CasFixes": nombre(c["fixes"]), "CasResultat": nombre(c["resultat"]), "CasHeures": nombre(c["heures"]),
        "CasCapacite": nombre(c["capacite"]), "CasMu": nombre(c["mu"], 1), "CasUnites": nombre(c["unites"]), "CasSeuil": nombre(c["seuil"]),
        "CasRetour": nombre(c["retour"], 1), "CasMasse": nombre(c["masse"]), "CasDetournee": nombre(c["detournee"]), "CasPartDetournee": pourcent(c["part_detournee"]),
        "CasCoutActuel": nombre(c["cout_actuel"]), "CasProba": pourcent(c["proba"]), "CasPcinq": nombre(c["p5"]), "CasMediane": nombre(c["mediane"]),
        "CasPnonantecinq": nombre(c["p95"]), "CasPeriodes": nombre(c["periodes"]), "CasFluide": nombre(c["fluide"]), "CasMyope": nombre(c["myope"]),
        "CasGamma": nombre(c["gamma"]), "CasGammaRel": pourcent(c["gamma_rel"]), "CasPertes": nombre(c["pertes"]), "CasAnomalies": nombre(c["anomalies"]),
        "CasLots": nombre(c["lots"]), "CasCopies": nombre(c["copies"]),
        "CasCompoPieces": nombre(c["c_pieces"]), "CasCompoValidees": nombre(c["c_validees"]), "CasCompoAcceptees": nombre(c["c_acceptees"]),
        "CasCompoFile": nombre(c["c_file"]), "CasCompoAppels": nombre(c["c_appels"]), "CasCompoSansAppel": nombre(c["c_sans_appel"]),
        "CasCompoCout": nombre(c["c_cout"], 2),
    }
    entete = "% Écrit par `python -m erc.papier`. Ne pas modifier à la main : relancer la commande.\n"
    return entete + "".join(f"\\newcommand{{\\{k}}}{{{v}}}\n" for k, v in m.items())


def _tableaux(e: dict, c: dict) -> dict:
    vide = [("\\multicolumn{5}{c}{not available: the corresponding step could not be computed}",)]
    v = e["variabilite"]
    return {
        "t_prix": _lignes((nombre(r["n"]), f"$3^{{{r['n']}}}$" if r["n"] > 12 else nombre(r["plans"]), duree(r["enum_ms"]), duree(r["sep_ms"])) for r in e["prix"]["rangs"]),
        "t_variabilite": _lignes((r["loi"], nombre(r["cv"], 2), *(pourcent(r[part], 1) for part in v["parts"])) for r in v["rangs"]),
        "t_fusion": _lignes((r["r"], r["k"], petit(r["erreur"]), petit(r["borne"]) if r["borne"] < 1 else "1 (vacuous)") for r in e["fusion"]["rangs"]),
        "t_chaine": _lignes((r["cinquieme"], pourcent(r["part_enjeu"], 1), nombre(r["enjeu_median"], 2), nombre(r["appels"], 2), nombre(r["cout"], 3),
                             pourcent(r["acceptees"]), pourcent(r["revue"]), pourcent(r["laissees"])) for r in e["chaine"]["cinquiemes"]),
        "t_apprentissage": _lignes((r["politique"], nombre(r["regret"], 2), pourcent(r["testees"]), nombre(r["q"], 2)) for r in e["apprentissage"]["rangs"]),
        "t_cas_heures": _lignes(c["t_heures"] or vide), "t_cas_rendements": _lignes(c["t_rendements"] or vide), "t_cas_previsions": _lignes(c["t_previsions"] or vide),
        "t_cas_sources": _lignes(c.get("t_sources") or vide),
        "t_politiques": _lignes((r["politique"], nombre(r["appels"]), nombre(r["cout"], 2), nombre(r["revues"], 1), nombre(r["acceptees"]),
                                 pourcent(r["justesse"], 1) if _fini(r["justesse"]) else "---", pourcent(r["part"]), f"{pourcent(r['part_min'])} to {pourcent(r['part_max'])}")
                                for r in e["politiques"]["rangs"]),
        "t_fusion_ablation": _lignes((r["methode"], r["validations"] if "Fusion" in r["methode"] else "---", pourcent(r["justesse"], 1), nombre(r["brier"], 3), nombre(r["ece"], 3),
                                      pourcent(r["couverture"]), pourcent(r["justesse_acceptees"], 1)) for r in e["fusion_ablation"]["rangs"]),
        "t_boucle": _lignes((r["source"], nombre(r["pieces"]), nombre(r["vraie"], 3), nombre(r["declaree"], 2), nombre(r["strates"], 3), nombre(r["ensemble"], 3)) for r in e["boucle"]["rangs"]),
        "t_boucle_file": _lignes((r["source"], nombre(r["pieces"]), nombre(r["vraie"], 3), nombre(r["declaree"], 2), nombre(r["strates"], 3), nombre(r["ensemble"], 3)) for r in e["boucle_file"]["rangs"]),
        "t_boucle_suivi": _lignes((r["tour"], nombre(r["acceptees"]), pourcent(r["justesse"], 1), nombre(r["revues"], 1), nombre(r["validees"]), nombre(r["appels"])) for r in e["boucle"]["suivi"]),
        "t_exactitude": _lignes((nombre(r["types"]), nombre(r["composants"]), nombre(r["secondes"], 2), r["partages"]) for r in e["exactitude"]["rangs"]),
        "t_tampon": _lignes((r["loi"], pourcent(r["ecart"], 1), pourcent(r["stock"]), pourcent(r["stock_borne"])) for r in e["tampon"]["rangs"]),
        "t_apprentissage_lp": _lignes((r["politique"], pourcent(r["part"], 1), nombre(r["testees"])) for r in e["apprentissage_lp"]["rangs"]),
    }


# Les papiers : sous-dossier de papier/, nom du fichier maître, où il lit les chiffres depuis son dossier.
PAPIERS = {"informs": ("", "manuscrit", ""), "kdd": ("kdd", "kdd", "../"), "icaps": ("icaps", "icaps", "../"), "icaps_supplement": ("icaps", "supplement", "../")}


def racine_du_papier(dossier=None) -> Path:
    return Path(dossier) if dossier else Path(__file__).resolve().parent.parent / "papier"


def dossier_des_sorties(racine: Path, demo: bool) -> Path:
    """Démonstration : papier/genere (versionné). Données du site : papier/site (jamais versionné ni empaqueté)."""
    return Path(racine) / ("genere" if demo else "site")


def nom_du_manuscrit(demo: bool, papier: str = "informs") -> str:
    return PAPIERS[papier][1] + ("" if demo else "_site")


def ecrire(cfg, dossier=None, echelle: float = 1.0, graine: int = GRAINE, suivre=None) -> dict:
    """Calcule tout et écrit les macros, les corps de tableaux et les figures : dans papier/genere pour la
    démonstration, dans papier/site pour les données du site. Les trois papiers lisent le même dossier."""
    sortie = dossier_des_sorties(racine_du_papier(dossier), bool(cfg.demo))
    sortie.mkdir(parents=True, exist_ok=True)
    e, c = experiences(graine, suivre), etude_de_cas(cfg, echelle)
    (sortie / "macros.tex").write_text(_macros(e, c, bool(cfg.demo), echelle), encoding="utf-8")
    for nom, corps in _tableaux(e, c).items():
        (sortie / f"{nom}.tex").write_text(corps, encoding="utf-8")
    return {"dossier": sortie, "figures": figures(e, sortie), "experiences": e, "cas": c, "demo": bool(cfg.demo)}


def compiler(dossier=None, nom: str = "manuscrit", papier: str | None = None, demo: bool = True) -> Path | None:
    """Compile un papier si pdflatex et bibtex sont installés ; rend le chemin du PDF, ou None.
    `papier` (informs, kdd, icaps, icaps_supplement) choisit le sous-dossier et le fichier ; sinon `nom` dans `dossier`."""
    racine = racine_du_papier(dossier)
    if papier is not None:
        racine, nom = racine / PAPIERS[papier][0], nom_du_manuscrit(demo, papier)
    if not shutil.which("pdflatex") or not shutil.which("bibtex"):
        return None
    latex = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", nom + ".tex"]
    cite = "\\citation" in "".join(f.read_text(encoding="utf-8", errors="replace") for f in racine.glob(nom + ".aux"))
    for commande in (latex, ["bibtex", nom], latex, latex):
        if commande[0] == "bibtex" and not (racine / (nom + ".aux")).is_file():
            continue
        r = subprocess.run(commande, cwd=racine, capture_output=True, text=True, errors="replace")
        if r.returncode != 0 and commande[0] == "pdflatex":
            raise RuntimeError("La compilation a échoué :\n" + "\n".join(r.stdout.splitlines()[-25:]))
    for suffixe in (".aux", ".log", ".out", ".blg", ".toc"):
        (racine / (nom + suffixe)).unlink(missing_ok=True)
    return racine / (nom + ".pdf")


def pages_de(dossier, nom: str, etiquette: str = "fin:contenu") -> dict:
    """Après une compilation gardant le .aux : page où finit le contenu (\\label{fin:contenu}) et nombre total de pages."""
    import re
    aux, log = Path(dossier) / (nom + ".aux"), Path(dossier) / (nom + ".log")
    m = re.search(r"\\newlabel\{" + re.escape(etiquette) + r"\}\{\{[^{}]*\}\{(\d+)\}", aux.read_text(encoding="utf-8", errors="replace")) if aux.is_file() else None
    t = re.search(r"Output written on .*?\((\d+) pages?", log.read_text(encoding="utf-8", errors="replace")) if log.is_file() else None
    return {"contenu": int(m.group(1)) if m else None, "total": int(t.group(1)) if t else None}


def archive_overleaf(dossier=None, demo: bool = True, papier: str = "informs") -> Path:
    """Fabrique l'archive à déposer sur Overleaf (New Project > Upload Project) : le texte, la bibliographie et les
    chiffres, tableaux et figures. Le document principal est document.tex ; il se compile tel quel.

    demo=True  : chiffres de démonstration (papier/genere)
    demo=False : VOS chiffres (papier/site), rangés dans l'archive sous le nom genere/. Cette archive contient vos
                 résultats : la déposer sur un service en ligne les lui confie.
    """
    racine = racine_du_papier(dossier)
    sorties = dossier_des_sorties(racine, demo)
    if not (sorties / "macros.tex").is_file():
        raise FileNotFoundError(f"{sorties} est vide : lancer d'abord python -m erc.papier" + (" --demo" if demo else ""))
    sous, _, remonte = PAPIERS[papier]
    source = racine / sous
    nom = {"informs": "Manuscrit", "kdd": "KDD", "icaps": "ICAPS"}[papier]
    archive = racine / (f"{nom}_Overleaf.zip" if demo else f"{nom}_Overleaf_site.zip")
    textes = [f for f in sorted(source.rglob("*")) if f.is_file() and f.suffix in (".tex", ".bib", ".bst", ".sty", ".cls") and "genere" not in f.parts and "site" not in f.parts
              and not f.stem.endswith("_site") and f.name not in ("manuscrit.tex", "kdd.tex", "icaps.tex", "supplement.tex", "commun.tex")
              and (papier != "informs" or f.parent.name in ("papier", "sections") or f.parent == source)]
    if papier == "informs":
        textes = [f for f in textes if f.parent == source or f.parent == source / "sections"]
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for f in textes:
            contenu = f.read_text(encoding="utf-8")
            if remonte:                                         # dans l'archive, genere/ et commun.tex sont à côté du document
                contenu = contenu.replace("{" + remonte + "genere}", "{genere}").replace("{" + remonte + "commun}", "{commun}")
            z.writestr(f.relative_to(source).as_posix(), contenu)
        if remonte:
            z.writestr("commun.tex", (racine / "commun.tex").read_text(encoding="utf-8").replace("{" + remonte + "genere}", "{genere}"))
        for f in sorted(sorties.iterdir()):
            if f.suffix in (".tex", ".pdf"):
                z.write(f, f"genere/{f.name}")
        z.writestr("LISEZ-MOI.txt", "Projet Overleaf.\n\nDocument principal : document.tex (Menu > Main document).\n"
                   "Compilateur : pdfLaTeX. Bibliographie : references.bib, par BibTeX.\n"
                   "Le dossier genere/ contient les chiffres, les corps des tableaux et les figures : il est écrit par la commande\n"
                   "python -m erc.papier du dossier, ne pas le modifier à la main. Pour changer un chiffre, relancer la commande et\n"
                   "redéposer le dossier genere/.\n"
                   "Le texte à écrire après le passage sur vos données est marqué en rouge : chercher \\apres{ dans les fichiers .tex.\n"
                   + ("" if demo else "\nATTENTION : cette archive contient les chiffres de VOTRE site.\n"))
    return archive


def main(argv=None) -> int:
    import argparse

    from .config import charger
    a = argparse.ArgumentParser(prog="python -m erc.papier", description="Écrit les chiffres, tableaux et figures du manuscrit depuis le dossier")
    a.add_argument("--dossier")
    a.add_argument("--demo", action="store_true")
    a.add_argument("--echelle", type=float, default=1.0, help="facteur appliqué aux montants de l'étude de cas (non publié)")
    a.add_argument("--compiler", action="store_true", help="compile ensuite le manuscrit")
    a.add_argument("--overleaf", action="store_true", help="fabrique ensuite l'archive à déposer sur Overleaf")
    a.add_argument("--papier", choices=["informs", "kdd", "icaps", "tous"], default="tous", help="papier à compiler ou à archiver (défaut : tous)")
    o = a.parse_args(argv)
    cfg = charger(dossier=o.dossier, demo=True if o.demo else None)
    print("Expériences synthétiques (quelques minutes) :", end=" ", flush=True)
    r = ecrire(cfg, echelle=o.echelle, suivre=lambda nom: print(nom, end=" ", flush=True))
    print()
    print(f"Écrit : {r['dossier']} (macros, {len(r['figures'])} figures). Données de l'étude de cas : " + ("DÉMONSTRATION (fictives)" if r["demo"] else "réelles") + ".")
    choisis = ["informs", "kdd", "icaps"] if o.papier == "tous" else [o.papier]
    racine = racine_du_papier()
    presents = [p_ for p_ in choisis if (racine / PAPIERS[p_][0] / "document.tex").is_file()]
    if o.compiler:
        for p_ in presents + (["icaps_supplement"] if "icaps" in presents and (racine / "icaps" / "supplement_document.tex").is_file() else []):
            pdf = compiler(papier=p_, demo=r["demo"])
            print(f"PDF ({p_}) : " + str(pdf) if pdf else "pdflatex ou bibtex absent : rien n'a été compilé (voir papier/LISEZ-MOI.md).")
    if o.overleaf:
        for p_ in presents:
            print(f"Archive pour Overleaf ({p_}) : " + str(archive_overleaf(demo=r["demo"], papier=p_)))
        if not r["demo"]:
            print("ATTENTION : ces archives contiennent les chiffres de votre site. Les déposer sur Overleaf les confie à ce service.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
