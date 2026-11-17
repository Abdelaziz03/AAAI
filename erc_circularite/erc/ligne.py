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

Ce que devient une entrée inconnue (None ou NaN) : jamais un zéro caché
------------------------------------------------------------------------
- Entrée d'une option (temps, nombre par FRU, probabilité, valeur, poids, prix, ouverture) : l'option n'est pas
  calculable et n'est jamais choisie ; la colonne « Manque ... » dit ce qu'il faut obtenir.
- FRU rebutées par an, taux horaire, coût de traitement du recycleur actuel, ou aucune option calculable :
  le type de FRU est « incomplet », exclu du calcul et compté dans « Types de FRU incomplets ». Les autres
  types sont optimisés normalement.
- Investissement, durée d'amortissement, coûts fixes annuels, poids d'un FRU : l'indicateur qui en dépend
  vaut NaN (coûts fixes, résultat, seuil, retour sur investissement, masse, coût actuel).
- Heures opérateur inconnues = pas de limite d'heures : le résultat est alors un potentiel, pas un plan tenu
  par l'atelier (« Capacité (h/an) » vaut inf et « Taux d'occupation » NaN).
- Entrées facultatives, comptées seulement si elles sont saisies : transport d'une pièce réemployée, délai
  d'approvisionnement évité, poids d'une pièce réemployée (traitement évité), revente au kilo des exemplaires
  refusés au test. La colonne « Non compté faute de donnée » de `valeurs_options` les signale pièce par pièce.
- « ouverture_tri_min » et « taux_horaire_eur » d'un FRU ne retombent sur leur valeur par défaut (ouverture
  soignée, taux de la ligne) que si la clé est absente du dictionnaire ; présente et inconnue, elle reste inconnue.
"""
from __future__ import annotations


import numpy as np
import pandas as pd

RNG = np.random.default_rng(2026)


def _inconnu(v):
    """Inconnu : None, NaN (nombre Python ou numpy), pd.NA, pd.NaT. Une plage ou un texte n'est pas « inconnu »."""
    if v is None or v is pd.NA or v is pd.NaT:
        return True
    return isinstance(v, (float, np.floating)) and bool(np.isnan(v))


def _facultatif(v):
    """Entrée facultative : comptée si elle est saisie, sinon absente du calcul (et signalée par l'appelant)."""
    return 0.0 if _inconnu(v) else v


# ---------------------------------------------------------------------------
# 1. Probabilité de défaut tirée de la consommation
# ---------------------------------------------------------------------------
def p_defaut_depuis_conso(conso_piece, fru_reparees, n_par_fru=1, part_preventive=0.0):
    """Probabilité qu'un exemplaire de la pièce soit défectueux dans une FRU de ce type, entre 0 et 1.

    conso_piece     : pièces consommées sur la période (réparations de ce type de FRU)
    fru_reparees    : FRU de ce type réparées sur la même période
    n_par_fru       : exemplaires de la pièce dans une FRU
    part_preventive : part des remplacements faits par précaution sur une pièce saine, entre 0 et 1
                      (ex. les deux IGBT changés quand un seul a lâché : jusqu'à 0,5)
    Une entrée inconnue, ou un dénominateur nul ou négatif, donne NaN.
    """
    if any(_inconnu(v) for v in (conso_piece, fru_reparees, n_par_fru, part_preventive)):
        return np.nan
    if not fru_reparees > 0 or not n_par_fru > 0:
        return np.nan
    part = float(np.clip(part_preventive, 0, 1))
    return float(np.clip(conso_piece * (1 - part) / (fru_reparees * n_par_fru), 0, 1))


def p_reutilisable(p_defaut, facteur_rebut=1.0, casse_demontage=0.0, rendement_test=1.0):
    """P(un exemplaire extrait d'une FRU REBUTÉE est réutilisable), entre 0 et 1.

    = (1 − p_défaut × facteur_rebut) × (1 − casse au démontage) × rendement du test, chaque facteur borné à [0, 1].
    Une entrée inconnue donne NaN : la valeur neutre d'un correctif (1, 0, 1) se passe explicitement.
    """
    if any(_inconnu(v) for v in (p_defaut, facteur_rebut, casse_demontage, rendement_test)) or not np.isfinite(p_defaut):
        return np.nan
    sain = np.clip(1 - p_defaut * facteur_rebut, 0, 1)
    return float(sain * (1 - np.clip(casse_demontage, 0, 1)) * np.clip(rendement_test, 0, 1))


# ---------------------------------------------------------------------------
# 2. Tirage des plages
# ---------------------------------------------------------------------------
# Une plage est un couple (bas, haut) tiré uniformément ou un triplet (bas, mode, haut) tiré selon une loi
# triangulaire. Tuple ou liste : le modèle relu depuis un fichier JSON contient des listes.
def _bornes(x):
    """(bas, haut) dans l'ordre, ou None si la plage est mal formée ou a une borne inconnue."""
    if len(x) not in (2, 3) or _inconnu(x[0]) or _inconnu(x[-1]):
        return None
    return (float(min(x[0], x[-1])), float(max(x[0], x[-1])))


def _tirer(x, rng):
    """Un tirage de x : une plage est tirée, un dictionnaire est parcouru, le reste est rendu tel quel.

    Plage dégénérée (bas = haut) : cette valeur. Bornes inversées : remises dans l'ordre. Mode hors des bornes :
    ramené à la borne la plus proche. Borne inconnue : même valeur que `_milieu` (pas de dispersion tirée).
    """
    if isinstance(x, (tuple, list)):
        b = _bornes(x)
        if b is None or (len(x) == 3 and _inconnu(x[1])):
            return _milieu(x)
        if len(x) == 2:
            return float(rng.uniform(b[0], b[1]))
        if not b[0] < b[1]:
            return b[0]
        return float(rng.triangular(b[0], min(max(float(x[1]), b[0]), b[1]), b[1]))
    if isinstance(x, dict):
        return {k: _tirer(v, rng) for k, v in x.items()}
    return x


def _milieu(x):
    """Centre de x : moyenne des bornes d'un couple, mode d'un triplet (ramené entre les bornes). Inconnu → None."""
    if isinstance(x, (tuple, list)):
        b = _bornes(x)
        if len(x) == 2:
            return None if b is None else float(np.mean(b))
        if len(x) == 3 and not _inconnu(x[1]):
            return float(x[1]) if b is None else min(max(float(x[1]), b[0]), b[1])
        return None
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
# par les options 1 et 2 évite ce coût : il est ajouté à leur valeur (« traitement évité »). Un exemplaire refusé au
# test qui retourne à la benne n'est pas sorti de la benne : seule la part réutilisable (p_réut) est comptée.
# Coût de traitement inconnu : aucune valeur n'est calculée (type de FRU « incomplet »).
# Ouverture de la FRU, payée UNE fois : soignée (ouverture_min) dès qu'une pièce part en réemploi, sinon
# sommaire (ouverture_tri_min, à défaut ouverture_min) dès qu'une pièce part au recyclage. Option 3 partout = pas d'ouverture.
# Délai d'approvisionnement : seul critère supply retenu. Chaque pièce réemployée évite delai_semaines d'attente,
# valorisées à valeur_semaine_eur (= coût d'une semaine d'immobilisation × probabilité de rupture, à fixer).
OPTIONS = ("réemploi", "recyclage", "jeté")
CHAMPS_REEMPLOI = ["n_par_fru", "extraction_min", "test_min", "p_reutilisable", "valeur_eur"]
CHAMPS_RECYCLAGE = ["n_par_fru", "poids_kg", "prix_recycleur_eur_kg", "tri_min"]
# Limite de calcul, pas une donnée : 3^8 = 6 561 combinaisons par type de FRU. Au-delà de 8 pièces, les pièces dont la
# meilleure option seule vaut le moins (les inconnues d'abord) restent dans le FRU ; le plan les nomme dans
# « Pièces non examinées ».
MAX_PIECES_ENUM = 8
COLONNES_DETAIL = ["Type de FRU", "Décision", "1 Réemploi", "2 Recyclage", "FRU traitées / an", "FRU rebutées / an", "Heures par FRU",
                   "Marge par FRU (€)", "Marge par heure (€)", "Heures / an", "Marge variable / an (€)", "Kg détournés / an",
                   "Entrées manquantes", "Pièces non examinées"]
COLONNES_PERIODE = ["Semaine", "FRU arrivées", "FRU traitées", "Heures utilisées", "Capacité (h)", "Marge variable (€)", "Coût fixe (€)",
                    "Résultat (€)", "Valeur d'une heure en plus (€)", "Résultat cumulé (€)"]


def _pieces(fru: dict) -> dict:
    return fru.get("pieces") or {}


def options_disponibles(fru: dict) -> dict:
    """Pour chaque pièce : options calculables et entrées manquantes des autres."""
    out = {}
    ouv_tri = fru.get("ouverture_tri_min", fru.get("ouverture_min"))
    for p, d in _pieces(fru).items():
        d = d or {}
        m_re = [c for c in CHAMPS_REEMPLOI if _inconnu(d.get(c))] + (["ouverture_min"] if _inconnu(fru.get("ouverture_min")) else [])
        m_rc = [c for c in CHAMPS_RECYCLAGE if _inconnu(d.get(c))] + (["ouverture_tri_min"] if _inconnu(ouv_tri) else [])
        out[p] = {"réemploi": m_re, "recyclage": m_rc}
    return out


def manques(fru: dict, taux_defaut) -> list[str]:
    """Entrées qui empêchent de calculer un type de FRU (liste vide = calculable).

    Le coût de traitement du recycleur actuel est lu dans fru["_c_trait"], que `optimiser_ligne` renseigne :
    présent et inconnu, il bloque le type de FRU ; absent, il n'est pas vérifié.
    """
    m = [c for c in ("rebut_an",) if _inconnu(fru.get(c))]
    if not m and fru["rebut_an"] < 0:
        m.append("rebut_an négatif")
    if _inconnu(fru.get("taux_horaire_eur", taux_defaut)):
        m.append("taux_horaire_eur")
    if "_c_trait" in fru and _inconnu(fru["_c_trait"]):
        m.append("cout_traitement_eur_kg")
    dispo = options_disponibles(fru)
    if not any(not v for o in dispo.values() for v in o.values()):
        m.append("aucune option calculable : " + "; ".join(f"{p} réemploi[{', '.join(o['réemploi'])}] recyclage[{', '.join(o['recyclage'])}]"
                                                      for p, o in dispo.items()))
    return m


def valeurs_options(fru: dict, taux_defaut) -> pd.DataFrame:
    """Une ligne par pièce : valeur nette par FRU de chaque option, HORS ouverture (partagée, donnée à part).

    fru["_c_trait"] = coût de traitement du recycleur actuel (€/kg). Clé absente : le traitement évité n'est pas compté.
    Taux horaire ou coût de traitement inconnu : les valeurs sont NaN, les heures et les kg restent donnés.
    « Non compté faute de donnée » liste ce que la valeur du réemploi laisse de côté parce que l'entrée facultative
    n'est pas saisie.
    """
    taux = fru.get("taux_horaire_eur", taux_defaut)
    taux_connu = not _inconnu(taux)
    c_fourni = "_c_trait" in fru
    c_connu = not (c_fourni and _inconnu(fru["_c_trait"]))
    c_trait = (fru.get("_c_trait") or 0.0) if c_connu else np.nan
    chiffrable = taux_connu and c_connu
    dispo, lignes = options_disponibles(fru), []
    for p, d in _pieces(fru).items():
        d = d or {}
        n = d.get("n_par_fru")
        poids_connu = not _inconnu(d.get("poids_kg"))
        kg = d.get("poids_kg") if poids_connu else 0.0     # poids inconnu : aucun traitement évité compté
        kgv = None if dispo[p]["recyclage"] else d["poids_kg"] * d["prix_recycleur_eur_kg"]
        k_re = k_rc = 0.0
        non_compte = []
        if dispo[p]["réemploi"]:
            v_re, h_re = np.nan, np.nan
        else:
            k_re = n * kg * (d["p_reutilisable"] + (1 - d["p_reutilisable"]) * (kgv is not None))
            bonus = _facultatif(d.get("delai_semaines")) * _facultatif(d.get("valeur_semaine_eur"))
            echec = kgv if kgv is not None else 0.0
            h_re = n * (d["extraction_min"] + d["test_min"]) / 60
            v_re = (n * (d["p_reutilisable"] * (d["valeur_eur"] + bonus) + (1 - d["p_reutilisable"]) * echec
                         - _facultatif(d.get("transport_eur"))) - h_re * taux + k_re * c_trait) if chiffrable else np.nan
            if _inconnu(d.get("transport_eur")):
                non_compte.append("transport")
            if _inconnu(d.get("delai_semaines")) or _inconnu(d.get("valeur_semaine_eur")):
                non_compte.append("délai évité")
            if kgv is None:
                non_compte.append("revente au kilo des exemplaires refusés au test")
            if not poids_connu or not c_fourni:
                non_compte.append("traitement évité")
        if dispo[p]["recyclage"]:
            v_rc, h_rc = np.nan, np.nan
        else:
            h_rc = n * d["tri_min"] / 60
            k_rc = n * kg
            v_rc = n * kgv - h_rc * taux + k_rc * c_trait if chiffrable else np.nan
            if not c_fourni and "traitement évité" not in non_compte:
                non_compte.append("traitement évité")
        lignes.append({"Pièce": p, "1 Réemploi (€/FRU)": v_re, "2 Recyclage (€/FRU)": v_rc, "3 Jeté (€/FRU)": 0.0,
                       "Heures réemploi": h_re, "Heures recyclage": h_rc, "Kg détournés réemploi": k_re, "Kg détournés recyclage": k_rc,
                       "Manque réemploi": ", ".join(dispo[p]["réemploi"]), "Manque recyclage": ", ".join(dispo[p]["recyclage"]),
                       "Non compté faute de donnée": ", ".join(non_compte)})
    t = pd.DataFrame(lignes)
    if len(t):
        t["Meilleure option seule"] = t[["1 Réemploi (€/FRU)", "2 Recyclage (€/FRU)", "3 Jeté (€/FRU)"]].idxmax(axis=1).str[2:].str.replace(" (€/FRU)", "", regex=False)
    ouv, ouv_tri = fru.get("ouverture_min"), fru.get("ouverture_tri_min", fru.get("ouverture_min"))
    t.attrs["Ouverture soignée (€/FRU)"] = ouv / 60 * taux if taux_connu and not _inconnu(ouv) else np.nan
    t.attrs["Ouverture sommaire (€/FRU)"] = ouv_tri / 60 * taux if taux_connu and not _inconnu(ouv_tri) else np.nan
    return t


_CODES: dict[int, np.ndarray] = {}


def _codes(n: int) -> np.ndarray:
    """Toutes les affectations de n pièces : matrice (3^n, n), 0 = réemploi, 1 = recyclage, 2 = jeté."""
    if n not in _CODES:
        _CODES[n] = np.indices((3,) * n).reshape(n, -1).T if n else np.zeros((1, 0), dtype=int)
    return _CODES[n]


class Options:
    """Toutes les affectations pièce → option d'un type de FRU : heures, marge et kg détournés par FRU (tableaux numpy).

    Au plus MAX_PIECES_ENUM pièces sont examinées : celles dont la meilleure option seule vaut le plus (ex æquo dans
    l'ordre de saisie, pièces sans option calculable en dernier). `noms_ignores` nomme les autres, laissées dans le FRU.
    """

    def __init__(self, fru: dict, taux_defaut):
        taux = fru.get("taux_horaire_eur", taux_defaut)
        t = valeurs_options(fru, taux_defaut)
        toutes = list(t["Pièce"]) if len(t) else []
        if len(t):
            t = t.assign(meilleur=t[["1 Réemploi (€/FRU)", "2 Recyclage (€/FRU)"]].max(axis=1)).sort_values(
                "meilleur", ascending=False, kind="mergesort").head(MAX_PIECES_ENUM)
        self.noms = list(t["Pièce"]) if len(t) else []
        self.noms_ignores = [p for p in toutes if p not in set(self.noms)]      # pièces au-delà de MAX_PIECES_ENUM : laissées dans le FRU
        self.ignorees = len(self.noms_ignores)
        C = _codes(len(self.noms))
        col = lambda c: t[c].to_numpy(float) if len(t) else np.zeros(0)
        v = np.stack([col("1 Réemploi (€/FRU)"), col("2 Recyclage (€/FRU)"), np.zeros(len(self.noms))])      # (3, n)
        h = np.stack([col("Heures réemploi"), col("Heures recyclage"), np.zeros(len(self.noms))])
        k = np.stack([col("Kg détournés réemploi"), col("Kg détournés recyclage"), np.zeros(len(self.noms))])
        j = np.arange(len(self.noms))
        valide = ~np.isnan(v[C, j]).any(axis=1)                                 # une option non calculable n'est jamais choisie
        ouv = _facultatif(fru.get("ouverture_min")) / 60                        # inconnue : aucun plan valide ne l'utilise
        ouv_tri = _facultatif(fru.get("ouverture_tri_min", fru.get("ouverture_min"))) / 60
        o = np.where((C == 0).any(axis=1), ouv, np.where((C == 1).any(axis=1), ouv_tri, 0.0))
        cout_ouv = np.where(o != 0, o * (np.nan if _inconnu(taux) else taux), 0.0)
        self.C = C
        self.H = np.where(valide, np.nan_to_num(h[C, j]).sum(axis=1) + o, 0.0)
        self.M = np.where(valide, np.nan_to_num(v[C, j]).sum(axis=1) - cout_ouv, -np.inf)
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
    """Choix des FRU à démonter et des pièces à extraire, sous la capacité en heures. Valeurs ponctuelles
    (une plage est lue en son centre).

    Relâché continu résolu par multiplicateur de Lagrange mu sur les heures : chaque type de FRU prend le plan qui
    maximise marge − mu × heures ; mu est trouvé par dichotomie. Au point de rupture, les heures restantes sont
    données aux types de FRU dont le plan change, dans l'ordre du gain par heure supplémentaire. Le résultat est
    l'optimum du programme linéaire du document (vérifié contre un solveur exact dans tests/test_ligne.py).
    Heures opérateur inconnues = pas de limite ; négatives = aucune heure.
    """
    ligne, frus = _milieu(ligne or {}), _milieu(frus or {})
    taux = ligne.get("taux_horaire_eur")
    avec = {f: dict(d or {}, _c_trait=ligne.get("cout_traitement_eur_kg")) for f, d in frus.items()}
    incomplets = {f: manques(d, taux) for f, d in avec.items()}
    ok = {f: d for f, d in avec.items() if not incomplets[f]}
    opts = {f: Options(d, taux) for f, d in ok.items()}
    cap = ligne.get("heures_operateur_an")
    cap = np.inf if _inconnu(cap) else max(float(cap), 0.0)

    def choix(mu):
        return {f: o.meilleur(mu) for f, o in opts.items()}

    def heures(c):
        return sum(ok[f]["rebut_an"] * x[1] for f, x in c.items())

    mu_lo, mu_hi = 0.0, 0.0
    c_hi = choix(0.0)
    c_lo = c_hi
    if heures(c_hi) > cap:
        mu_hi = 1.0
        while heures(choix(mu_hi)) > cap and mu_hi < 1e300:     # borne : jamais de boucle sans fin sur des entrées aberrantes
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
        debut = len(lignes)
        if x > 0:                                 # x FRU au plan plus gourmand, le reste au plan sobre
            S2, h2, m2, k2 = c_lo[f]
            lignes.append(_ligne_res(f, S2, x, h2, m2, ok[f], k2))
            if n - x > 1e-9:
                lignes.append(_ligne_res(f, S, n - x if S else 0.0, h, m, ok[f], k))
        else:
            lignes.append(_ligne_res(f, S, n if S else 0.0, h, m, ok[f], k))
        for l in lignes[debut:]:
            l["Pièces non examinées"] = ", ".join(str(p) for p in opts[f].noms_ignores)
    for f, m in incomplets.items():
        if m:
            lignes.append({"Type de FRU": f, "Décision": "incomplet", "Entrées manquantes": ", ".join(m)})
    detail = pd.DataFrame(lignes, columns=COLONNES_DETAIL)
    return _bilan(ligne, detail, mu_hi, cap, frus)


def _ligne_res(f, S, n, h, m, d, k=0.0):
    return {"Type de FRU": f, "Décision": "traiter" if S and n > 0 else "jeter telle quelle",
            "1 Réemploi": ", ".join(p for p, o in S if o == "réemploi"),
            "2 Recyclage": ", ".join(p for p, o in S if o == "recyclage"), "FRU traitées / an": n, "FRU rebutées / an": d["rebut_an"],
            "Heures par FRU": h, "Marge par FRU (€)": m, "Marge par heure (€)": m / h if h else np.nan,
            "Heures / an": n * h, "Marge variable / an (€)": n * m, "Kg détournés / an": n * k, "Entrées manquantes": ""}


def _couts_fixes(ligne) -> float:
    """Coût fixe d'une année = installation / durée d'amortissement + coûts fixes annuels. Entrée inconnue → NaN.

    Une durée d'amortissement inférieure à un an compte pour un an : l'installation est alors payée en entier la
    première année. Sans investissement, la durée n'intervient pas.
    """
    inv, fix, duree = ligne.get("cout_installation_eur"), ligne.get("couts_fixes_annuels_eur"), ligne.get("amortissement_ans")
    if _inconnu(inv) or _inconnu(fix):
        return np.nan
    if inv == 0:
        return float(fix)
    if _inconnu(duree):
        return np.nan
    return inv / max(duree, 1) + fix


def _bilan(ligne, detail, mu, cap, frus=None):
    """Résultat de la ligne. Coût fixe ou marge inconnus → NaN (jamais 0)."""
    frus = frus or {}
    c = ligne.get("cout_traitement_eur_kg")
    masses = [d["rebut_an"] * d["poids_fru_kg"] for d in frus.values()
              if d and not _inconnu(d.get("rebut_an")) and not _inconnu(d.get("poids_fru_kg")) and d["rebut_an"] >= 0]
    masse = float(sum(masses)) if masses and len(masses) == len(frus) else np.nan
    cout_actuel = masse * c if not _inconnu(c) else np.nan
    inv, fix = ligne.get("cout_installation_eur"), ligne.get("couts_fixes_annuels_eur")
    fixes = _couts_fixes(ligne)
    calc = detail[detail["Décision"].ne("incomplet")] if len(detail) else detail
    marge = float(calc["Marge variable / an (€)"].sum()) if len(calc) else np.nan
    h = float(calc["Heures / an"].sum()) if len(calc) else np.nan
    n = float(calc["FRU traitées / an"].sum()) if len(calc) else np.nan
    moy = marge / n if n else np.nan
    excedent = marge - fix if not _inconnu(fix) else np.nan
    return {"detail": detail, "resume": {
        "Marge variable / an (€)": marge, "Coûts fixes annualisés (€)": fixes, "Résultat / an (€)": marge - fixes,
        "Heures utilisées / an": h, "Capacité (h/an)": cap, "Taux d'occupation": h / cap if np.isfinite(cap) and cap else np.nan,
        "FRU traitées / an": n, "Marge moyenne par FRU (€)": moy,
        "Seuil de rentabilité (FRU / an)": fixes / moy if moy and moy > 0 else np.nan,
        "Retour sur investissement (ans)": inv / excedent if not _inconnu(inv) and excedent > 0 else np.nan,
        "Valeur d'une heure opérateur en plus (€ net)": mu if len(calc) else np.nan,
        "Types de FRU incomplets": int(detail["Décision"].eq("incomplet").sum()) if len(detail) else 0,
        "Masse des FRU rebutées (kg/an)": masse, "Masse détournée de la benne (kg/an)": float(calc["Kg détournés / an"].sum()) if len(calc) else np.nan,
        "Coût actuel de traitement (€/an)": cout_actuel}}


def comparer_scenarios(ligne: dict, frus: dict) -> pd.DataFrame:
    """Situation actuelle (tout chez le recycleur actuel) contre ligne de démontage + tri. Flux annuels, € ; coût = négatif.

    L'écart total (avec la ligne − actuel) est le « Résultat / an (€) » du résumé : le traitement évité, compris dans
    la marge du résumé, apparaît ici sur la ligne du recycleur actuel. Les écarts sont calculés directement : ils
    restent connus quand le coût actuel ne l'est pas (poids d'un FRU manquant).
    """
    r = point_milieu(ligne, frus)["resume"]
    c = _milieu((ligne or {}).get("cout_traitement_eur_kg"))
    c = np.nan if _inconnu(c) else c
    evite = r["Masse détournée de la benne (kg/an)"] * c
    actuel = -r["Coût actuel de traitement (€/an)"]
    marge_hors_evite = r["Marge variable / an (€)"] - evite
    lignes = [
        ("Traitement des FRU par le recycleur actuel", actuel, actuel + evite, evite),
        ("Marge de la ligne : réemploi + vente au kg − main-d'œuvre", 0.0, marge_hors_evite, marge_hors_evite),
        ("Coûts fixes de la ligne (installation amortie + annuels)", 0.0, -r["Coûts fixes annualisés (€)"], -r["Coûts fixes annualisés (€)"]),
    ]
    t = pd.DataFrame(lignes, columns=["Poste (€/an)", "Actuel", "Avec la ligne", "Écart"])
    tot = pd.DataFrame([("TOTAL", t["Actuel"].sum(skipna=False), t["Avec la ligne"].sum(skipna=False), t["Écart"].sum(skipna=False))], columns=t.columns)
    t = pd.concat([t, tot], ignore_index=True)
    t.attrs.update({"Masse rebutée (kg/an)": r["Masse des FRU rebutées (kg/an)"], "Masse détournée (kg/an)": r["Masse détournée de la benne (kg/an)"],
                    "Part détournée": r["Masse détournée de la benne (kg/an)"] / r["Masse des FRU rebutées (kg/an)"] if r["Masse des FRU rebutées (kg/an)"] else np.nan})
    return t


def monte_carlo_ligne(ligne: dict, frus: dict, n=500, rng=RNG) -> dict:
    """Tire toutes les plages, ré-optimise la ligne à chaque tirage.

    rng : générateur numpy (le même générateur de même graine redonne les mêmes tirages) ou graine entière.
    « P(ligne rentable) » = part des tirages au résultat connu et positif ; NaN si aucun résultat n'est calculable.
    """
    if rng is None:
        rng = RNG
    elif not hasattr(rng, "uniform"):
        rng = np.random.default_rng(rng)
    n = max(int(n), 0)
    res, choix = [], {}
    for _ in range(n):
        r = optimiser_ligne(_tirer(ligne, rng), _tirer(frus, rng))
        res.append(r["resume"])
        d = r["detail"]
        for f in (d.loc[d["Décision"].eq("traiter"), "Type de FRU"].unique() if len(d) else []):
            choix[f] = choix.get(f, 0) + 1
    R = pd.DataFrame(res)
    x = R["Résultat / an (€)"].dropna() if len(R) else pd.Series(dtype=float)
    out = {"tirages": R, "P(ligne rentable)": float((x > 0).mean()) if len(x) else np.nan,
           "Résultat P5 / médiane / P95 (€)": tuple(np.quantile(x, [0.05, 0.5, 0.95]).round(0)) if len(x) else (np.nan,) * 3,
           "Fréquence de traitement par type de FRU": {f: c / n for f, c in choix.items()}}
    return out


def point_milieu(ligne, frus):
    """Version déterministe au centre des plages, pour lire le détail."""
    return optimiser_ligne(_milieu(ligne), _milieu(frus))


def _semaine_incomplete(v) -> bool:
    """Vrai seulement si la semaine est explicitement marquée incomplète (False, 0, « non », « faux »)."""
    return not _inconnu(v) and str(v).strip().lower() in ("false", "0", "0.0", "non", "faux")


def resultat_par_periode(ligne: dict, frus: dict, flux: pd.DataFrame, periodes_par_an=52) -> pd.DataFrame:
    """Le modèle rejoué période par période sur le flux RÉEL des FRU rebutées (colonnes Semaine, FRU, FRU rebutées).

    Chaque période : capacité = heures annuelles / périodes ; coût fixe = (installation amortie + fixes annuels) / périodes,
    payé même si peu de FRU arrivent ; pas de stock d'une période à l'autre (hypothèse 10 du modèle).
    Une période présente dans le flux sans FRU du modèle compte pour zéro FRU. Si le flux a une colonne
    « Semaine complète », les semaines marquées incomplètes sont écartées : une semaine extraite à moitié n'est pas
    une semaine creuse. Les FRU du flux absents du modèle sont ignorés.
    Les attributs du tableau comparent avec le modèle annuel au flux moyen des mêmes périodes : l'écart est le
    COÛT DE LA VARIABILITÉ du flux (heures perdues les semaines creuses, FRU non traitées les semaines chargées).
    Il est positif ou nul, et nul quand le flux est constant ou les heures sans limite.
    """
    if _inconnu(periodes_par_an) or not periodes_par_an > 0:
        raise ValueError("periodes_par_an doit être un nombre positif : 52 pour des semaines, 12 pour des mois")
    lg, fr = _milieu(ligne or {}), _milieu(frus or {})
    H = lg.get("heures_operateur_an")
    cap_p = None if _inconnu(H) else max(float(H), 0.0) / periodes_par_an      # inconnue = pas de limite ; 0 heure = rien n'est traité
    fixe_p = _couts_fixes(lg) / periodes_par_an
    if flux is None or not len(flux):
        return pd.DataFrame(columns=COLONNES_PERIODE)
    if "Semaine complète" in flux.columns:
        flux = flux[~flux["Semaine complète"].map(_semaine_incomplete).astype(bool)]
    total = {}
    for sem, f, v in zip(flux["Semaine"], flux["FRU"], pd.to_numeric(flux["FRU rebutées"], errors="coerce")):
        if f in fr and not np.isnan(v):
            total[(sem, f)] = total.get((sem, f), 0.0) + float(v)
    semaines = sorted(flux["Semaine"].dropna().unique())
    lignes, cumul = [], 0.0
    for sem in semaines:
        fr_t = {f: dict(d or {}, rebut_an=total.get((sem, f), 0.0)) for f, d in fr.items()}
        r = optimiser_ligne(dict(lg, heures_operateur_an=cap_p), fr_t)["resume"]
        resultat = r["Marge variable / an (€)"] - fixe_p
        cumul += resultat
        lignes.append({"Semaine": sem, "FRU arrivées": float(sum(d["rebut_an"] for d in fr_t.values())), "FRU traitées": r["FRU traitées / an"],
                       "Heures utilisées": r["Heures utilisées / an"], "Capacité (h)": np.nan if cap_p is None else cap_p,
                       "Marge variable (€)": r["Marge variable / an (€)"], "Coût fixe (€)": fixe_p, "Résultat (€)": resultat,
                       "Valeur d'une heure en plus (€)": r["Valeur d'une heure opérateur en plus (€ net)"], "Résultat cumulé (€)": cumul})
    t = pd.DataFrame(lignes, columns=COLONNES_PERIODE)
    if len(t):
        moyen = {f: dict(d or {}, rebut_an=sum(total.get((sem, f), 0.0) for sem in semaines) / len(semaines) * periodes_par_an) for f, d in fr.items()}
        annuel = optimiser_ligne(lg, moyen)["resume"]["Résultat / an (€)"]
        par_periode = t["Résultat (€)"].mean() * periodes_par_an
        t.attrs.update({"Périodes": len(t), "Résultat annualisé, période par période (€)": par_periode,
                        "Résultat du modèle annuel au flux moyen (€)": annuel, "Coût de la variabilité du flux (€/an)": annuel - par_periode,
                        "Périodes en perte": int((t["Résultat (€)"] < 0).sum())})
    return t
