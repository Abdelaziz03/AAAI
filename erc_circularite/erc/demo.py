"""Jeu de démonstration : des sources entièrement FICTIVES, dans les mêmes formats de fichiers que les sources réelles.

Références, descriptions, quantités, coûts et délais sont inventés. Le jeu sert à faire tourner tout le dossier
(pipeline, notebooks, outil) sans aucune donnée d'entreprise, et à tester les lecteurs sur les vrais formats.
Quelques trous sont volontaires (un poids absent, un FRU sans atelier, un FRU sans temps de démontage) pour
montrer comment une donnée manquante est signalée.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from .config import Config

DEBUT, FIN = "2026-06-01", "2026-11-01"                 # 22 semaines complètes, lundi → dimanche
SOURCE_DEMO = "DÉMO : valeur fictive"

# FRU : description, atelier, famille, poids kg, réparations par semaine, rebuts par semaine
FRUS = {
    "FRU-A100-R": ("Amplificateur de gradient (démo)", "MR", "Amplificateur", 79.0, 12, 5.0),
    "FRU-A200-R": ("Alimentation de puissance (démo)", "MR", "Alimentation", 62.0, 6, 1.5),
    "FRU-B300-R": ("Boîtier de commande (démo)", "TSUI", "Commande", 5.5, 15, 2.0),
    "FRU-B400-R": ("Pupitre de table (démo)", "TSUI", "Commande", 6.3, 5, 0.6),
    "FRU-C500-R": ("Antenne de surface (démo)", "Coils", "Antenne", 3.0, 4, 1.0),
    "FRU-W600-R": ("Station de travail (démo)", None, None, 11.0, 3, 0.4),      # atelier volontairement absent
}
# pièce : description, MMICV (0 = absent), poids kg (None = absent), catégorie, benne
PIECES = {
    "P-1001": ("IGBT 400A 1200V", 32.0, 0.35, "Composant de puissance", "DEEE"),
    "P-1002": ("IGBT 400A 600V", 25.0, 0.35, "Composant de puissance", "DEEE"),
    "P-1003": ("AL Electrolytic Capacitor 450V 4700uF 105degC", 0.0, None, "Condensateur", "DEEE"),   # MMICV et poids absents
    "P-1004": ("Gate Driver Board", 320.0, 0.40, "Carte B", "DEEE"),
    "P-1005": ("Control board assembly", 310.0, 0.45, "Carte B", "DEEE"),
    "P-1006": ("Bus resistance 33k ohm 10W", 4.5, 0.05, "Composant standard", "DEEE"),
    "P-1007": ("Protection fuse 100A high speed", 1.8, 0.08, "Composant standard", "DEEE"),
    "P-2001": ("Power supply board", 210.0, 0.60, "Carte B", "DEEE"),
    "P-2002": ("Cooling fan 120mm", 18.0, 0.25, "Composant standard", "DEEE"),
    "P-3001": ("Coque boîtier gris", 120.0, 0.60, "Plastique", "DIB"),
    "P-3002": ("Tête de joystick", 56.0, 0.05, "Plastique", "DIB"),
    "P-3003": ("Soufflet caoutchouc", 1.5, 0.02, "Plastique", "DIB"),
    "P-3004": ("Cable harness boîtier", 140.0, 0.30, "Câbles", "DEEE"),
    "P-3005": ("Keypad controller board", 180.0, 0.20, "Carte C", "DEEE"),
    "P-4001": ("Grille de protection", 40.0, 0.30, "Métal", "Métal"),
    "P-5001": ("Coil preamp board", 95.0, 0.10, "Carte C", "DEEE"),
    "P-5002": ("Coil cable", 60.0, 0.20, "Câbles", "DEEE"),
    "P-6001": ("Mainboard station", 400.0, None, None, None),                                          # non classée
    "P-6002": ("Cooling fan 80mm", 9.0, 0.12, "Composant standard", "DEEE"),
}
# FRU → {pièce: (exemplaires par FRU, probabilité qu'un exemplaire soit défectueux à une réparation, remplacée par jeu complet)}
NOMENCLATURE = {
    "FRU-A100-R": {"P-1001": (2, 0.22, True), "P-1002": (2, 0.18, True), "P-1003": (4, 0.25, False), "P-1004": (1, 0.30, False),
                   "P-1005": (1, 0.10, False), "P-1006": (3, 0.15, False), "P-1007": (2, 0.10, False)},
    "FRU-A200-R": {"P-1002": (2, 0.15, True), "P-2001": (1, 0.40, False), "P-2002": (2, 0.30, False), "P-1007": (2, 0.12, False)},
    "FRU-B300-R": {"P-3001": (1, 0.35, False), "P-3002": (2, 0.30, False), "P-3003": (2, 0.50, False), "P-3004": (1, 0.20, False), "P-3005": (1, 0.15, False)},
    "FRU-B400-R": {"P-3002": (2, 0.25, False), "P-3005": (1, 0.20, False), "P-4001": (1, 0.40, False)},
    "FRU-C500-R": {"P-5001": (2, 0.30, False), "P-5002": (1, 0.35, False)},
    "FRU-W600-R": {"P-6001": (1, 0.30, False), "P-6002": (2, 0.40, False)},
}
PRIX_GRADES = {"Carte B": 8.0, "Carte C": 3.0, "Composant de puissance": 2.5, "Condensateur": 0.6, "Câbles": 1.8,
               "Composant standard": 0.5, "Plastique": 0.05, "Métal": 0.25}
# Vérité du simulateur pour l'audit de démontage : part des pièces réellement réutilisables dans un FRU rebuté
Q_VRAI = {("FRU-A100-R", "P-1001"): 0.55, ("FRU-A100-R", "P-1004"): 0.35, ("FRU-A100-R", "P-1003"): 0.20,
          ("FRU-B300-R", "P-3001"): 0.50, ("FRU-B300-R", "P-3002"): 0.65}
# Temps (extraction, test, tri) en minutes par pièce, pour le classeur de paramètres de la démo
TEMPS = {"P-1001": (6, 4, 1), "P-1002": (6, 4, 1), "P-1003": (3, 2, 0.5), "P-1004": ("8|10|14", "15|20|30", 2), "P-1005": (10, 20, 2),
         "P-1006": (2, 1, 0.5), "P-1007": (2, 1, 0.5), "P-2001": (12, 20, 2), "P-2002": (5, 3, 1),
         "P-3001": (5, 2, 1), "P-3002": (4, 3, 0.5), "P-3003": (2, 1, 0.3), "P-3004": (6, 5, 1), "P-3005": (7, 12, 1)}
OUVERTURE = {"FRU-A100-R": ("30|45|70", 15), "FRU-A200-R": ("25|35|50", 12), "FRU-B300-R": ("10|15|25", 6)}     # FRU-B400-R sans temps : volontaire
DELAIS = {"P-1001": 26, "P-1002": 26, "P-1004": 16, "P-1005": 16, "P-2001": 12, "P-3005": 10}


def _csv(d: pd.DataFrame, chemin, **kw):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(chemin, sep=";", index=False, encoding="utf-8-sig", **kw)


def generer(cfg: Config, forcer: bool = False) -> bool:
    """Écrit les sources fictives sous cfg.projet et cfg.racine si elles n'existent pas. Renvoie True si écrites."""
    temoin = cfg.projet / "DEMO_LISEZ_MOI.txt"
    if temoin.is_file() and not forcer:
        return False
    rng = np.random.default_rng(cfg.graine)
    cfg.projet.mkdir(parents=True, exist_ok=True)
    jours = pd.date_range(DEBUT, FIN)
    ouvres = [j for j in jours if j.weekday() < 5]

    # ---- consommations par réparation (PO)
    ev, po = [], 100000
    for j in ouvres:
        for fru, (_, _, _, _, rep_sem, _) in FRUS.items():
            for _ in range(rng.poisson(rep_sem / 5)):
                po += 1
                for piece, (n, d, jeu) in NOMENCLATURE[fru].items():
                    hs = int(rng.binomial(n, d))
                    q = n if (jeu and hs) else hs                    # « jeu complet » : toutes changées dès qu'une lâche
                    if q:
                        ev.append((j, f"PO{po}", fru, piece, PIECES[piece][0], q, round(q * PIECES[piece][1] * rng.uniform(0.9, 1.1), 2)))
    ev = pd.DataFrame(ev, columns=["Jour", "PO", "FRU ITEM", "Component ITEM", "Component Description", "Qte", "Valeur MICV"])

    # ---- FRU rebutées : flux irrégulier (semaines creuses et semaines chargées)
    lundis = pd.date_range(DEBUT, FIN, freq="W-MON")
    reb, serie = [], 5000
    for lundi in lundis:
        charge = rng.choice([0.3, 0.8, 1.0, 1.2, 1.9])
        for fru, (_, _, _, _, _, taux) in FRUS.items():
            for _ in range(rng.poisson(taux * charge)):
                serie += 1
                fin_ = lundi + pd.Timedelta(days=int(rng.integers(0, 5)))
                recu = fin_ - pd.Timedelta(days=int(rng.integers(10, 60)))
                reb.append({"PO": f"PR{serie}", "FRU ITEM": fru, "Numero de serie": f"SN{serie}", "Statut": "Scrapped",
                            "Date creation PO": recu - pd.Timedelta(days=2), "Date reception": recu,
                            "Date diagnostic": recu + pd.Timedelta(days=int(rng.integers(1, 8))), "Date statut": fin_})
    reb = pd.DataFrame(reb)
    cohorte = pd.DataFrame([(f, st, int(n)) for f in FRUS for st, n in
                            (("Scrapped", reb["FRU ITEM"].eq(f).sum()), ("Shipped", FRUS[f][4] * 20), ("In repair", rng.integers(2, 12)))],
                           columns=["FRU ITEM", "Statut", "Unites"])

    # ---- deux extractions qui se chevauchent : la plus récente doit gagner sur les jours communs
    fenetres = [("20260601", "20260913"), ("20260831", "20261101")]
    for k, (a, b) in enumerate(fenetres):
        f = cfg.projet / f"ERC_R26_extraction_{a}_{b}.xlsx"
        with pd.ExcelWriter(f, engine="openpyxl") as w:
            ev[(ev["Jour"] >= a) & (ev["Jour"] <= b)].to_excel(w, sheet_name="Composants_jour", index=False)
            reb[(reb["Date statut"] >= a) & (reb["Date statut"] <= b)].to_excel(w, sheet_name="FRU_rebutees", index=False)
            cohorte.to_excel(w, sheet_name="FRU_statut_cohorte", index=False)
        os.utime(f, (1_780_000_000 + k * 86400, 1_780_000_000 + k * 86400))

    # ---- référentiels
    pd.DataFrame([{"Item": f, "workshop": v[1], "category": v[2]} for f, v in FRUS.items() if v[1]]).to_excel(cfg.racine / "FRU_info.xlsx", index=False)
    qc = ev.groupby(["FRU ITEM", "Component ITEM", "Component Description"]).agg(q=("Qte", "sum"), v=("Valeur MICV", "sum")).reset_index()
    qc = pd.DataFrame({"FRU ITEM": qc["FRU ITEM"], "FRU Description": qc["FRU ITEM"].map(lambda f: FRUS[f][0]), "Component ITEM": qc["Component ITEM"],
                       "Component Description": qc["Component Description"], "Total Consumption Quantity": qc["q"] * 2, "Total value": (qc["v"] * 2).round(2),
                       "unit weight": qc["Component ITEM"].map(lambda p: PIECES[p][2])})
    fl = pd.DataFrame([{"ITEM": f, "ITEM Description": v[0], "Scrapped": int(reb["FRU ITEM"].eq(f).sum() * 2), "Net weight": v[3]} for f, v in FRUS.items()])
    with pd.ExcelWriter(cfg.racine / "ERC_Valorisation_MICV_v1.xlsx", engine="openpyxl") as w:
        qc.to_excel(w, sheet_name="QueryComponents", index=False)
        fl.to_excel(w, sheet_name="QueryERC_Flow_In_Out", index=False)
    _csv(pd.DataFrame([{"ITEM": p, "Description": v[0], "MMICV USD": v[1]} for p, v in PIECES.items()]), cfg.projet / "Extraction_R26" / "poids_items_vwAllItems.csv")
    d_cl = cfg.projet / "Classification_matieres"
    d_cl.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"Référence": p, "Catégorie proposée": v[3], "Benne": v[4], "Poids unitaire (kg)": v[2], "Source poids": "pesée (démo)" if v[2] else None,
                   "Fabricant": "Fabricant démo", "Nature réelle": v[0], "Niveau de preuve": "démo"} for p, v in PIECES.items() if v[3]]
                 ).to_excel(d_cl / "ERC_Classification_Cartes_resultats.xlsx", sheet_name="Classification", index=False)
    pd.DataFrame({"Catégorie": list(PRIX_GRADES), "Prix recycleur (€/kg)": list(PRIX_GRADES.values())}).to_excel(
        d_cl / "ERC_Referentiel_Grades.xlsx", sheet_name="Grades", index=False)

    # ---- fiabilité : défaillances précoces par origine de pièce, et pièces posées sur la même période
    elf, poses = [], []
    for piece, forme, taux in (("P-1001", 0.7, {"": 0.010, "-R": 0.022}), ("P-1004", 0.8, {"": 0.015, "-R": 0.018, "-H": 0.030}),
                               ("P-1003", 2.4, {"": 0.008}), ("P-3005", 1.0, {"": 0.012, "-R": 0.014})):
        for suffixe, t in taux.items():
            n_pose = int(rng.integers(4000, 9000)) if not suffixe else int(rng.integers(1200, 3000))
            org = {"": "Neuve", "-R": "Réparée", "-H": "Récupérée"}[suffixe]
            poses.append({"Référence": piece, "Origine": org, "Pièces posées": n_pose})
            for _ in range(rng.binomial(n_pose, t)):
                d = 400 * rng.weibull(forme)
                while d > 90:                                         # le fichier ne garde que les défaillances dans la fenêtre
                    d = 400 * rng.weibull(forme)
                date = 44600 + int(rng.integers(0, 700))
                elf.append({"failed_part_no": piece, "replacement_part_no": piece + suffixe, "replacement_part_description": PIECES[piece][0],
                            "elf_days": int(d), "elf_date": date, "failed_part_install_date": date - int(d), "region_description": rng.choice(["EMEA", "AMER", "APAC"])})
    _csv(pd.DataFrame(elf), cfg.projet / "Extraction_R26" / "fiabilite_ELF_references_ERC.csv")
    _csv(pd.DataFrame(poses), cfg.projet / "Extraction_R26" / "poses_2022_2023_par_reference.csv")

    # ---- terrain : pesées du vendredi (6 dernières semaines) et audit de démontage
    evp = ev.assign(Semaine=ev["Jour"] - pd.to_timedelta(ev["Jour"].dt.weekday, unit="D"), Benne=ev["Component ITEM"].map(lambda p: PIECES[p][4]),
                    kg=ev["Qte"] * ev["Component ITEM"].map(lambda p: PIECES[p][2] or 0.45))      # les pièces sans poids pèsent quand même sur la balance
    vrai = evp.dropna(subset=["Benne"]).groupby(["Benne", "Semaine"])["kg"].sum().unstack(0).sort_index()
    pes = []
    for benne in ("DEEE", "DIB"):
        s = vrai[benne].fillna(0)
        mesure = 0.7 * s + 0.3 * s.shift(1).fillna(s.iloc[0])            # 30 % des pièces restent une semaine dans les bacs individuels
        if benne == "DEEE":
            mesure = mesure * 1.18                                        # benne partagée avec d'autres ateliers
        for lundi, m in mesure.tail(6).items():
            pes.append({"Semaine": (lundi + pd.Timedelta(days=4)).strftime("%d/%m/%Y"), "Flux": benne,
                        "Masse mesurée (kg)": f"{m * rng.uniform(0.96, 1.04):.1f}".replace(".", ","), "Incertitude mesure (kg)": "0,5",
                        "Périmètre": "MR, TSUI, Workstation" if benne == "DEEE" else "TSUI", "Commentaire": "pesée du vendredi (démo)",
                        "Cause constatée": ("benne partagée : bacs d'un autre atelier vidés le même jour (démo)" if benne == "DEEE" and len(pes) % 3 == 0 else "")})
    _csv(pd.DataFrame(pes), cfg.projet / "Acquisition" / "pesees_hebdo.csv")
    aud = []
    for k in range(6):
        for (fru, piece), q in Q_VRAI.items():
            n = int(rng.integers(4, 11))
            aud.append({"Date": (pd.Timestamp("2026-09-21") + pd.Timedelta(weeks=k)).strftime("%d/%m/%Y"), "Type de FRU": fru, "Pièce": piece,
                        "Pièces testées": n, "Pièces bonnes": int(rng.binomial(n, q))})
    _csv(pd.DataFrame(aud), cfg.projet / "Acquisition" / "audit_demontage.csv")
    temoin.write_text("Sources FICTIVES générées par erc.demo. Aucune donnée d'entreprise.\n", encoding="utf-8")
    return True


def remplir_parametres(tables: dict) -> dict:
    """Remplit le gabarit de la démo avec des valeurs fictives, en laissant quelques manques volontaires."""
    lg = tables["Ligne"].astype(object).set_index("Paramètre")
    for k, v in {"cout_installation_eur": "20000|30000|45000", "amortissement_ans": 5, "couts_fixes_annuels_eur": 6000, "heures_operateur_an": 900,
                 "taux_horaire_eur": "38|42|48", "cout_traitement_eur_kg": "0,15|0,35", "valeur_reemploi_frac": "0,3|0,5|0,7",
                 "valeur_semaine_eur": 0.5, "taux_change_mmicv": 0.92}.items():
        lg.at[k, "Valeur"], lg.at[k, "Source"] = v, SOURCE_DEMO
    tables["Ligne"] = lg.reset_index()
    fru = tables["FRU"].astype(object)
    for i, r in fru.iterrows():
        if r["FRU"] in OUVERTURE:
            fru.at[i, "ouverture_min"], fru.at[i, "ouverture_tri_min"] = OUVERTURE[r["FRU"]]
            fru.at[i, "facteur_rebut"], fru.at[i, "Source"] = 1.3, SOURCE_DEMO
    tables["FRU"] = fru
    pc = tables["Pieces"].astype(object)
    for i, r in pc.iterrows():
        if r["Pièce"] == "CARCASSE":
            if r["FRU"] in OUVERTURE:
                pc.at[i, "prix_recycleur_eur_kg"], pc.at[i, "tri_min"], pc.at[i, "Source"] = "0,12|0,25", 10, SOURCE_DEMO
            continue
        if r["Pièce"] in TEMPS and r["FRU"] in OUVERTURE:
            pc.at[i, "extraction_min"], pc.at[i, "test_min"], pc.at[i, "tri_min"] = TEMPS[r["Pièce"]]
            pc.at[i, "n_par_fru"] = NOMENCLATURE[r["FRU"]][r["Pièce"]][0]
            pc.at[i, "casse_demontage"], pc.at[i, "rendement_test"], pc.at[i, "Source"] = 0.05, 0.9, SOURCE_DEMO
            if NOMENCLATURE[r["FRU"]][r["Pièce"]][2]:
                pc.at[i, "part_preventive"] = 0.4
    tables["Pieces"] = pc
    sp = tables["Supply"].astype(object)
    for i, r in sp.iterrows():
        if r["Référence"] in DELAIS:
            sp.at[i, "Délai (semaines)"], sp.at[i, "Source"] = DELAIS[r["Référence"]], SOURCE_DEMO
    tables["Supply"] = sp
    tables["Chiffres_a_verifier"] = pd.DataFrame([{"Libellé": "IGBT, toutes références (chiffre annoncé en revue, démo)", "Motif": r"\bigbt\b",
                                                   "Atelier": "MR", "Valeur par mois": 150}])
    return tables
