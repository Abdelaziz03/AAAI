"""Pipeline : sept étapes qui lisent les sources, calculent, et déposent chaque résultat dans les artefacts.

    sources → classement → flux → fiabilite → rex → ligne → synthese

Chaque étape renvoie un dictionnaire {nom: table ou objet} et écrit les mêmes objets dans artefacts/<NN_étape>/.
Un calcul qui échoue n'arrête pas le pipeline : il est inscrit dans la table « Anomalies » (étape sources) et
l'artefact correspondant reste vide. Les notebooks appellent `executer(jusqua="...")` puis affichent les artefacts.
"""
from __future__ import annotations

import traceback
from datetime import datetime

import numpy as np
import pandas as pd

from . import classement as mod_cl
from . import fiabilite as mod_fiab
from . import flux as mod_flux
from . import ligne as mod_ligne
from . import parametres as mod_par
from . import rex as mod_rex
from .artefacts import Depot, vers_json
from .config import ETAPES, Config, charger as charger_config
from .sources import Sources, base_ref, charger as charger_sources, origine


class Contexte:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.depot = Depot(cfg.artefacts, cfg.demo)
        self.src: Sources | None = None
        self.params: mod_par.Parametres | None = None
        self.res: dict[str, dict] = {}
        self.anomalies: list[dict] = []
        self.faites: list[str] = []

    def essayer(self, etape: str, quoi: str, fonction, defaut=None):
        """Exécute un calcul ; en cas d'erreur, l'inscrit aux anomalies et renvoie `defaut`."""
        try:
            return fonction()
        except Exception as e:
            self.anomalies.append({"Étape": etape, "Calcul": quoi, "Erreur": f"{type(e).__name__}: {e}"[:400],
                                   "Détail": traceback.format_exc(limit=3)[-600:]})
            return defaut() if callable(defaut) else defaut

    def deposer(self, etape: str, tables: dict, descriptions: dict | None = None):
        """Dépose tables (DataFrame) et objets (dict/list → JSON), puis les figures et le classeur de l'étape."""
        descriptions = descriptions or {}
        for nom, obj in tables.items():
            if isinstance(obj, pd.DataFrame):
                self.depot.table(etape, nom, obj, descriptions.get(nom, ""))
            elif obj is not None:
                self.depot.json(etape, nom, obj, descriptions.get(nom, ""))
        self.res[etape] = tables
        try:
            from . import figures
            import matplotlib.pyplot as plt
            for nom, description, fig in figures.tracer(etape, self):
                self.depot.figure(etape, nom, fig, description)
                plt.close(fig)
        except Exception as e:                                # une figure ratée ne doit pas faire perdre les tables
            self.anomalies.append({"Étape": etape, "Calcul": "figures", "Erreur": f"{type(e).__name__}: {e}"[:400],
                                   "Détail": traceback.format_exc(limit=3)[-600:]})
        self.depot.classeur(etape)
        self.depot.ecrire_manifeste()
        self.faites.append(etape)
        return tables


def _vide(*cols):
    return pd.DataFrame(columns=list(cols))


# =========================================================================== 0. sources
def etape_sources(ctx: Contexte) -> dict:
    cfg = ctx.cfg
    ctx.src = charger_sources(cfg)
    ctx.params = mod_par.lire(cfg)
    mod_par.appliquer_aux_sources(ctx.params, ctx.src)
    s = ctx.src
    perimetre = {"mode": cfg.mode, "demo": cfg.demo, "periode": s.periode, "jours_extraits": len(s.couverts),
                 "debut": min(s.couverts) if s.couverts else None, "fin": max(s.couverts) if s.couverts else None,
                 "lignes_consommation": len(s.ev), "pieces_consommees": float(s.ev["Qte"].sum()) if len(s.ev) else 0.0,
                 "fru_rebutees": float(s.fru_rebutees["Unités"].sum()) if len(s.fru_rebutees) else 0.0,
                 "regle_date_rebut": s.regle_date_rebut, "ateliers_prioritaires": cfg.ateliers_prioritaires,
                 "classeur_parametres": "présent" if ctx.params.existe else "absent : il sera créé à l'étape classement",
                 "genere_le": datetime.now().isoformat(timespec="seconds"), **{k: v for k, v in cfg.resume().items()}}
    return ctx.deposer("sources", {"État des sources": s.etat_df(), "Périmètre": perimetre},
                       {"État des sources": "Chaque fichier attendu : chargé, absent ou en erreur, et ce à quoi il sert",
                        "Périmètre": "Mode (réel ou démonstration), période couverte, volumes lus, chemins"})


# =========================================================================== 1. classement
def etape_classement(ctx: Contexte) -> dict:
    cfg, s = ctx.cfg, ctx.src
    E = "classement"
    tous = ctx.essayer(E, "classement tous ateliers", lambda: mod_cl.classement(s.ev, s), lambda: mod_cl.classement(s.ev.iloc[:0], s))
    par_atelier = {a: ctx.essayer(E, f"classement {a}", lambda a=a: mod_cl.classement(s.ev[s.ev["Atelier"].eq(a)], s), tous.iloc[:0])
                   for a in cfg.ateliers_prioritaires}
    cal, par_mois = ctx.essayer(E, "calendrier", lambda: mod_cl.calendrier(s), (_vide("Mois"), pd.DataFrame()))
    rebut, source_rebut = ctx.essayer(E, "FRU rebutées", lambda: mod_cl.fru_rebutees(s), (_vide("Atelier", "FRU", "Description FRU", "FRU rebutées"), "erreur"))
    couples = ctx.essayer(E, "couples FRU x pièce", lambda: mod_cl.couples_fru_piece(s), _vide("FRU", "Pièce"))
    contenu = ctx.essayer(E, "composants des FRU rebutées", lambda: mod_cl.composants_fru_rebutees(s, rebut, couples), _vide("Référence"))
    # Le classeur de paramètres est créé ici, une fois, avec les FRU et les pièces trouvés dans les données.
    cree = ctx.essayer(E, "gabarit des paramètres", lambda: _creer_classeur(ctx, rebut, couples, tous), False)
    if cree:
        ctx.params = mod_par.lire(cfg)
        mod_par.appliquer_aux_sources(ctx.params, s)
    chiffres = ctx.essayer(E, "chiffres à vérifier", lambda: mod_cl.chiffres_a_verifier(s, ctx.params.chiffres, cal), _vide("Chiffre"))
    prio = ctx.essayer(E, "priorisation", lambda: mod_cl.priorisation(tous, contenu), pd.DataFrame())
    tables = {"Classement tous ateliers": tous, **{f"Classement {a}": t for a, t in par_atelier.items()}, "Mois calendrier": cal, "Pièces par mois": par_mois,
              "Chiffres à vérifier": chiffres, "FRU rebutées": rebut, "Couples FRU x pièce": couples, "Composants des FRU rebutées": contenu,
              "Priorisation": prio,
              "Notes": {"source_fru_rebutees": source_rebut, "classeur_parametres_cree": bool(cree),
                        "criteres_actifs": prio.attrs.get("Critères actifs", []), "criteres_inactifs": prio.attrs.get("Critères inactifs faute de données", [])}}
    return ctx.deposer(E, tables, {
        "Classement tous ateliers": "Pièces consommées sur la période : volume, MMICV unitaire et total, type de déchet, poids",
        "FRU rebutées": "FRU rebutées par type sur la période, avec poids",
        "Couples FRU x pièce": "Par couple : pièces consommées, réparations du FRU, maximum observé sur un PO (minimum de pièces par FRU)",
        "Composants des FRU rebutées": "Pièces présentes dans la nomenclature de consommation des FRU rebutées",
        "Priorisation": "Critères de pré-sélection (valeur, gisement, risque matière, risque supply) et front de Pareto"})


def _creer_classeur(ctx: Contexte, rebut, couples, tous) -> bool:
    cfg = ctx.cfg
    if cfg.classeur.is_file():
        return False
    tables = mod_par.tables_gabarit(cfg, ctx.src, rebut, couples, tous)
    if cfg.demo:
        from . import demo
        tables = demo.remplir_parametres(tables)
    mod_par.ecrire_classeur(cfg.classeur, tables)
    return True


# =========================================================================== 2. flux
def etape_flux(ctx: Contexte) -> dict:
    cfg, s = ctx.cfg, ctx.src
    E = "flux"
    tous = ctx.res["classement"]["Classement tous ateliers"]
    comp = ctx.essayer(E, "composants et type de déchet", lambda: mod_flux.tableau_composants(tous), _vide("Référence", "Type de déchet", "Benne", "Poids unitaire (kg)"))
    comp_fru = ctx.essayer(E, "composant x FRU x type de déchet", lambda: _composant_fru(s, tous), _vide("FRU", "Référence"))
    synthese = ctx.essayer(E, "synthèse par benne", lambda: comp.groupby(["Benne", "Type de déchet"], dropna=False).agg(
        Références=("Référence", "nunique"), Pièces=("Pièces", "sum"), **{"Références au poids connu": ("Poids connu", "sum"),
            # min_count=1 : un type de déchet dont aucun poids n'est connu a une masse inconnue, pas une masse nulle
            "Kg (poids connus)": ("Kg (poids connus)", lambda x: x.sum(min_count=1))}).reset_index(), _vide("Benne"))
    flux_fru = ctx.essayer(E, "FRU rebutées par semaine", lambda: mod_flux.flux_fru_hebdo(s.fru_rebutees, s.couverts, s.poids_fru)
                           if len(s.fru_rebutees) else _vide("Semaine", "FRU", "FRU rebutées", "Jours extraits", "Semaine complète"),
                           _vide("Semaine", "FRU", "FRU rebutées", "Jours extraits", "Semaine complète"))
    rebut_an = ctx.essayer(E, "rebut annuel", lambda: mod_flux.rebut_annuel(flux_fru) if len(flux_fru) else _vide("FRU", "rebut_an"), _vide("FRU", "rebut_an"))
    est = ctx.essayer(E, "masse estimée par semaine", lambda: mod_flux.estimation_hebdo(s.ev, comp, s.couverts, par=cfg.par_flux), _vide("Semaine", "Flux"))
    rap = ctx.essayer(E, "estimé contre pesé", lambda: mod_flux.rapprocher(est, s.pesees), _vide("Semaine", "Flux", "Dans la marge"))
    verdict = ctx.essayer(E, "verdict par flux", lambda: _verdict(rap), _vide("Flux"))
    tables = {"Composant FRU type de déchet": comp_fru, "Composants type de déchet": comp, "Synthèse par benne": synthese,
              "FRU rebutées par semaine": flux_fru, "Rebut annuel": rebut_an, "Masse estimée par semaine": est,
              "Estimé contre pesé": rap, "Verdict par flux": verdict,
              "Notes": {"regle_date_rebut": s.regle_date_rebut, "granularite": cfg.par_flux, "semaines_pesees": int(s.pesees["Semaine"].nunique()) if len(s.pesees) else 0}}
    return ctx.deposer(E, tables, {
        "Composant FRU type de déchet": "Une ligne par couple (FRU, composant) : type de déchet, benne, poids",
        "FRU rebutées par semaine": "Flux d'entrée du modèle : FRU rebutées par semaine et par type (0 les semaines sans rebut)",
        "Rebut annuel": "FRU rebutées par an (bas, moyen, haut) tirées des semaines complètes",
        "Masse estimée par semaine": "Masse estimée par semaine et par flux, avec marge d'erreur",
        "Estimé contre pesé": "Semaine, valeur estimée et mesurée, marge d'erreur, causes candidates de l'écart, cause constatée à saisir",
        "Verdict par flux": "Le flux est-il assez bien vérifié pour alimenter le modèle ?"})


def _composant_fru(s: Sources, tous: pd.DataFrame) -> pd.DataFrame:
    t = mod_flux.tableau_composants(tous, s.ev)
    if "FRU" in t and len(t):
        t.insert(1, "Atelier du FRU", t["FRU"].map(s.atelier_fru).fillna("(non rattaché)"))
        t.insert(1, "Description FRU", t["FRU"].map(s.desc_fru))
    return t


def _verdict(rap: pd.DataFrame) -> pd.DataFrame:
    cols = ["Flux", "Semaines comparées", "Semaines dans la marge", "Écart moyen (%)", "Écart cumulé final (%)", "Couverture poids moyenne", "Utilisable par le modèle"]
    if not len(rap) or "Dans la marge" not in rap:
        return pd.DataFrame(columns=cols)
    c = rap[rap["Dans la marge"].ne("non comparable")]
    if not len(c):
        return pd.DataFrame(columns=cols)
    v = c.groupby("Flux").agg(**{"Semaines comparées": ("Semaine", "nunique"), "Semaines dans la marge": ("Dans la marge", lambda x: int((x == "oui").sum())),
                                 "Écart moyen (%)": ("Écart (%)", "mean"), "Écart cumulé final (%)": ("Écart cumulé (%)", "last"),
                                 "Couverture poids moyenne": ("Couverture poids", "mean")}).reset_index()
    v["Utilisable par le modèle"] = np.where((v["Semaines comparées"] >= 3) & (v["Écart cumulé final (%)"].abs() <= 0.15), "oui",
                                             np.where(v["Semaines comparées"] < 3, "pas assez de semaines (3 minimum)", "non : corriger la cause dominante"))
    return v[cols]


# =========================================================================== 3. fiabilité
def etape_fiabilite(ctx: Contexte) -> dict:
    cfg, s = ctx.cfg, ctx.src
    E = "fiabilite"
    fiab = ctx.essayer(E, "fiabilité par référence", lambda: mod_fiab.fiabilite_par_reference(s.elf, cfg.fenetre_elf_jours, s.poses).sort_values(
        "Défaillances ELF", ascending=False).reset_index(drop=True) if len(s.elf) else _vide("Référence", "Origine posée"), _vide("Référence", "Origine posée"))
    km = ctx.essayer(E, "Kaplan-Meier", lambda: _km(s.elf, fiab), _vide("Référence", "Origine posée", "t", "S(t)"))
    grille = pd.DataFrame([{"Forme k": k, "Lecture": mod_fiab.lecture_forme(k).split(" :")[0], "Âge du donneur (j)": a,
                            "P(tenir la garantie)": float(mod_fiab.survie_conditionnelle(a, cfg.garantie_jours, k, 1000.0)),
                            "Vie résiduelle moyenne (j)": float(mod_fiab.vie_residuelle_moyenne(a, k, 1000.0))}
                           for k in (0.7, 1.0, 2.5) for a in (0, 180, 730, 1500)])
    physique = pd.DataFrame([
        ("Condensateur électrolytique", "Séchage de l'électrolyte (usure)", "La vie double tous les 10 °C sous la température nominale",
         "Vie nominale (h) et température nominale, température de service", "Fiche du fabricant, mesure dans le FRU"),
        ("IGBT / module de puissance", "Fatigue en cyclage thermique", "Coffin-Manson : nombre de cycles ∝ ΔTj^-n, n ≈ 5",
         "Amplitude de température de jonction ΔTj, constante du module", "Fiche du fabricant, conception"),
    ], columns=["Type de pièce", "Mécanisme", "Loi", "Paramètres à lire", "Source"])
    prio = ctx.res["classement"].get("Priorisation", pd.DataFrame())
    if len(prio) and len(fiab):                                # la fiabilité devient un critère de la pré-sélection
        tous, contenu = ctx.res["classement"]["Classement tous ateliers"], ctx.res["classement"]["Composants des FRU rebutées"]
        prio = ctx.essayer(E, "priorisation avec fiabilité", lambda: mod_cl.priorisation(tous, contenu, fiab), prio)
    tables = {"Fiabilité par référence": fiab, "Courbes de Kaplan-Meier": km, "Vie résiduelle (grille illustrative)": grille,
              "A priori physiques": physique, "Priorisation avec fiabilité": prio,
              "Notes": {"lignes_elf": len(s.elf), "denominateur": "chargé" if s.poses is not None else "absent : pas de taux, seulement la forme",
                        "fenetre_elf_jours": cfg.fenetre_elf_jours or (float(pd.to_numeric(s.elf["elf_days"], errors="coerce").max()) if len(s.elf) and "elf_days" in s.elf else None),
                        "garantie_jours": cfg.garantie_jours, "criteres_actifs": prio.attrs.get("Critères actifs", []) if len(prio) else []}}
    return ctx.deposer(E, tables, {
        "Fiabilité par référence": "Par référence et origine (neuve, réparée, récupérée) : défaillances précoces, forme de Weibull, taux et rapport au neuf",
        "Vie résiduelle (grille illustrative)": "Effet de la forme k et de l'âge du donneur sur la tenue de la garantie (échelle arbitraire de 1 000 jours)",
        "Priorisation avec fiabilité": "Pré-sélection de l'étape classement, avec le critère de fiabilité du réemploi quand il existe"})


def _km(elf: pd.DataFrame, fiab: pd.DataFrame, n_refs: int = 6) -> pd.DataFrame:
    cols = ["Référence", "Origine posée", "t", "à risque", "défaillances", "S(t)"]
    if not len(elf) or not len(fiab):
        return pd.DataFrame(columns=cols)
    e = elf.assign(Base=elf["replacement_part_no"].map(base_ref), Origine=elf["replacement_part_no"].map(origine),
                   t=pd.to_numeric(elf["elf_days"], errors="coerce")).dropna(subset=["t"])
    out = []
    for b in fiab["Référence"].drop_duplicates().head(n_refs):
        for o, g in e[e["Base"].eq(b)].groupby("Origine"):
            k = mod_fiab.kaplan_meier(g["t"], np.ones(len(g)))
            out.append(k.assign(**{"Référence": b, "Origine posée": o}))
    return pd.concat(out, ignore_index=True)[cols] if out else pd.DataFrame(columns=cols)


# =========================================================================== 4. modèle de Rex
def etape_rex(ctx: Contexte) -> dict:
    s, p = ctx.src, ctx.params
    E = "rex"
    couples = ctx.res["classement"]["Couples FRU x pièce"]
    prior = ctx.essayer(E, "a priori de consommation", lambda: mod_par.a_priori_rex(p, couples), _vide("Type de FRU", "Pièce", "q0"))
    ap = prior[["Type de FRU", "Pièce", "q0"]].astype({"q0": float}) if len(prior) else pd.DataFrame({"Type de FRU": [], "Pièce": [], "q0": pd.Series(dtype=float)})
    audit = s.audit
    n0 = ctx.essayer(E, "réglage de N0", lambda: mod_rex.regler_n0(audit, ap), _vide("N0", "Log-perte"))
    post = ctx.essayer(E, "a posteriori", lambda: mod_rex.entrainer(audit, ap), _vide("Type de FRU", "Pièce", "q0", "Pièces testées", "q moyen"))
    if len(post):
        post["Transmis au modèle de ligne"] = np.where((post["Pièces testées"] > 0) | post["q0"].notna(), "oui", "non : ni audit ni a priori")
    ev = ctx.essayer(E, "évaluation", lambda: mod_rex.evaluer(audit, ap), {"detail": pd.DataFrame(), "metriques": pd.DataFrame()})
    banc = ctx.essayer(E, "banc d'essai des politiques", lambda: mod_rex.simuler_politiques(q_vrai=0.6, q0=0.2, gain_bonne=40.0, gain_mauvaise=-12.0, gain_recyclage=2.0),
                       pd.DataFrame())
    courbes = pd.DataFrame({r["Politique"]: r["Courbe"] for _, r in banc.iterrows()}).rename_axis("Pièce n°").reset_index() if len(banc) else pd.DataFrame()
    tables = {"A priori (consommation)": prior, "Audit de démontage": audit, "A posteriori": post, "Métriques": ev["metriques"],
              "Prédictions lot par lot": ev["detail"], "Réglage de N0": n0,
              "Banc d'essai des politiques": banc.drop(columns="Courbe") if len(banc) else banc, "Banc d'essai (courbes de regret)": courbes,
              "Notes": {"lots_audit": len(audit), "pieces_testees": float(audit["Pièces testées"].sum()) if len(audit) else 0.0, "N0": mod_rex.N0,
                        "banc_essai": dict(banc.attrs) if len(banc) else {}, "banc_essai_synthetique": True}}
    return ctx.deposer(E, tables, {
        "A priori (consommation)": "q0 par (FRU, pièce) tiré de la consommation, avec le détail du calcul et les correctifs appliqués",
        "A posteriori": "Probabilité qu'une pièce extraite soit réutilisable : moyenne et intervalle à 90 %, après l'audit",
        "Métriques": "Brier, log-perte, écart absolu, couverture : chaque lot est prédit avant d'être appris ; deux références à battre",
        "Banc d'essai des politiques": "Simulation SYNTHÉTIQUE : regret des règles de décision quand l'a priori est trop pessimiste"})


# =========================================================================== 5. ligne de démontage et de tri
def etape_ligne(ctx: Contexte) -> dict:
    cfg, s, p = ctx.cfg, ctx.src, ctx.params
    E = "ligne"
    couples = ctx.res["classement"]["Couples FRU x pièce"]
    rebut = ctx.res["classement"]["FRU rebutées"]
    flux_fru, rebut_an = ctx.res["flux"]["FRU rebutées par semaine"], ctx.res["flux"]["Rebut annuel"]
    post = ctx.res["rex"]["A posteriori"]
    LIGNE, FRUS, prov = ctx.essayer(E, "résolution des paramètres", lambda: mod_par.resoudre(cfg, p, s, couples, rebut_an, post, rebut),
                                    ({}, {}, _vide("FRU", "Pièce", "Paramètre", "Valeur", "Provenance", "État")))
    a_obtenir = ctx.essayer(E, "données à obtenir", lambda: mod_par.a_obtenir(prov, FRUS), _vide("Paramètre"))
    lg, fr = mod_ligne._milieu(LIGNE), mod_ligne._milieu(FRUS)
    c_trait = lg.get("cout_traitement_eur_kg")

    def options():
        out = []
        for f, d in fr.items():
            t = mod_ligne.valeurs_options(dict(d, _c_trait=c_trait), lg.get("taux_horaire_eur"))
            if len(t):
                t.insert(0, "Type de FRU", f)
                t["Ouverture soignée (€/FRU)"], t["Ouverture sommaire (€/FRU)"] = t.attrs.get("Ouverture soignée (€/FRU)"), t.attrs.get("Ouverture sommaire (€/FRU)")
                out.append(t)
        return pd.concat(out, ignore_index=True) if out else _vide("Type de FRU", "Pièce")
    opts = ctx.essayer(E, "valeur des trois options", options, _vide("Type de FRU", "Pièce"))
    base = ctx.essayer(E, "optimisation de la ligne", lambda: mod_ligne.optimiser_ligne(lg, fr), {"detail": pd.DataFrame(), "resume": {}})
    scen = ctx.essayer(E, "actuel contre ligne", lambda: mod_ligne.comparer_scenarios(LIGNE, FRUS), pd.DataFrame())
    par_periode = ctx.essayer(E, "période par période", lambda: mod_ligne.resultat_par_periode(LIGNE, FRUS, flux_fru) if len(flux_fru) else pd.DataFrame(), pd.DataFrame())
    mc = ctx.essayer(E, "Monte-Carlo", lambda: mod_ligne.monte_carlo_ligne(LIGNE, FRUS, n=cfg.n_monte_carlo, rng=np.random.default_rng(cfg.graine)), {})
    tirages = mc.get("tirages", pd.DataFrame())
    H = lg.get("heures_operateur_an")

    def sensibilite():
        if not H:
            return _vide("Heures / an", "Résultat / an (€)")
        garder = ("Résultat / an (€)", "Marge variable / an (€)", "FRU traitées / an", "Taux d'occupation", "Valeur d'une heure opérateur en plus (€ net)")
        return pd.DataFrame([{"Heures / an": round(H * m), **{k: v for k, v in mod_ligne.optimiser_ligne(dict(lg, heures_operateur_an=H * m), fr)["resume"].items() if k in garder}}
                             for m in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0)])
    sens = ctx.essayer(E, "sensibilité aux heures", sensibilite, _vide("Heures / an"))
    resume = base.get("resume", {})
    tables = {"Paramètres effectifs": prov, "Données à obtenir": a_obtenir, "Options par pièce": opts, "Plan optimal": base.get("detail", pd.DataFrame()),
              "Résumé": pd.DataFrame([{"Indicateur": k, "Valeur": v} for k, v in resume.items()]),
              "Actuel contre ligne": scen, "Période par période": par_periode,
              "Monte-Carlo (tirages)": tirages[[c for c in ("Résultat / an (€)", "Marge variable / an (€)", "Heures utilisées / an", "FRU traitées / an") if c in tirages]] if len(tirages) else tirages,
              "Sensibilité aux heures": sens,
              "Modèle": {"ligne": LIGNE, "frus": FRUS},
              "Notes": {"resume": resume, "actuel_contre_ligne": dict(scen.attrs) if len(scen) else {}, "periode_par_periode": dict(par_periode.attrs) if len(par_periode) else {},
                        "monte_carlo": {k: v for k, v in mc.items() if k != "tirages"}, "types_de_fru": len(FRUS),
                        "types_incomplets": int(resume.get("Types de FRU incomplets", 0) or 0)}}
    return ctx.deposer(E, tables, {
        "Paramètres effectifs": "Chaque paramètre du modèle avec sa valeur et sa provenance : saisi, tiré des données, ou manquant",
        "Données à obtenir": "Ce qui manque pour calculer, et à qui le demander",
        "Options par pièce": "Valeur nette par FRU des trois options de chaque pièce : réemploi, recyclage trié, laissée dans le FRU",
        "Plan optimal": "Pour chaque type de FRU : traiter ou non, pièces à réemployer et à recycler, heures et marge",
        "Actuel contre ligne": "Coût de la situation actuelle (recycleur actuel) contre la ligne de démontage et de tri",
        "Période par période": "Le modèle rejoué sur le flux hebdomadaire réel : coût fixe payé chaque semaine, pas de stock",
        "Monte-Carlo (tirages)": "Résultat annuel pour chaque tirage des plages de paramètres",
        "Sensibilité aux heures": "Résultat et valeur d'une heure supplémentaire selon les heures opérateur disponibles",
        "Modèle": "Paramètres effectifs sous la forme lue par le modèle (plages comprises)"})


# =========================================================================== 6. synthèse et outil des décideurs
def etape_synthese(ctx: Contexte) -> dict:
    E = "synthese"
    donnees = ctx.essayer(E, "données de l'outil", lambda: donnees_outil(ctx), {})
    lg = ctx.res["ligne"]
    notes = lg["Notes"]
    r, mc = notes.get("resume", {}), notes.get("monte_carlo", {})
    scen = lg["Actuel contre ligne"]

    def fmt(v, unite="", dec=0):
        return "inconnu" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{v:,.{dec}f}".replace(",", " ").replace(".", ",") + unite
    total = scen.loc[scen["Poste (€/an)"].eq("TOTAL")].iloc[0] if len(scen) else {}
    pp = notes.get("periode_par_periode", {})
    decision = pd.DataFrame([
        ("Gain annuel par rapport à la situation actuelle", fmt(total.get("Écart") if len(scen) else None, " €"), "Total « avec la ligne » moins total « actuel », au centre des plages"),
        ("Probabilité que la ligne soit rentable", fmt(100 * mc.get("P(ligne rentable)", np.nan), " %"), f"{ctx.cfg.n_monte_carlo} tirages des plages de paramètres"),
        ("Résultat annuel : P5 / médiane / P95", " / ".join(fmt(v, " €") for v in mc.get("Résultat P5 / médiane / P95 (€)", (np.nan,) * 3)), "Monte-Carlo"),
        ("Résultat annualisé, semaine par semaine", fmt(pp.get("Résultat annualisé, période par période (€)"), " €"), "Flux hebdomadaire réel, coût fixe payé chaque semaine, pas de stock"),
        ("Coût de la variabilité du flux", fmt(pp.get("Coût de la variabilité du flux (€/an)"), " €/an"), "Écart entre le modèle annuel au flux moyen et le calcul semaine par semaine"),
        ("Seuil de rentabilité", fmt(r.get("Seuil de rentabilité (FRU / an)"), " FRU/an"), "Coûts fixes annualisés ÷ marge moyenne par FRU"),
        ("Retour sur investissement", fmt(r.get("Retour sur investissement (ans)"), " ans", 1), "Investissement ÷ (marge variable − coûts fixes annuels)"),
        ("Heures utilisées / capacité", f"{fmt(r.get('Heures utilisées / an'), ' h')} / {fmt(r.get('Capacité (h/an)'), ' h')}", "Au centre des plages"),
        ("Valeur d'une heure opérateur en plus", fmt(r.get("Valeur d'une heure opérateur en plus (€ net)"), " €"), "Marge nette qu'apporterait une heure de plus (0 si la capacité n'est pas saturée)"),
        ("Masse détournée de la benne actuelle", fmt(r.get("Masse détournée de la benne (kg/an)"), " kg/an"), "Pièces réemployées ou triées"),
        ("Types de FRU incomplets", fmt(float(notes.get("types_incomplets", 0))), "FRU exclus du calcul faute de paramètres : voir « Données à obtenir »"),
    ], columns=["Indicateur", "Valeur", "Lecture"])
    lecture = pd.DataFrame([
        ("Mode", ctx.cfg.mode), ("Période", ctx.src.periode),
        ("MMICV", "Coût standard : référence provisoire, ni prix de revente ni valeur de réemploi. Devise à confirmer."),
        ("Nombre de pièces par FRU", "Inconnu sans audit de démontage : le maximum observé sur un PO est un minimum."),
        ("Fiabilité", "Le fichier de fiabilité ne contient que des défaillances : il donne la forme et un taux précoce, pas une durée de vie."),
        ("Valeurs potentielles", "Estimations, distinctes des recettes réelles. Toute entrée inconnue laisse le résultat vide."),
        ("Banc d'essai du modèle de Rex", "Simulation synthétique : démontre la méthode, ne décrit pas l'atelier."),
    ], columns=["Élément", "À savoir"])
    tables = {"Tableau de décision": decision, "Limites et lecture": lecture, "Anomalies": pd.DataFrame(ctx.anomalies, columns=["Étape", "Calcul", "Erreur", "Détail"]),
              "Données de l'outil": donnees}
    ctx.deposer(E, tables, {"Tableau de décision": "Les indicateurs de décision au centre des plages et en probabilité",
                            "Anomalies": "Calculs qui ont échoué pendant l'exécution (table vide = aucun)",
                            "Données de l'outil": "Tout ce que l'outil des décideurs affiche et recalcule"})
    chemin = ctx.essayer(E, "outil des décideurs", lambda: _construire_outil(ctx, donnees), None)
    tables["Outil"] = {"chemin": str(chemin) if chemin else None}
    # Une anomalie survenue pendant les figures ou la construction de l'outil doit aussi être dans la table déposée.
    tables["Anomalies"] = pd.DataFrame(ctx.anomalies, columns=["Étape", "Calcul", "Erreur", "Détail"])
    ctx.depot.table(E, "Anomalies", tables["Anomalies"], "Calculs qui ont échoué pendant l'exécution (table vide = aucun)")
    ctx.depot.classeur(E)
    ctx.depot.ecrire_manifeste()
    return tables


def _construire_outil(ctx: Contexte, donnees: dict):
    from . import outil
    chemin = outil.construire(donnees, ctx.cfg.artefacts / "outil" / "ERC_Outil_Decision.html")
    ctx.depot.fichier("synthese", "Outil des décideurs", chemin, "Page autonome : s'ouvre dans un navigateur, recalcule le modèle en direct", "outil")
    return chemin


CLES_PIECE_MODELE = ["n_par_fru", "extraction_min", "test_min", "tri_min", "p_reutilisable", "valeur_eur", "delai_semaines",
                     "valeur_semaine_eur", "transport_eur", "poids_kg", "prix_recycleur_eur_kg"]


def _param(v, provenance: str = "") -> dict:
    """Paramètre pour l'outil : valeur centrale, bornes, loi de tirage (fixe, uniforme, triangulaire), provenance."""
    b = mod_par.bornes(v)
    if b is None:
        return {"valeur": None, "bas": None, "haut": None, "loi": None, "provenance": provenance or "manquant"}
    loi = "fixe" if not isinstance(v, tuple) else "uniforme" if len(v) == 2 else "triangulaire"
    return {"valeur": b[1], "bas": b[0], "haut": b[2], "loi": loi, "provenance": provenance}


def donnees_outil(ctx: Contexte) -> dict:
    """Données de l'outil des décideurs. Chaque paramètre du modèle est un dictionnaire
    {valeur (centre), bas, haut, loi (fixe, uniforme, triangulaire ou None), provenance} ; valeur None = inconnu.
    Clés : meta, ligne, frus (avec leurs pièces), reference (résultats Python au centre des plages), monte_carlo,
    periodes, flux, priorisation, rex, a_obtenir, sources, anomalies."""
    cfg, s = ctx.cfg, ctx.src
    lg = ctx.res["ligne"]
    modele = lg["Modèle"]
    prov = lg["Paramètres effectifs"]
    pv = {(r["FRU"], r["Pièce"], r["Paramètre"]): r["Provenance"] for _, r in prov.iterrows()} if len(prov) else {}
    cl = s.classification
    from .risques import risque_matiere
    ligne = {k: {**_param(modele["ligne"].get(k), pv.get(("(ligne)", "", k), "")), "libelle": v[0], "unite": v[1], "a_demander_a": v[2]}
             for k, v in mod_par.P_LIGNE.items()}
    frus = []
    for f, d in modele["frus"].items():
        pieces = []
        for pc, e in d.get("pieces", {}).items():
            desc = e.get("description") or ""
            rm = risque_matiere(desc) if pc != mod_par.CARCASSE else {}
            item = {"piece": pc, "description": desc, "type_piece": rm.get("Type de pièce", "Carcasse"),
                    "type_dechet": cl.at[pc, "Catégorie proposée"] if pc in cl.index else None, "benne": cl.at[pc, "Benne"] if pc in cl.index else None,
                    "risque_matiere": rm.get("Score risque matière (0-1)"), "crm": rm.get("CRM", "")}
            for k in CLES_PIECE_MODELE:                        # seulement ce que le modèle de ligne lit
                if k in e or pc != mod_par.CARCASSE:
                    item[k] = _param(e.get(k), pv.get((f, pc, k), ""))
            pieces.append(item)
        item = {"fru": f, "description": d.get("description") or "", "atelier": d.get("atelier") or "", "pieces": pieces}
        for k in ("rebut_an", "poids_fru_kg", "ouverture_min", "ouverture_tri_min", "taux_horaire_eur"):
            item[k] = _param(d.get(k), pv.get((f, "", k), ""))
        frus.append(item)
    notes = lg["Notes"]
    mc = notes.get("monte_carlo", {})
    tir = lg["Monte-Carlo (tirages)"]
    rap = ctx.res["flux"]["Estimé contre pesé"]
    prio = ctx.res["fiabilite"].get("Priorisation avec fiabilité", pd.DataFrame())
    cols_prio = ["Référence", "Description", "Ateliers", "Pièces", "MMICV total (USD)", "Type de pièce", "CRM", "Score risque matière (0-1)",
                 "Risque supply retenu", "Source supply retenue", "FRU rebutées (nomenclature)", "Fiabilité réemploi (1/rapport)", "Sur le front de Pareto"]
    return vers_json({
        "meta": {"genere_le": datetime.now().isoformat(timespec="seconds"), "donnees": "démonstration" if cfg.demo else "réelles",
                 "periode": s.periode, "jours_extraits": len(s.couverts), "ateliers": cfg.ateliers_prioritaires, "garantie_jours": cfg.garantie_jours},
        "ligne": ligne, "frus": frus,
        "reference": {"resume": notes.get("resume", {}), "plan": lg["Plan optimal"], "actuel_contre_ligne": lg["Actuel contre ligne"],
                      "options": lg["Options par pièce"], "sensibilite_heures": lg["Sensibilité aux heures"]},
        "monte_carlo": {"p_rentable": mc.get("P(ligne rentable)"), "p5_mediane_p95": mc.get("Résultat P5 / médiane / P95 (€)"),
                        "tirages": [None if pd.isna(v) else round(float(v), 1) for v in tir["Résultat / an (€)"]] if len(tir) and "Résultat / an (€)" in tir else [],
                        "n": cfg.n_monte_carlo, "frequence_traitement": mc.get("Fréquence de traitement par type de FRU", {})},
        "periodes": {"table": lg["Période par période"], "resume": notes.get("periode_par_periode", {})},
        "flux": {"fru_hebdo": ctx.res["flux"]["FRU rebutées par semaine"], "rebut_annuel": ctx.res["flux"]["Rebut annuel"].drop(columns="rebut_an", errors="ignore"),
                 "rapprochement": rap[[c for c in ("Semaine", "Flux", "Estimé bas (kg)", "Estimé central (kg)", "Estimé haut (kg)", "Marge d'erreur (± kg)", "Masse mesurée (kg)",
                                                   "Écart (%)", "Dans la marge", "Écart cumulé (%)", "Causes candidates de l'écart") if c in rap]] if len(rap) else [],
                 "verdict": ctx.res["flux"]["Verdict par flux"], "regle_date_rebut": s.regle_date_rebut},
        "priorisation": prio[[c for c in cols_prio if c in prio]].head(60) if len(prio) else [],
        "rex": {"posterieur": ctx.res["rex"]["A posteriori"].drop(columns=["a", "b"], errors="ignore"), "metriques": ctx.res["rex"]["Métriques"],
                "banc_essai": ctx.res["rex"]["Banc d'essai des politiques"]},
        "a_obtenir": lg["Données à obtenir"], "sources": s.etat_df(),
        "anomalies": ctx.anomalies,
    })


# =========================================================================== exécution
FONCTIONS = {"sources": etape_sources, "classement": etape_classement, "flux": etape_flux, "fiabilite": etape_fiabilite,
             "rex": etape_rex, "ligne": etape_ligne, "synthese": etape_synthese}


def executer(jusqua: str = "synthese", cfg: Config | None = None, silencieux: bool = False, **options) -> Contexte:
    """Exécute les étapes dans l'ordre jusqu'à `jusqua` incluse et renvoie le contexte (ctx.res, ctx.depot, ctx.src)."""
    if jusqua not in ETAPES:
        raise ValueError(f"Étape inconnue : {jusqua}. Étapes : {', '.join(ETAPES)}")
    cfg = cfg or charger_config(**options)
    ctx = Contexte(cfg)
    if not silencieux:
        print(f"ERC circularité — {cfg.mode}")
    for e in ETAPES[: ETAPES.index(jusqua) + 1]:
        FONCTIONS[e](ctx)
        if not silencieux:
            n = sum(1 for (et, _, t) in ctx.depot._entrees if et == e and t in ("table", "json", "figure"))
            print(f"  étape {e:<11} {n:>3} artefacts → {ctx.depot.dossier(e).relative_to(cfg.dossier).as_posix()}/")
    if ctx.anomalies and not silencieux:
        print(f"  {len(ctx.anomalies)} anomalie(s) : voir la table « Anomalies » de la synthèse")
    return ctx
