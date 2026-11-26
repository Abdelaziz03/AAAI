"""Composition des pièces d'une nomenclature (BOM) : de la description et du code article à la classe matière.

Entrée : une liste Excel (code article, description, et si possible fabricant et référence du fabricant).
Sortie : pour chaque pièce, la classe matière la plus probable, sa probabilité, les sources, un statut, et ce qu'il
reste à faire. Tout est écrit dans le cortex (erc/cortex.py), qui garde les preuves et apprend la fiabilité des sources.

La chaîne va du moins cher au plus cher et s'arrête dès que possible :

  0  le cortex connaît déjà la pièce (validée par une personne)                      gratuit, aucun appel
  1  une règle sur la description                                                      gratuit
  2  une pièce validée de description proche (analogie)                                gratuit
  3  le classement antérieur de la pièce, s'il existe                                  gratuit
  ── la suite coûte : elle n'est lancée que si l'enjeu de la pièce dépasse le coût de l'action ──
  4  collecte de documents publics (fiche du fabricant, déclaration matière)           un appel au collecteur
  5  lecture du document par un modèle de langage, sauf déclaration explicite          un appel au modèle
  6  contrôle de cette lecture par le modèle (Qwen ou autre), seulement en cas de doute un appel au modèle
  7  revue par une personne, par ordre d'enjeu

L'ENJEU d'une pièce borne ce que la connaissance de sa composition peut rapporter par an (erc/information.py) :
masse annuelle concernée × écart moyen entre les prix possibles. Une pièce légère, rare, ou dont toutes les classes
plausibles ont le même prix ne déclenche aucun appel payant : c'est ce qui réduit les appels au modèle au minimum.

Confidentialité. Aucun code article interne ni aucune description ne sort : une requête ne contient que le fabricant,
sa référence et un type générique de pièce. Une pièce de conception interne n'est jamais recherchée à l'extérieur.

Le collecteur et le modèle sont des pièces rapportées : toute fonction ou tout objet qui respecte l'interface convient
(votre méthode de collecte existante, un serveur Qwen local). Sans eux, la chaîne s'arrête à l'étape 3 et dit ce qui manque.

Vocabulaire : « collecte » désigne la recherche de documents sur le web ; « scrapé » reste réservé aux pièces mises au scrap.
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import cortex as mod_cortex
from .risques import type_piece
from .sources import _cle, ref

DOMAINE, ATTRIBUT = "composition", "classe matière"
mod_cortex.A_PRIORI_SOURCES.setdefault("classement antérieur", 0.70)       # hypothèse de travail, comme les autres a priori

COLONNES_BOM = {
    "PN": ("pn", "partnumber", "item", "componentitem", "reference", "ref", "codearticle", "code", "article"),
    "Description": ("description", "componentdescription", "designation", "libelle"),
    "FRU": ("fru", "fruitem", "parent", "ensemble"),
    "Quantité": ("quantite", "qte", "qty", "quantity", "nparfru"),
    "Fabricant": ("fabricant", "manufacturer", "mfr", "marque"),
    "Référence fabricant": ("referencefabricant", "mpn", "manufacturerpartnumber", "mfrpn", "reffabricant"),
    "Interne": ("interne", "conceptioninterne", "inhouse", "makebuy", "fabriqueeninterne"),
    "Poids (kg)": ("poidskg", "poids", "weight", "unitweight", "poidsunitairekg"),
}
COLS_RESULTAT = ["PN", "Description", "Classe retenue", "Probabilité", "Statut", "Sources", "Preuves", "Enjeu (€/an, borne)",
                 "Appels au modèle", "Coût des acquisitions (€)", "Prochaine action"]


@dataclass
class Reglages:
    """Seuils et coûts de la chaîne. Les coûts sont des HYPOTHÈSES DE TRAVAIL à régler : ils servent seulement à
    comparer une action à l'enjeu de la pièce."""
    seuil_acceptation: float = 0.90      # probabilité à partir de laquelle une classe est acceptée sans revue
    seuil_doute: float = 0.60            # en dessous, un contrôle par le modèle ne suffirait pas : revue humaine
    seuil_analogie: float = 0.50         # part minimale de mots communs avec une pièce validée
    cout_collecte: float = 0.02          # € par recherche de documents
    cout_extraction: float = 0.05        # € par lecture de document par le modèle
    cout_validation: float = 0.03        # € par contrôle par le modèle
    cout_revue: float = 5.0              # € par revue humaine d'une pièce (quelques minutes)
    max_documents: int = 3


# --------------------------------------------------------------------------- lecture de la nomenclature
def lire_bom(chemin) -> pd.DataFrame:
    """Nomenclature en table normalisée, une ligne par code article. Les colonnes sont reconnues sans casse ni accent.
    Seuls « PN » et « Description » sont nécessaires ; une colonne absente reste vide."""
    chemin = Path(chemin)
    d = pd.read_csv(chemin, sep=None, engine="python", dtype=object, encoding="utf-8-sig") if chemin.suffix.lower() == ".csv" \
        else pd.read_excel(chemin, dtype=object)
    trouve = {}
    for c in d.columns:
        for cible, alias in COLONNES_BOM.items():
            if cible not in trouve and _cle(c).replace(" ", "") in alias:
                trouve[cible] = c
    if "PN" not in trouve or "Description" not in trouve:
        raise ValueError("Nomenclature illisible : il faut une colonne de code article (PN) et une colonne Description. "
                         f"Colonnes trouvées : {', '.join(map(str, d.columns))}")
    out = pd.DataFrame({cible: d[c] for cible, c in trouve.items()})
    for c in COLONNES_BOM:
        if c not in out:
            out[c] = None
    out["PN"] = out["PN"].map(ref)
    out = out.dropna(subset=["PN"])
    oui = {"oui", "o", "yes", "y", "true", "1", "vrai", "make", "interne"}
    out["Interne"] = out["Interne"].map(lambda v: str(v).strip().lower() in oui if isinstance(v, str) or (v is not None and not pd.isna(v)) else False)
    out["Poids (kg)"] = pd.to_numeric(out["Poids (kg)"].astype(str).str.replace(",", ".", regex=False), errors="coerce")
    liens = out[["PN", "FRU", "Quantité"]].dropna(subset=["FRU"]).copy()
    out = out.drop_duplicates("PN").reset_index(drop=True)[list(COLONNES_BOM)]
    out.attrs["liens"] = liens
    return out


def regle(description, regles: pd.DataFrame):
    """Première règle dont le motif (expression régulière, sans casse) se trouve dans le texte : (classe, motif) ou None."""
    if regles is None or not len(regles):
        return None
    t = str(description or "")
    for _, r in regles.iterrows():
        m, c = r.get("Motif"), r.get("Classe")
        if isinstance(m, str) and isinstance(c, str) and m.strip() and c.strip():
            try:
                if re.search(m, t, re.I):
                    return c.strip(), m
            except re.error:
                continue                                       # motif mal écrit : ignoré, signalé par regles_invalides
    return None


def regles_invalides(regles: pd.DataFrame) -> list:
    out = []
    for _, r in (regles if regles is not None else pd.DataFrame()).iterrows():
        try:
            re.compile(str(r.get("Motif")))
        except re.error as e:
            out.append(f"{r.get('Motif')} : {e}")
    return out


def requete_publique(piece: dict):
    """Ce qui peut sortir pour chercher une pièce : fabricant, référence du fabricant, type générique. Jamais le code
    article interne ni la description. None si la pièce est de conception interne ou n'a pas de référence de fabricant."""
    if piece.get("Interne"):
        return None
    mpn, fab = piece.get("Référence fabricant"), piece.get("Fabricant")
    if not isinstance(mpn, str) or not mpn.strip():
        return None
    t = type_piece(piece.get("Description"))
    return {"fabricant": fab.strip() if isinstance(fab, str) else "", "reference_fabricant": mpn.strip(),
            "type": "" if t.startswith("(") else t}


# --------------------------------------------------------------------------- modèle de langage local (Qwen ou autre)
class ModeleLocal:
    """Client d'un serveur compatible avec l'interface « chat completions » (Ollama, LM Studio, llama.cpp, vLLM…).

    Deux usages, tous deux à réponse contrainte :
      extraire(texte, classes) : classe matière lue dans un document, avec la citation qui la justifie ;
      valider(classe, texte)   : le document confirme-t-il cette classe ? oui, non, ou ne sait pas.
    Garde-fous sans appel supplémentaire : la classe doit être une des classes proposées, et la citation doit se
    trouver mot pour mot dans le document ; sinon la réponse est rejetée. Une panne du serveur rend None.
    """

    def __init__(self, url: str = "http://localhost:11434/v1", modele: str = "qwen", cle: str | None = None, delai: float = 60.0):
        self.url, self.modele, self.cle, self.delai, self.appels = url.rstrip("/"), modele, cle, delai, 0

    def demander(self, consigne: str, contenu: str):
        self.appels += 1
        corps = json.dumps({"model": self.modele, "temperature": 0, "messages": [{"role": "system", "content": consigne},
                                                                                {"role": "user", "content": contenu}]}).encode("utf-8")
        entetes = {"Content-Type": "application/json", **({"Authorization": f"Bearer {self.cle}"} if self.cle else {})}
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{self.url}/chat/completions", data=corps, headers=entetes), timeout=self.delai) as r:
                return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]
        except Exception:
            return None

    @staticmethod
    def _objet(texte):
        m = re.search(r"\{.*\}", texte or "", re.S)
        try:
            return json.loads(m.group(0)) if m else None
        except ValueError:
            return None

    def extraire(self, texte: str, classes) -> tuple:
        classes = list(classes)
        consigne = ("Tu lis un document technique sur un composant. Choisis la classe matière qui lui correspond parmi cette liste, "
                    "et seulement si le document le permet : " + " ; ".join(classes) + ". Réponds en JSON : "
                    '{"classe": "<une classe de la liste, ou null>", "citation": "<passage du document, recopié mot pour mot, qui le justifie>"}')
        o = self._objet(self.demander(consigne, texte[:6000]))
        if not isinstance(o, dict) or o.get("classe") not in classes:
            return None, ""
        citation = str(o.get("citation") or "")
        propre = lambda s: re.sub(r"\s+", " ", s).strip().lower()
        if len(propre(citation)) < 8 or propre(citation) not in propre(texte):
            return None, ""                                    # citation absente du document : réponse non fondée, rejetée
        return o["classe"], citation

    def valider(self, classe: str, texte: str):
        consigne = ("Tu vérifies une affirmation contre un document. Réponds en JSON : "
                    '{"verdict": "oui"} si le document confirme l\'affirmation, {"verdict": "non"} s\'il la contredit, '
                    '{"verdict": "indetermine"} s\'il ne permet pas de trancher.')
        o = self._objet(self.demander(consigne, f"Affirmation : ce composant relève de la classe matière « {classe} ».\n\nDocument :\n{texte[:6000]}"))
        v = str((o or {}).get("verdict", "")).strip().lower()
        return True if v == "oui" else False if v == "non" else None


# --------------------------------------------------------------------------- chaîne d'acquisition pour une pièce
def enjeu(masse_annuelle_kg, probabilites: dict, prix: dict) -> float:
    """Borne de la valeur de l'information sur la classe d'une pièce : masse annuelle × E|p − p̄| sous la croyance
    actuelle. Inconnu si la masse est inconnue, ou si une classe plausible (plus de 5 %) n'a pas de prix."""
    if masse_annuelle_kg is None or not np.isfinite(masse_annuelle_kg):
        return float("nan")
    c = [(p, prix.get(k)) for k, p in probabilites.items() if p > 0]
    if any(v is None or not np.isfinite(v) for p, v in c if p > 0.05):
        return float("nan")
    c = [(p, v) for p, v in c if v is not None and np.isfinite(v)]
    if not c:
        return float("nan")
    p, v = np.array([x[0] for x in c]), np.array([x[1] for x in c])
    p = p / p.sum()
    return float(masse_annuelle_kg * (p @ np.abs(v - p @ v)))


def preuves_gratuites(cx: mod_cortex.Cortex, piece: dict, regles, reglages: "Reglages", classement_anterieur: str | None = None) -> None:
    """Étapes 1 à 3 : règle sur la description, analogie avec une pièce validée, classement antérieur. Sans coût, et
    enregistrées même pour une pièce déjà validée : c'est en les comparant aux validations que le cortex apprend ce que
    vaut chaque type de source."""
    pn, desc = str(piece["PN"]), piece.get("Description") or ""
    r = regle(desc, regles)
    if r:
        cx.affirmer(DOMAINE, pn, ATTRIBUT, r[0], "règle", f"règle : {r[1]}", {"motif": r[1]})
    for voisin, s, classe in cx.voisins(DOMAINE, ATTRIBUT, desc, k=1, seuil=reglages.seuil_analogie, sauf=pn):
        cx.affirmer(DOMAINE, pn, ATTRIBUT, classe, "analogie", f"analogie : {voisin}", {"voisin": voisin, "ressemblance": round(s, 3)})
    if isinstance(classement_anterieur, str) and classement_anterieur.strip():
        cx.affirmer(DOMAINE, pn, ATTRIBUT, classement_anterieur.strip(), "classement antérieur", "classement antérieur")


def resoudre(cx: mod_cortex.Cortex, piece: dict, classes, prix: dict, regles: pd.DataFrame | None = None, reglages: Reglages | None = None,
             masse_annuelle_kg=None, collecteur=None, modele=None, a_priori: dict | None = None, classement_anterieur: str | None = None,
             fiabilites: pd.DataFrame | None = None) -> dict:
    """Résout la classe matière d'une pièce en suivant la chaîne décrite en tête de module ; écrit dans le cortex.
    `fiabilites` : fiabilité des sources à utiliser (défaut : celle que le cortex déduit de ses validations)."""
    g = reglages or Reglages()
    pn, desc = str(piece["PN"]), piece.get("Description") or ""
    cx.declarer(DOMAINE, pn, desc, bool(piece.get("Interne")))
    appels, cout = 0, 0.0
    croire = lambda: cx.croyance(DOMAINE, pn, ATTRIBUT, classes, a_priori, fiabilites)

    def bilan(b, statut, suite):
        return {"PN": pn, "Description": desc, "Classe retenue": b["retenue"], "Probabilité": b["probabilite"], "Statut": statut,
                "Sources": ", ".join(b["sources"]), "Preuves": b["preuves"], "Enjeu (€/an, borne)": enjeu(masse_annuelle_kg, b["probabilites"], prix) if not b["validee"] else 0.0,
                "Appels au modèle": appels, "Coût des acquisitions (€)": cout, "Prochaine action": suite}

    preuves_gratuites(cx, piece, regles, g, classement_anterieur)
    b = croire()
    if b["validee"]:
        return bilan(b, "validée", "aucune")
    if b["preuves"] and b["probabilite"] >= g.seuil_acceptation:
        return bilan(b, "acceptée", "aucune : contrôle par sondage")
    # 4 à 6 : sources payantes, seulement si l'enjeu les justifie
    e = enjeu(masse_annuelle_kg, b["probabilites"], prix)
    requete = requete_publique(piece)
    if collecteur is not None and requete is not None and np.isfinite(e) and e >= g.cout_collecte:
        cout += g.cout_collecte
        try:
            documents = list(collecteur(requete) or [])[: g.max_documents]
        except Exception as ex:                                # une collecte en panne n'arrête pas la chaîne
            documents = []
            cx.noter(DOMAINE, pn, "collecte", g.cout_collecte, f"échec : {type(ex).__name__}")
        else:
            cx.noter(DOMAINE, pn, "collecte", g.cout_collecte, f"{len(documents)} document(s)")
        meilleur = None
        for d in documents:
            origine, texte = str(d.get("origine") or "document"), str(d.get("texte") or "")
            declaration = d.get("nature") == "déclaration fabricant"
            # Un document n'est PAS relu avec les règles de description : la même règle appliquée à deux textes ne fait
            # pas deux sources indépendantes. Seuls comptent une classe donnée explicitement par le collecteur, les
            # matières nommées par une déclaration du fabricant, ou la lecture par le modèle.
            if isinstance(d.get("classe"), str) and d["classe"] in list(classes):
                cx.affirmer(DOMAINE, pn, ATTRIBUT, d["classe"], "déclaration fabricant" if declaration else "document", origine)
                meilleur = meilleur or (origine, texte)
            elif declaration and regle(texte, regles):
                lu = regle(texte, regles)
                cx.affirmer(DOMAINE, pn, ATTRIBUT, lu[0], "déclaration fabricant", origine, {"motif": lu[1]})
                meilleur = meilleur or (origine, texte)
            elif modele is not None and e >= g.cout_extraction:
                appels, cout = appels + 1, cout + g.cout_extraction
                classe, citation = modele.extraire(texte, classes)
                cx.noter(DOMAINE, pn, "lecture par le modèle", g.cout_extraction, classe or "sans réponse fondée")
                if classe:
                    cx.affirmer(DOMAINE, pn, ATTRIBUT, classe, "modèle : extraction", origine, {"citation": citation})
                    meilleur = meilleur or (origine, texte)
        b = croire()
        if modele is not None and meilleur and b["preuves"] and g.seuil_doute - 1e-9 <= b["probabilite"] < g.seuil_acceptation and e >= g.cout_validation:
            appels, cout = appels + 1, cout + g.cout_validation
            verdict = modele.valider(b["retenue"], meilleur[1])
            cx.noter(DOMAINE, pn, "contrôle par le modèle", g.cout_validation, {True: "confirme", False: "contredit", None: "ne tranche pas"}[verdict])
            if verdict is not None:
                cx.affirmer(DOMAINE, pn, ATTRIBUT, b["retenue"], "modèle : validation", f"{meilleur[0]} # contrôle", polarite=1 if verdict else -1)
            b = croire()
    if b["preuves"] and b["probabilite"] >= g.seuil_acceptation:
        return bilan(b, "acceptée", "aucune : contrôle par sondage")
    e = enjeu(masse_annuelle_kg, b["probabilites"], prix)
    if not np.isfinite(e):
        suite = "revue humaine si la pièce compte : enjeu inconnu (poids, volume ou prix d'une classe manquant)"
    elif e < g.cout_revue:
        suite = "aucune : connaître la classe rapporterait moins que le coût d'une revue"
    elif piece.get("Interne"):
        suite = "revue humaine (pièce de conception interne : aucune recherche extérieure)"
    elif requete is None:
        suite = "revue humaine, ou renseigner le fabricant et sa référence pour permettre la collecte"
    elif collecteur is None:
        suite = "revue humaine, ou brancher un collecteur de documents"
    else:
        suite = "revue humaine"
    return bilan(b, "à valider" if b["preuves"] else "inconnue", suite)


def importer_validations(cx: mod_cortex.Cortex, table: pd.DataFrame) -> int:
    """Validations humaines : colonnes « PN », « Classe validée » et, facultatives, « Validateur », « Commentaire »."""
    n = 0
    for _, r in table.iterrows():
        pn, c = ref(r.get("PN")), r.get("Classe validée")
        if isinstance(pn, str) and isinstance(c, str) and c.strip():
            deja = cx.verite(DOMAINE, pn, ATTRIBUT)
            if deja != c.strip():
                cx.valider(DOMAINE, pn, ATTRIBUT, c.strip(), str(r.get("Validateur") or "non précisé"), str(r.get("Commentaire") or ""))
                n += 1
    return n


def traiter(cx: mod_cortex.Cortex, bom: pd.DataFrame, classes, prix: dict, regles=None, reglages: Reglages | None = None,
            masses: dict | None = None, collecteur=None, modele=None, classement: dict | None = None) -> dict:
    """Toute une nomenclature. Renvoie les tables de résultat ; la file de revue est triée par enjeu décroissant."""
    g = reglages or Reglages()
    for _, p in bom.iterrows():                                  # tous les sujets d'abord : l'analogie voit toute la nomenclature
        cx.declarer(DOMAINE, str(p["PN"]), p.get("Description") or "", bool(p.get("Interne")))
    v = cx.verites(DOMAINE, ATTRIBUT)
    freq = pd.Series(list(v.values()), dtype=object).value_counts()
    a_priori = {c: float(freq.get(c, 0) + 1) for c in classes}   # fréquence des classes validées, lissée d'une unité
    # Premier passage : les preuves gratuites de toutes les pièces. La fiabilité des sources est ensuite figée pour le
    # second passage, de sorte que le résultat ne dépend pas de l'ordre des lignes de la nomenclature.
    for _, p in bom.iterrows():
        preuves_gratuites(cx, p.to_dict(), regles, g, (classement or {}).get(str(p["PN"])))
    fiab_figee = cx.fiabilites(DOMAINE, ATTRIBUT)
    lignes = [resoudre(cx, p.to_dict(), classes, prix, regles, g, (masses or {}).get(str(p["PN"])), collecteur, modele, a_priori,
                       (classement or {}).get(str(p["PN"])), fiab_figee) for _, p in bom.iterrows()]
    cx.base.commit()
    res = pd.DataFrame(lignes, columns=COLS_RESULTAT)
    file_ = res[res["Statut"].isin(["à valider", "inconnue"])].copy()
    file_["Vaut une revue"] = np.where(file_["Enjeu (€/an, borne)"].isna(), "enjeu inconnu", np.where(file_["Enjeu (€/an, borne)"] >= g.cout_revue, "oui", "non"))
    file_ = file_.sort_values("Enjeu (€/an, borne)", ascending=False, na_position="last")
    file_.insert(len(file_.columns), "Classe validée", "")       # à remplir par la personne qui relit, puis à réimporter
    file_.insert(len(file_.columns), "Validateur", "")
    fiab = cx.fiabilites(DOMAINE, ATTRIBUT).drop(columns=["_a", "_b"])
    statuts = res["Statut"].value_counts().to_dict()
    return {"Composition proposée": res, "File de revue": file_.reset_index(drop=True), "Fiabilité des sources": fiab,
            "Journal des acquisitions": cx.journal(DOMAINE),
            "Notes": {"pieces": len(res), "statuts": statuts, "appels_au_modele": int(res["Appels au modèle"].sum()),
                      "cout_des_acquisitions_eur": float(res["Coût des acquisitions (€)"].sum()),
                      "pieces_sans_appel_payant": int((res["Coût des acquisitions (€)"] == 0).sum()),
                      "classes": list(classes), "seuil_acceptation": g.seuil_acceptation, "couts_hypotheses_de_travail": {
                          "collecte": g.cout_collecte, "lecture par le modèle": g.cout_extraction, "contrôle par le modèle": g.cout_validation, "revue humaine": g.cout_revue},
                      "collecteur": "branché" if collecteur is not None else "absent", "modele": "branché" if modele is not None else "absent",
                      "cortex": mod_cortex.Cortex.bilan(cx, DOMAINE, ATTRIBUT)}}


# --------------------------------------------------------------------------- dans le dossier : après le pipeline principal
def executer(ctx, collecteur=None, modele=None, reglages: Reglages | None = None) -> dict:
    """Lance la chaîne sur la nomenclature du dossier et dépose ses tables dans artefacts/composition/.

    ctx : contexte rendu par erc.executer() (au moins jusqu'à l'étape « classement » ; jusqu'à « ligne » pour classer
    les pièces par valeur de l'information dans le modèle de ligne). Sans fichier de nomenclature, la liste des pièces
    consommées sert de nomenclature. En démonstration, un collecteur et un modèle FICTIFS sont utilisés et signalés.
    """
    from . import information
    cfg, src = ctx.cfg, ctx.src
    E = "composition"
    prix = {k: float(v) for k, v in src.prix_recycleur.items()}
    classes = list(prix) or sorted({c for c in src.classification["Catégorie proposée"].dropna().astype(str)})
    fictifs = False
    if cfg.demo and collecteur is None and modele is None:
        from . import demo
        collecteur, modele, fictifs = demo.collecteur_fictif, demo.ModeleFictif(), True
    chemin = cfg.chemin_bom()
    if chemin is not None:
        bom, origine_bom = lire_bom(chemin), chemin.name
    else:
        bom = pd.DataFrame({"PN": src.desc_piece.index.astype(str), "Description": src.desc_piece.values})
        for c in COLONNES_BOM:
            if c not in bom:
                bom[c] = None
        bom["Interne"], origine_bom = False, "aucun fichier de nomenclature : pièces consommées dans les extractions"
    tous = ctx.res.get("classement", {}).get("Classement tous ateliers", pd.DataFrame())
    masses = {}
    jours = len(src.couverts)
    if len(tous) and jours:
        poids = bom.set_index("PN")["Poids (kg)"].astype(float).to_dict() if len(bom) else {}
        for _, r in tous.iterrows():
            w = r.get("Poids unitaire (kg)")
            w = w if w is not None and np.isfinite(w) else poids.get(str(r["Référence"]), np.nan)
            masses[str(r["Référence"])] = float(r["Pièces"]) * 365.0 / jours * w if np.isfinite(w) else np.nan
    regles = getattr(ctx.params, "regles", None)
    classement = src.classification["Catégorie proposée"].dropna().astype(str).to_dict()
    vide = {"Composition proposée": pd.DataFrame(columns=COLS_RESULTAT), "File de revue": pd.DataFrame(), "Fiabilité des sources": pd.DataFrame(),
            "Journal des acquisitions": pd.DataFrame(), "Valeur de l'information": pd.DataFrame()}
    if len(classes) < 2:
        tables = dict(vide, Notes={"motif": "moins de deux classes matière connues : il faut le référentiel des grades (classes et prix)"})
    else:
        with mod_cortex.Cortex(cfg.cortex) as cx:
            f = cfg.projet / "Acquisition" / "validations_composition.csv" if cfg.projet else None
            importees = 0
            if f is not None and f.is_file():
                importees = importer_validations(cx, pd.read_csv(f, sep=";", dtype=object, encoding="utf-8-sig"))
            tables = traiter(cx, bom, classes, prix, regles, reglages, masses, collecteur, modele, classement)
            croyances = {pn: cx.croyance(DOMAINE, pn, ATTRIBUT, classes)["probabilites"] for pn in tables["File de revue"]["PN"]} if len(tables["File de revue"]) else {}
        tables["Notes"].update({"nomenclature": origine_bom, "validations_importees": importees, "regles": 0 if regles is None else len(regles),
                                "regles_invalides": regles_invalides(regles), "fournisseurs_fictifs": fictifs})
        # Valeur de l'information dans le modèle de ligne, pour les pièces encore incertaines qui y figurent
        modele_ligne = ctx.res.get("ligne", {}).get("Modèle")
        inc = []
        if modele_ligne:
            for fru, d in modele_ligne["frus"].items():
                for pc in d.get("pieces", {}):
                    pr = [(prix[c], q) for c, q in croyances.get(pc, {}).items() if q > 0.01 and c in prix]
                    if len(pr) >= 2:
                        inc.append({"Type de FRU": fru, "Pièce": pc, "Paramètre": "prix_recycleur_eur_kg", "Valeurs": [x[0] for x in pr], "Probabilités": [x[1] for x in pr]})
        g = reglages or Reglages()
        tables["Valeur de l'information"] = information.priorites(modele_ligne["ligne"], modele_ligne["frus"], pd.DataFrame(inc), g.cout_revue) \
            if inc else pd.DataFrame(columns=["Type de FRU", "Pièce", "Paramètre", "Borne (€/an)", "Valeur de l'information (€/an)", "La décision change", "Calcul exact", "À acquérir"])
    for nom, t in tables.items():
        if isinstance(t, pd.DataFrame):
            ctx.depot.table(E, nom, t, {"Composition proposée": "Classe matière la plus probable de chaque pièce, probabilité, sources, statut, suite à donner",
                                        "File de revue": "Pièces à faire valider par une personne, par enjeu décroissant ; à remplir puis à réimporter",
                                        "Fiabilité des sources": "Ce que valent les sources, appris sur les pièces validées, à côté de l'a priori de départ",
                                        "Journal des acquisitions": "Chaque collecte et chaque appel au modèle, avec son coût",
                                        "Valeur de l'information": "Pièces du modèle de ligne dont la classe est incertaine : ce que rapporterait de la connaître"}.get(nom, ""))
        else:
            ctx.depot.json(E, nom, t, "Volumes, statuts, appels au modèle, coûts supposés, état du cortex")
    ctx.depot.classeur(E)
    ctx.depot.ecrire_manifeste()
    ctx.res[E] = tables
    return tables


def main(argv=None) -> int:
    import argparse

    from .config import charger
    from .etapes import executer as pipeline
    a = argparse.ArgumentParser(prog="python -m erc.composition", description="Composition des pièces d'une nomenclature, avec le cortex du dossier")
    a.add_argument("--demo", action="store_true")
    a.add_argument("--dossier")
    a.add_argument("--bom", help="fichier Excel ou CSV de la nomenclature (PN, Description, et si possible Fabricant, Référence fabricant)")
    a.add_argument("--modele-url", help="serveur local compatible « chat completions », par exemple http://localhost:11434/v1")
    a.add_argument("--modele-nom", default="qwen")
    o = a.parse_args(argv)
    cfg = charger(dossier=o.dossier, demo=True if o.demo else None)
    if o.bom:
        cfg.bom = o.bom
    ctx = pipeline("ligne", cfg=cfg, silencieux=True)
    t = executer(ctx, modele=ModeleLocal(o.modele_url, o.modele_nom) if o.modele_url else None)
    n = t["Notes"]
    print(f"{n.get('pieces', 0)} pièces | statuts : {n.get('statuts', {})} | appels au modèle : {n.get('appels_au_modele', 0)} | "
          f"sans appel payant : {n.get('pieces_sans_appel_payant', 0)}")
    print("Tables : artefacts/composition/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
