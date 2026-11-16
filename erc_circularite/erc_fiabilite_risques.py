"""ERC : fiabilité opérationnelle, durée de vie résiduelle, risques supply et matière, valeur par voie.

Module autonome (numpy + pandas seulement) appelé par ERC_Fiabilite_Risques_Priorisation.ipynb.
Il se branche sur les sorties de ERC_Aide_Decision_Composants.ipynb :
  - cache fiabilité  Extraction_R26/fiabilite_ELF_references_ERC.csv
  - classeur          ERC_Aide_Decision_Composants.xlsx (onglets Classement_*, Composants_FRU_rebutees)

Règle du projet : aucune valeur inventée. Toute table codée en dur porte une colonne « Source » et
une valeur None signifie « inconnu » ; elle est propagée comme incertitude, jamais remplacée par zéro.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

RNG = np.random.default_rng(2026)

# ---------------------------------------------------------------------------
# 1. Risque matière : tables codées en dur
# ---------------------------------------------------------------------------
# Liste UE des matières premières critiques (CRM, 34) et stratégiques (17), Règlement (UE) 2024/1252
# (Critical Raw Materials Act), annexes I et II. À re-vérifier contre le texte publié avant diffusion.
CRM_UE = {
    "antimoine", "arsenic", "bauxite/alumine/aluminium", "baryte", "béryllium", "bismuth", "bore", "cobalt",
    "charbon à coke", "cuivre", "feldspath", "fluorine", "gallium", "germanium", "hafnium", "hélium",
    "terres rares lourdes", "terres rares légères", "lithium", "magnésium", "manganèse", "graphite naturel",
    "nickel", "niobium", "phosphate naturel", "phosphore", "platinoïdes (PGM)", "scandium", "silicium métal",
    "strontium", "tantale", "titane métal", "tungstène", "vanadium",
}
STRATEGIQUES_UE = {
    "bismuth", "bore", "cobalt", "cuivre", "gallium", "germanium", "lithium", "magnésium", "manganèse",
    "graphite naturel", "nickel", "platinoïdes (PGM)", "terres rares lourdes", "terres rares légères",
    "silicium métal", "titane métal", "tungstène", "bauxite/alumine/aluminium",
}
# Métaux précieux : pas CRM (sauf PGM) mais pilotent le prix recycleur des cartes.
PRECIEUX = {"or", "argent", "platinoïdes (PGM)"}

# Composition qualitative par type de pièce (présence, pas de teneur). Teneurs réelles : fiche
# matière fabricant (IPC-1752 / déclaration RoHS-REACH) ou analyse du recycleur, à demander.
COMPOSITION_TYPE = {
    # type               (motif sur la description,                                    matières présentes)
    "IGBT / module de puissance": (r"\bigbt\b|power module|mosfet", ["cuivre", "bauxite/alumine/aluminium", "silicium métal", "argent", "étain"]),
    "Condensateur électrolytique": (r"electrolytic|électrolytique|\bcap(acitor)?\b.*\buf\b", ["bauxite/alumine/aluminium", "papier", "électrolyte"]),
    "Condensateur tantale": (r"tantal", ["tantale", "manganèse"]),
    "Carte électronique": (r"board|\bbd\b|\bpwa\b|\bpcb\b|carte|driver|controller|assembly", ["cuivre", "or", "argent", "platinoïdes (PGM)", "étain", "tantale", "gallium", "antimoine", "verre-époxy"]),
    "Fusible": (r"fuse|fusible", ["cuivre", "argent", "céramique"]),
    "Résistance de puissance": (r"resist", ["nickel", "cuivre", "céramique"]),
    "Câble / faisceau": (r"cable|câble|harness|wire", ["cuivre", "PVC"]),
    "Bobine / antenne IRM": (r"\bcoil\b|bobine|antenne", ["cuivre", "verre-époxy", "or", "argent"]),
    "Aimant": (r"magnet|aimant|ndfeb", ["terres rares légères", "terres rares lourdes", "bore", "cobalt"]),
    "Ventilateur / moteur": (r"\bfan\b|ventil|motor|moteur", ["cuivre", "terres rares légères", "plastique"]),
    "Pièce plastique / mécanique": (r"cover|coque|grille|joystick|caoutch|bellow|soufflet|sleeve|key|cap |toggle|handle", ["plastique", "élastomère"]),
}


def type_piece(description: str) -> str:
    d = str(description).lower()
    for t, (motif, _) in COMPOSITION_TYPE.items():
        if re.search(motif, d):
            return t
    return "(type non reconnu)"


def risque_matiere(description: str) -> dict:
    """Score 0–1 : part des matières CRM pondérée (stratégique = 2, CRM = 1), plus indicateurs utiles au recycleur."""
    t = type_piece(description)
    mats = COMPOSITION_TYPE.get(t, (None, []))[1]
    if not mats:
        return {"Type de pièce": t, "Matières (présence)": "", "CRM": "", "Stratégiques": "",
                "Score risque matière (0-1)": np.nan, "Métaux précieux": False}
    crm = [m for m in mats if m in CRM_UE]
    strat = [m for m in mats if m in STRATEGIQUES_UE]
    points = sum(2 if m in STRATEGIQUES_UE else 1 for m in crm)
    return {"Type de pièce": t, "Matières (présence)": ", ".join(mats), "CRM": ", ".join(crm),
            "Stratégiques": ", ".join(strat), "Score risque matière (0-1)": min(points / 8, 1.0),
            "Métaux précieux": any(m in PRECIEUX for m in mats)}


# ---------------------------------------------------------------------------
# 2. Risque supply : table par référence, codée en dur, à remplir avec les achats
# ---------------------------------------------------------------------------
# None = inconnu. Le score n'utilise que les champs renseignés et donne sa couverture.
# Exemple de remplissage : {"5477590": {"Délai (semaines)": 26, "Source unique": True, "Fin de vie (EOL/LTB)": False,
#                                      "Pays d'origine": "JP", "Source": "Achats, mail du 12/11"}}
SUPPLY = {
    "5477590": {"Délai (semaines)": None, "Source unique": None, "Fin de vie (EOL/LTB)": None, "Pays d'origine": None, "Source": "à demander aux achats"},
    "5477591": {"Délai (semaines)": None, "Source unique": None, "Fin de vie (EOL/LTB)": None, "Pays d'origine": None, "Source": "à demander aux achats"},
    "6850032": {"Délai (semaines)": None, "Source unique": None, "Fin de vie (EOL/LTB)": None, "Pays d'origine": None, "Source": "à demander aux achats"},
    "6850030": {"Délai (semaines)": None, "Source unique": None, "Fin de vie (EOL/LTB)": None, "Pays d'origine": None, "Source": "à demander aux achats"},
    "5953513": {"Délai (semaines)": None, "Source unique": None, "Fin de vie (EOL/LTB)": None, "Pays d'origine": None, "Source": "à demander aux achats"},
}
# Score supply = moyenne des sous-scores renseignés. Seuils codés en dur, modifiables.
DELAI_CRITIQUE_SEM = 26


def risque_supply(reference: str, type_p: str = "") -> dict:
    """Risque supply = délai d'approvisionnement seul (choix du projet). Score = délai / DELAI_CRITIQUE_SEM, plafonné à 1.
    Source unique et fin de vie restent dans la table à titre d'information, hors score."""
    s = SUPPLY.get(str(reference), {})
    d = s.get("Délai (semaines)")
    return {"Délai (semaines)": d, "Score risque supply (0-1)": min(d / DELAI_CRITIQUE_SEM, 1.0) if d is not None else np.nan,
            "A priori supply (type)": 0.6 if type_p in ("IGBT / module de puissance", "Carte électronique") else np.nan,
            "Source supply": s.get("Source", "aucune")}


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
def base_ref(r):
    return re.sub(r"-(H|U|R|RA)$", "", str(r).strip().upper())


def origine(r):
    r = str(r).strip().upper()
    return "Récupérée" if r.endswith(("-H", "-U")) else "Réparée" if r.endswith(("-R", "-RA")) else "Neuve"


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


# ---------------------------------------------------------------------------
# 5. Valeur espérée par voie, Monte-Carlo sur les entrées incertaines
# ---------------------------------------------------------------------------
def tirer(x, n):
    """x = nombre, (bas, haut) uniforme, (bas, mode, haut) triangulaire, ou None (inconnu → NaN)."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.full(n, np.nan)
    if isinstance(x, (tuple, list)):
        return RNG.uniform(x[0], x[1], n) if len(x) == 2 else RNG.triangular(x[0], x[1], x[2], n)
    return np.full(n, float(x))


def valeur_voies(p: dict, n=10000) -> dict:
    """Valeur nette espérée par pièce et par voie, avec P(valeur > 0).

    Clés de p (toutes facultatives, None = inconnu) :
      poids_kg, prix_recycleur_eur_kg, tri_min, taux_horaire_eur, mmicv, valeur_reemploi_frac,
      demontage_min, test_min, rendement_test, survie_garantie, cout_defaillance_terrain,
      devis_reman, transport_eur, rendement_reman, bonus_supply_eur
    Coût de main-d'œuvre = minutes / 60 × taux horaire : heures en plus du plan de charge (Stéphan / Lewis).
    """
    T = lambda k: tirer(p.get(k), n)
    h = T("taux_horaire_eur") / 60
    vente = T("poids_kg") * T("prix_recycleur_eur_kg") - T("tri_min") * h
    v_reemploi = T("mmicv") * T("valeur_reemploi_frac") + np.nan_to_num(T("bonus_supply_eur"))
    R = T("survie_garantie")
    harvest = T("rendement_test") * (R * v_reemploi - (1 - R) * T("cout_defaillance_terrain")) \
        - (T("demontage_min") + T("test_min")) * h
    reman = T("rendement_reman") * v_reemploi - T("devis_reman") - T("transport_eur") - T("demontage_min") * h
    out = {}
    for nom, v in [("Vente recycleur", vente), ("Récupération / réemploi", harvest), ("Remanufacturing externe", reman)]:
        if np.isnan(v).all():
            out[nom] = {"moyenne": np.nan, "P5": np.nan, "P95": np.nan, "P(>0)": np.nan}
        else:
            out[nom] = {"moyenne": float(np.mean(v)), "P5": float(np.quantile(v, 0.05)),
                        "P95": float(np.quantile(v, 0.95)), "P(>0)": float(np.mean(v > 0))}
    return out


def manques_voies(p: dict) -> dict:
    besoins = {"Vente recycleur": ["poids_kg", "prix_recycleur_eur_kg", "tri_min", "taux_horaire_eur"],
               "Récupération / réemploi": ["mmicv", "valeur_reemploi_frac", "rendement_test", "survie_garantie",
                                           "cout_defaillance_terrain", "demontage_min", "test_min", "taux_horaire_eur"],
               "Remanufacturing externe": ["mmicv", "valeur_reemploi_frac", "rendement_reman", "devis_reman",
                                           "transport_eur", "demontage_min", "taux_horaire_eur"]}
    return {v: [k for k in ks if p.get(k) is None] for v, ks in besoins.items()}


# ---------------------------------------------------------------------------
# 6. Pré-sélection : front de Pareto plutôt qu'une note unique
# ---------------------------------------------------------------------------
def front_pareto(df: pd.DataFrame, maximiser: list[str]) -> pd.Series:
    """True si aucune autre ligne n'est au moins aussi bonne sur tous les critères et meilleure sur un.
    Les NaN comptent comme le pire niveau : une référence sans donnée ne domine rien."""
    X = df[maximiser].astype(float).fillna(-np.inf).to_numpy()
    domine = np.zeros(len(X), bool)
    for i in range(len(X)):
        domine[i] = np.any(np.all(X >= X[i], axis=1) & np.any(X > X[i], axis=1))
    return pd.Series(~domine, index=df.index)


def score_pondere(df: pd.DataFrame, poids: dict) -> pd.Series:
    """Note 0–1 après normalisation rang-centile ; à n'utiliser qu'après accord de l'équipe sur les poids."""
    s = sum(w * df[c].rank(pct=True).fillna(0) for c, w in poids.items())   # donnée absente = pire niveau
    return s / sum(abs(w) for w in poids.values())
