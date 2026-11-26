"""Composition des pièces d'une nomenclature (BOM) : de la description et du code article à la classe matière.

Entrée : une liste Excel (code article, description, et si possible fabricant et référence du fabricant).
Sortie : pour chaque pièce, la classe matière la plus probable, sa probabilité, les sources, un statut, et ce qu'il
reste à faire. Tout est écrit dans le cortex (erc/cortex.py), qui garde les preuves et apprend la fiabilité des sources.

La chaîne va du moins cher au plus cher et s'arrête dès que possible :

  0  le cortex connaît déjà la pièce (validée par une personne)                      gratuit, aucun appel
  1  une règle sur la description                                                      gratuit
  2  une pièce validée de description proche (analogie)                                gratuit
  3  le classement antérieur de la pièce, s'il existe                                  gratuit
  ── la suite coûte : chaque action n'est lancée que si l'enjeu de la pièce couvre ce qui a déjà été dépensé pour
     elle plus le coût de l'action, et la chaîne s'arrête dès que la classe est acceptée ──
  4  collecte de documents publics (fiche du fabricant, déclaration matière)           un appel au collecteur
  5  lecture du document par un modèle de langage, sauf classe donnée par le document  un appel au modèle
  6  contrôle de la classe retenue par un modèle (Qwen ou autre), seulement si un      un appel au modèle
     « oui » suffirait à la faire accepter
  7  revue par une personne, par ordre d'enjeu

Sans classe, pas de bac : une pièce dont la classe n'est pas établie ne peut pas être triée. L'ENJEU d'une pièce borne
donc ce que rapporterait par an d'établir sa classe (docs/Formal_framework.md, proposition 7) :

    masse annuelle concernée × moyenne, sur les classes possibles, de (prix du recycleur + traitement évité)⁺

Une pièce légère ou rare ne déclenche aucun appel payant : c'est ce qui réduit les appels au modèle au minimum.
Une classe est ACCEPTÉE sans revue quand sa probabilité atteint le seuil et que ce qu'une erreur peut coûter reste
sous le coût d'une revue ; les classes acceptées sont contrôlées par sondage (page de revue).

Confidentialité. Aucun code article interne ni aucune description ne sort : une requête ne contient que le fabricant,
sa référence et un type générique de pièce. Elle n'est émise que si le fabricant est nommé, n'est pas l'entreprise
elle-même, et si la référence a la forme d'une référence de fabricant et n'est le code article d'aucune pièce de la
nomenclature. Une pièce déclarée de conception interne n'est jamais recherchée ; toute valeur non reconnue dans la
colonne « interne » vaut « interne ». La garantie suppose que la colonne « référence fabricant » contient bien des
références de fabricant : c'est à vérifier sur la nomenclature avant de brancher une collecte.

Le collecteur et le modèle sont des pièces rapportées : toute fonction ou tout objet qui respecte l'interface convient
(votre méthode de collecte existante, un serveur Qwen local). Sans eux, la chaîne s'arrête à l'étape 3 et dit ce qui manque.

    collecteur(requete) -> [{"origine": ..., "texte": ..., "nature": "document" | "déclaration fabricant", "classe": ...}]
        requete = {"fabricant", "reference_fabricant", "type"} ; « classe » est facultative (déclaration structurée)
    modele.extraire(texte, classes) -> (classe ou None, citation)
    modele.valider(classe, texte)   -> True, False ou None

Vocabulaire : « collecte » désigne la recherche de documents sur le web ; « scrapé » reste réservé aux pièces mises au scrap.
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from . import composition_outil
from . import cortex as mod_cortex
from .cortex import HORS, plier, texte
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
# Seules ces valeurs de la colonne « interne » disent qu'une pièce est achetée ; toute autre valeur saisie dit « interne ».
NON_INTERNE = {"non", "n", "no", "false", "faux", "0", "0.0", "buy", "achat", "achete", "achetee", "externe", "purchased"}
FORME_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._/+#-]{2,39}")       # forme admise d'une référence de fabricant
SANS_MODELE = ", sans modèle"           # marque, au journal, une collecte faite sans modèle pour lire les documents
A_REPRENDRE = ", à reprendre"           # marque une collecte dont une lecture a échoué (panne du modèle) : à refaire
TOLERANCE_SANS_PRIX = 0.01              # probabilité totale tolérée pour des classes de la liste dont le prix manque
COLS_RESULTAT = ["PN", "Description", "Classe retenue", "Probabilité", "Statut", "Sources", "Preuves", "Enjeu (€/an, borne)",
                 "Appels au modèle", "Coût des acquisitions (€)", "Prochaine action"]


@dataclass
class Reglages:
    """Seuils et coûts de la chaîne. Les coûts sont des HYPOTHÈSES DE TRAVAIL à régler : ils servent seulement à
    comparer une action à l'enjeu de la pièce."""
    seuil_acceptation: float = 0.90      # probabilité à partir de laquelle une classe peut être acceptée sans revue
    seuil_analogie: float = 0.50         # part minimale de mots communs avec une pièce validée
    cout_collecte: float = 0.02          # € par recherche de documents
    cout_extraction: float = 0.05        # € par lecture de document par le modèle
    cout_validation: float = 0.03        # € par contrôle par le modèle
    cout_revue: float = 5.0              # € par revue humaine d'une pièce (quelques minutes)
    max_documents: int = 3
    recollecter: bool = False            # True : refaire la recherche payante d'une pièce déjà cherchée
    fabricants_internes: tuple = ()      # noms de l'entreprise et de ses sites : jamais recherchés à l'extérieur


# --------------------------------------------------------------------------- lecture de la nomenclature
def _est_interne(v) -> bool:
    """Cellule de la colonne « interne ». Vide : rien n'est déclaré. Sinon, seule une négation reconnue dit « achetée »."""
    t = plier(v).strip()
    return t != "" and t not in NON_INTERNE


def _lire_csv(chemin: Path) -> pd.DataFrame:
    for encodage in ("utf-8-sig", "cp1252"):                     # UTF-8, puis l'encodage des exports Excel sous Windows
        try:
            return pd.read_csv(chemin, sep=None, engine="python", dtype=object, encoding=encodage)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Nomenclature illisible : encodage de {chemin.name} non reconnu (UTF-8 ou Windows-1252 attendu)")


def lire_bom(chemin) -> pd.DataFrame:
    """Nomenclature en table normalisée, une ligne par code article. Les colonnes sont reconnues sans casse ni accent.
    Seuls « PN » et « Description » sont nécessaires ; une colonne absente reste vide."""
    chemin = Path(chemin)
    d = _lire_csv(chemin) if chemin.suffix.lower() == ".csv" else pd.read_excel(chemin, dtype=object)
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
    out["Interne"] = out["Interne"].map(_est_interne)
    out["Poids (kg)"] = pd.to_numeric(out["Poids (kg)"].astype(str).str.replace(",", ".", regex=False), errors="coerce")
    liens = out[["PN", "FRU", "Quantité"]].dropna(subset=["FRU"]).copy()
    out = out.drop_duplicates("PN").reset_index(drop=True)[list(COLONNES_BOM)]
    out.attrs["liens"] = liens
    return out


def _sans_accent(motif: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", motif.replace("œ", "oe").replace("æ", "ae")) if not unicodedata.combining(c))


def regle(description, regles: pd.DataFrame):
    """Première règle dont le motif (expression régulière) se trouve dans le texte : (classe, motif) ou None.
    Ni la casse ni les accents ne comptent : « cable » reconnaît « Câble blindé »."""
    if regles is None or not len(regles):
        return None
    t = plier(description)
    for _, r in regles.iterrows():
        m, c = r.get("Motif"), r.get("Classe")
        if isinstance(m, str) and isinstance(c, str) and m.strip() and c.strip():
            try:
                if re.search(_sans_accent(m), t, re.I):
                    return c.strip(), m
            except re.error:
                continue                                       # motif mal écrit : ignoré, signalé par regles_invalides
    return None


def regles_invalides(regles: pd.DataFrame) -> list:
    out = []
    for _, r in (regles if regles is not None else pd.DataFrame()).iterrows():
        try:
            re.compile(_sans_accent(str(r.get("Motif"))))
        except re.error as e:
            out.append(f"{r.get('Motif')} : {e}")
    return out


def requete_publique(piece: dict, pns=(), fabricants_internes=()):
    """Ce qui peut sortir pour chercher une pièce : fabricant, référence du fabricant, type générique. Jamais le code
    article interne ni la description.

    None, donc aucune recherche, si la pièce est déclarée de conception interne ; si le fabricant n'est pas nommé ou
    est l'entreprise elle-même ; si la référence n'a pas la forme d'une référence de fabricant ; ou si elle est le code
    article de cette pièce ou d'une autre pièce de la nomenclature (`pns`)."""
    if piece.get("Interne"):
        return None
    mpn, fab = texte(piece.get("Référence fabricant")).strip(), texte(piece.get("Fabricant")).strip()
    if not mpn or not fab or plier(fab) in {plier(x) for x in fabricants_internes}:
        return None
    if not FORME_REFERENCE.fullmatch(mpn) or ref(mpn) == ref(piece.get("PN")) or ref(mpn) in pns:
        return None
    t = type_piece(texte(piece.get("Description")))
    return {"fabricant": fab, "reference_fabricant": mpn, "type": "" if t.startswith("(") else t}


# --------------------------------------------------------------------------- modèle de langage local (Qwen ou autre)
class Indisponible(Exception):
    """Le serveur du modèle n'a pas répondu : l'appel est à refaire, il n'est pas compté."""


class ModeleLocal:
    """Client d'un serveur compatible avec l'interface « chat completions » (Ollama, LM Studio, llama.cpp, vLLM…).

    Deux usages, tous deux à réponse contrainte :
      extraire(texte, classes) : classe matière lue dans un document, avec la citation qui la justifie ;
      valider(classe, texte)   : le document confirme-t-il cette classe ? oui, non, ou ne sait pas.
    Garde-fous sans appel supplémentaire : la classe doit être une des classes proposées, et la citation doit se
    trouver mot pour mot dans le document ; sinon la réponse est rejetée. Une panne du serveur lève `Indisponible`.
    Le serveur doit tourner sur ce poste (localhost) : le texte des documents et la liste des classes lui sont envoyés.
    Pour un serveur distant, le dire explicitement avec distant=True.
    """

    def __init__(self, url: str = "http://localhost:11434/v1", modele: str = "qwen", cle: str | None = None, delai: float = 60.0,
                 distant: bool = False):
        hote = (urlparse(url).hostname or "").lower()
        if not (hote in ("localhost", "::1") or hote.startswith("127.")) and not distant:
            raise ValueError(f"Le serveur de modèle « {hote} » n'est pas sur ce poste. Les documents lus lui seraient envoyés : "
                             "pour l'accepter, créer le modèle avec distant=True.")
        self.url, self.modele, self.cle, self.delai, self.appels = url.rstrip("/"), modele, cle, delai, 0

    def demander(self, consigne: str, contenu: str) -> str:
        self.appels += 1
        corps = json.dumps({"model": self.modele, "temperature": 0, "messages": [{"role": "system", "content": consigne},
                                                                                {"role": "user", "content": contenu}]}).encode("utf-8")
        entetes = {"Content-Type": "application/json", **({"Authorization": f"Bearer {self.cle}"} if self.cle else {})}
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{self.url}/chat/completions", data=corps, headers=entetes), timeout=self.delai) as r:
                return str(json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"])
        except Exception as e:
            raise Indisponible(type(e).__name__) from e

    @staticmethod
    def _objet(reponse):
        m = re.search(r"\{.*\}", reponse or "", re.S)
        try:
            return json.loads(m.group(0)) if m else None
        except ValueError:
            return None

    def extraire(self, document: str, classes) -> tuple:
        classes = list(classes)
        consigne = ("Tu lis un document technique sur un composant. Choisis la classe matière qui lui correspond parmi cette liste, "
                    "et seulement si le document le permet : " + " ; ".join(classes) + ". Réponds en JSON : "
                    '{"classe": "<une classe de la liste, ou null>", "citation": "<passage du document, recopié mot pour mot, qui le justifie>"}')
        o = self._objet(self.demander(consigne, document[:6000]))
        if not isinstance(o, dict) or o.get("classe") not in classes:
            return None, ""
        citation = str(o.get("citation") or "")
        propre = lambda s: re.sub(r"\s+", " ", s).strip().lower()
        if len(propre(citation)) < 8 or propre(citation) not in propre(document):
            return None, ""                                    # citation absente du document : réponse non fondée, rejetée
        return o["classe"], citation

    def valider(self, classe: str, document: str):
        consigne = ("Tu vérifies une affirmation contre un document. Réponds en JSON : "
                    '{"verdict": "oui"} si le document confirme l\'affirmation, {"verdict": "non"} s\'il la contredit, '
                    '{"verdict": "indetermine"} s\'il ne permet pas de trancher.')
        o = self._objet(self.demander(consigne, f"Affirmation : ce composant relève de la classe matière « {classe} ».\n\nDocument :\n{document[:6000]}"))
        v = str((o or {}).get("verdict", "")).strip().lower()
        return True if v == "oui" else False if v == "non" else None


# --------------------------------------------------------------------------- enjeu d'une pièce
def _valeurs_nettes(probabilites: dict, prix: dict, cout_traitement):
    """{classe: (probabilité, (prix + traitement évité)⁺)}. None si des classes de la liste sans prix pèsent plus de
    TOLERANCE_SANS_PRIX : on ne peut alors rien borner. La case « hors référentiel » n'a pas de débouché trié : 0."""
    tau = 0.0 if cout_traitement is None or not np.isfinite(cout_traitement) else float(cout_traitement)
    sans_prix, out = 0.0, {}
    for c, q in probabilites.items():
        v = prix.get(c)
        if c == HORS:
            out[c] = (q, 0.0)
        elif v is None or not np.isfinite(v):
            sans_prix += q
        else:
            out[c] = (q, max(float(v) + tau, 0.0))
    return None if sans_prix > TOLERANCE_SANS_PRIX else out


def enjeu(masse_annuelle_kg, probabilites: dict, prix: dict, cout_traitement=0.0) -> float:
    """Ce que rapporterait au plus, par an, d'établir la classe de la pièce (proposition 7 du cadre formel) :
    masse annuelle × moyenne, sous la croyance actuelle, de (prix + traitement évité)⁺.
    Inconnu si la masse est inconnue ou si une classe plausible de la liste n'a pas de prix."""
    v = _valeurs_nettes(probabilites, prix, cout_traitement)
    if masse_annuelle_kg is None or not np.isfinite(masse_annuelle_kg) or v is None:
        return float("nan")
    return float(masse_annuelle_kg * sum(q * x for q, x in v.values()))


def enjeu_residuel(masse_annuelle_kg, probabilites: dict, retenue, prix: dict, cout_traitement=0.0) -> float:
    """Ce qu'une erreur sur la classe retenue peut coûter par an, au plus : masse annuelle × probabilité que la classe
    soit fausse × la meilleure valeur (prix + traitement évité)⁺ parmi les classes plausibles."""
    v = _valeurs_nettes(probabilites, prix, cout_traitement)
    if masse_annuelle_kg is None or not np.isfinite(masse_annuelle_kg) or v is None or retenue is None:
        return float("nan")
    plausibles = [x for c, (q, x) in v.items() if q >= 0.01 or c == retenue]
    return float(masse_annuelle_kg * (1.0 - probabilites.get(retenue, 0.0)) * max(plausibles, default=0.0))


# --------------------------------------------------------------------------- chaîne d'acquisition pour une pièce
def preuves_gratuites(cx: mod_cortex.Cortex, piece: dict, regles, reglages: "Reglages", classement_anterieur: str | None = None) -> None:
    """Étapes 1 à 3 : règle sur la description, analogie avec une pièce validée, classement antérieur. Sans coût, et
    enregistrées même pour une pièce déjà validée : c'est en les comparant aux validations que le cortex apprend ce que
    vaut chaque type de source. Chacune a une origine fixe : une règle modifiée remplace ce qu'elle disait, une source
    qui ne dit plus rien est retirée."""
    pn, desc = str(piece["PN"]), texte(piece.get("Description"))
    r = regle(desc, regles)
    if r:
        cx.affirmer(DOMAINE, pn, ATTRIBUT, r[0], "règle", "règle", {"motif": r[1]})
    else:
        cx.retirer(DOMAINE, pn, ATTRIBUT, "règle")
    voisins = cx.voisins(DOMAINE, ATTRIBUT, desc, k=1, seuil=reglages.seuil_analogie, sauf=pn)
    if voisins:
        voisin, s, classe = voisins[0]
        cx.affirmer(DOMAINE, pn, ATTRIBUT, classe, "analogie", "analogie", {"voisin": voisin, "ressemblance": round(s, 3)})
    else:
        cx.retirer(DOMAINE, pn, ATTRIBUT, "analogie")
    if texte(classement_anterieur).strip():
        cx.affirmer(DOMAINE, pn, ATTRIBUT, texte(classement_anterieur).strip(), "classement antérieur", "classement antérieur")
    else:
        cx.retirer(DOMAINE, pn, ATTRIBUT, "classement antérieur")


def _deja_cherchee(cx: mod_cortex.Cortex, pn: str, modele, g: Reglages) -> bool:
    """Une recherche déjà payée n'est pas refaite : ce qu'elle a trouvé est dans le cortex. Elle est refaite si elle
    avait échoué, si une lecture était restée en panne, ou si elle avait été faite sans modèle et qu'il y en a un."""
    if g.recollecter:
        return False
    for r in cx.actions(DOMAINE, pn, "collecte"):
        if r.startswith("échec") or A_REPRENDRE in r or (modele is not None and SANS_MODELE in r):
            continue
        return True
    return False


def resoudre(cx: mod_cortex.Cortex, piece: dict, classes, prix: dict, regles: pd.DataFrame | None = None, reglages: Reglages | None = None,
             masse_annuelle_kg=None, collecteur=None, modele=None, classement_anterieur: str | None = None,
             fiabilites: pd.DataFrame | None = None, modele_controle=None, cout_traitement=0.0, pns=(),
             preuves_posees: bool = False) -> dict:
    """Résout la classe matière d'une pièce en suivant la chaîne décrite en tête de module ; écrit dans le cortex.

    fiabilites      : fiabilité des sources à utiliser (défaut : celle que le cortex déduit de ses validations)
    modele_controle : modèle qui contrôle la classe retenue. S'il est distinct du modèle de lecture, son verdict est une
                      source de plus. Si c'est le même, un « oui » ne fait que confirmer sa propre lecture (une seule
                      source, plus fiable), et un « non » la retire.
    pns             : codes article de la nomenclature, pour ne jamais en envoyer un comme référence de fabricant
    """
    g = reglages or Reglages()
    classes = list(classes)
    pn, desc = str(piece["PN"]), texte(piece.get("Description"))
    cx.declarer(DOMAINE, pn, desc, bool(piece.get("Interne")))
    appels, cout = 0, 0.0
    deja_depense = cx.depense(DOMAINE, pn)
    croire = lambda en_plus=None, sans=None: cx.croyance(DOMAINE, pn, ATTRIBUT, classes, None, fiabilites, en_plus, sans)
    mise = lambda b: enjeu(masse_annuelle_kg, b["probabilites"], prix, cout_traitement)
    risque = lambda b: enjeu_residuel(masse_annuelle_kg, b["probabilites"], b["retenue"], prix, cout_traitement)

    def acceptee(b) -> bool:
        """Classe probable, dans le référentiel, et dont une erreur coûterait moins qu'une revue (ou d'enjeu inconnu)."""
        return bool(b["preuves"]) and b["retenue"] != HORS and b["probabilite"] >= g.seuil_acceptation and not risque(b) >= g.cout_revue

    def permis(b, c: float) -> bool:
        """L'enjeu couvre-t-il ce qui a déjà été dépensé pour cette pièce, plus cette action ?"""
        e = mise(b)
        return bool(np.isfinite(e) and e >= deja_depense + cout + c)

    def bilan(b, statut, suite):
        cx.conclure(DOMAINE, pn, ATTRIBUT, b["retenue"], b["probabilite"], statut)
        cx.base.commit()
        return {"PN": pn, "Description": desc, "Classe retenue": b["retenue"], "Probabilité": b["probabilite"], "Statut": statut,
                "Sources": ", ".join(b["sources"]), "Preuves": b["preuves"], "Enjeu (€/an, borne)": mise(b) if not b["validee"] else 0.0,
                "Appels au modèle": appels, "Coût des acquisitions (€)": cout, "Prochaine action": suite,
                "_probabilites": b["probabilites"]}

    if not preuves_posees:
        preuves_gratuites(cx, piece, regles, g, classement_anterieur)
    b = croire()
    if b["validee"]:
        return bilan(b, "validée", "aucune")
    # 4 à 6 : sources payantes
    requete = requete_publique(piece, pns, g.fabricants_internes)
    par_classe, lues = {}, {}            # classe → (origine, texte) du document qui la soutient ; origine → classe lue par le modèle
    if not acceptee(b) and collecteur is not None and requete is not None and not _deja_cherchee(cx, pn, modele, g) and permis(b, g.cout_collecte):
        cout += g.cout_collecte
        try:
            documents = [d for d in list(collecteur(requete) or []) if isinstance(d, dict)][: g.max_documents]
        except Exception as ex:                                # une collecte en panne n'arrête pas la chaîne
            documents = None
            cx.noter(DOMAINE, pn, "collecte", g.cout_collecte, f"échec : {type(ex).__name__}")
        if documents is not None:
            a_reprendre = False
            for d in documents:
                b = croire()
                if acceptee(b):
                    break                                      # la classe est établie : le reste des documents n'est pas lu
                origine, contenu = texte(d.get("origine")) or "document", texte(d.get("texte"))
                donnee = texte(d.get("classe")).strip()
                if donnee:                                     # classe donnée par le document lui-même (fiche, déclaration structurée)
                    declaration = d.get("nature") == "déclaration fabricant"
                    cx.affirmer(DOMAINE, pn, ATTRIBUT, donnee, "déclaration fabricant" if declaration else "document", origine)
                    par_classe.setdefault(donnee, (origine, contenu))
                elif modele is not None and contenu and permis(b, g.cout_extraction):
                    try:
                        classe, citation = modele.extraire(contenu, classes)
                    except Exception as ex:                    # panne du modèle : rien n'est compté, la lecture est à reprendre
                        cx.noter(DOMAINE, pn, "lecture par le modèle", 0.0, f"échec : {type(ex).__name__}")
                        a_reprendre = True
                        continue
                    appels, cout = appels + 1, cout + g.cout_extraction
                    if isinstance(classe, str) and classe in classes:
                        cx.noter(DOMAINE, pn, "lecture par le modèle", g.cout_extraction, classe)
                        cx.affirmer(DOMAINE, pn, ATTRIBUT, classe, "modèle : extraction", origine, {"citation": texte(citation)[:300]})
                        par_classe.setdefault(classe, (origine, contenu))
                        lues[origine] = classe
                    else:
                        cx.noter(DOMAINE, pn, "lecture par le modèle", g.cout_extraction, "sans réponse fondée")
            cx.noter(DOMAINE, pn, "collecte", g.cout_collecte,
                     f"{len(documents)} document(s)" + (SANS_MODELE if modele is None else "") + (A_REPRENDRE if a_reprendre else ""))
        # 6 : contrôle de la classe retenue, sur le document qui la soutient, seulement si un « oui » la ferait accepter
        b = croire()
        controleur = modele_controle if modele_controle is not None else modele
        if controleur is not None and not acceptee(b) and b["retenue"] in par_classe and b["retenue"] != HORS:
            origine, contenu = par_classe[b["retenue"]]
            meme_lecteur = controleur is modele and lues.get(origine) == b["retenue"]
            si_oui = croire([{"type_source": "modèle : extraction confirmée", "valeur": b["retenue"]}], [("modèle : extraction", origine)]) if meme_lecteur \
                else croire([{"type_source": "modèle : validation", "valeur": b["retenue"], "nature": "verdict"}])
            if si_oui["probabilite"] >= g.seuil_acceptation and si_oui["retenue"] == b["retenue"] and permis(b, g.cout_validation):
                try:
                    reponse = controleur.valider(b["retenue"], contenu)
                    verdict = True if reponse is True else False if reponse is False else None
                except Exception as ex:
                    cx.noter(DOMAINE, pn, "contrôle par le modèle", 0.0, f"échec : {type(ex).__name__}")
                else:
                    appels, cout = appels + 1, cout + g.cout_validation
                    cx.noter(DOMAINE, pn, "contrôle par le modèle", g.cout_validation, {True: "confirme", False: "contredit", None: "ne tranche pas"}[verdict])
                    if verdict is not None and meme_lecteur:   # le modèle relit sa propre lecture : une seule source, confirmée ou retirée
                        cx.retirer(DOMAINE, pn, ATTRIBUT, "modèle : extraction", origine)
                        if verdict:
                            cx.affirmer(DOMAINE, pn, ATTRIBUT, b["retenue"], "modèle : extraction confirmée", origine)
                    elif verdict is not None:                  # un autre lecteur : son verdict est une source de plus
                        cx.affirmer(DOMAINE, pn, ATTRIBUT, b["retenue"], "modèle : validation", origine, polarite=1 if verdict else -1, nature="verdict")
        b = croire()
    if acceptee(b):
        return bilan(b, "acceptée", "aucune : contrôle par sondage")
    e = mise(b)
    if b["retenue"] == HORS:
        suite = "revue humaine : la classe affirmée n'est pas dans le référentiel des grades"
    elif b["preuves"] and b["probabilite"] >= g.seuil_acceptation:
        suite = "revue humaine : la classe est probable, mais une erreur coûterait plus qu'une revue"
    elif not np.isfinite(e):
        suite = "revue humaine si la pièce compte : enjeu inconnu (poids, volume ou prix d'une classe manquant)"
    elif e < g.cout_revue:
        suite = "aucune : établir la classe rapporterait moins que le coût d'une revue"
    elif piece.get("Interne"):
        suite = "revue humaine (pièce de conception interne : aucune recherche extérieure)"
    elif requete is None:
        suite = "revue humaine, ou renseigner le fabricant et sa référence pour permettre la collecte"
    elif collecteur is None:
        suite = "revue humaine, ou brancher un collecteur de documents"
    else:
        suite = "revue humaine"
    return bilan(b, "à valider" if b["preuves"] else "inconnue", suite)


def fichiers_validations(projet) -> list:
    """Fichiers de validations humaines du projet : <projet>/Acquisition/validations_composition*.csv, par nom.
    Plusieurs personnes peuvent déposer chacune le leur ; lus dans l'ordre des noms, le dernier fait foi."""
    if not projet:
        return []
    d = Path(projet) / "Acquisition"
    return sorted(d.glob("validations_composition*.csv")) if d.is_dir() else []


def importer_validations(cx: mod_cortex.Cortex, table: pd.DataFrame) -> int:
    """Validations humaines : colonnes « PN », « Classe validée » et, facultatives, « Validateur », « Commentaire »,
    « Motif » (« sondage » : pièce acceptée tirée au hasard ; « file » : pièce que la chaîne n'avait pas tranchée)."""
    n = 0
    for _, r in table.iterrows():
        pn, c = ref(r.get("PN")), texte(r.get("Classe validée")).strip()
        if isinstance(pn, str) and c:
            if cx.verite(DOMAINE, pn, ATTRIBUT) != c:
                cx.valider(DOMAINE, pn, ATTRIBUT, c, texte(r.get("Validateur")) or "non précisé", texte(r.get("Commentaire")), texte(r.get("Motif")))
                n += 1
    return n


def traiter(cx: mod_cortex.Cortex, bom: pd.DataFrame, classes, prix: dict, regles=None, reglages: Reglages | None = None,
            masses: dict | None = None, collecteur=None, modele=None, classement: dict | None = None, modele_controle=None,
            cout_traitement=0.0) -> dict:
    """Toute une nomenclature. Renvoie les tables de résultat ; la file de revue est triée par enjeu décroissant."""
    g = reglages or Reglages()
    classes = list(classes)
    doublons = int(bom["PN"].astype(str).duplicated().sum()) if len(bom) else 0
    if doublons:                                                 # un code article répété : la première ligne est gardée
        bom = bom[~bom["PN"].astype(str).duplicated()]
    pns = frozenset(ref(p) for p in bom["PN"]) if len(bom) else frozenset()
    for _, p in bom.iterrows():                                  # tous les sujets d'abord : l'analogie voit toute la nomenclature
        cx.declarer(DOMAINE, str(p["PN"]), texte(p.get("Description")), bool(p.get("Interne")))
    # Premier passage : les preuves gratuites de toutes les pièces. La fiabilité des sources est ensuite figée pour le
    # second passage, de sorte que le résultat ne dépend pas de l'ordre des lignes de la nomenclature.
    for _, p in bom.iterrows():
        preuves_gratuites(cx, p.to_dict(), regles, g, (classement or {}).get(str(p["PN"])))
    fiab_figee = cx.fiabilites(DOMAINE, ATTRIBUT)
    lignes = [resoudre(cx, p.to_dict(), classes, prix, regles, g, (masses or {}).get(str(p["PN"])), collecteur, modele,
                       (classement or {}).get(str(p["PN"])), fiab_figee, modele_controle, cout_traitement, pns, preuves_posees=True)
              for _, p in bom.iterrows()]
    cx.base.commit()
    croyances = {l["PN"]: l.pop("_probabilites") for l in lignes}
    res = pd.DataFrame(lignes, columns=COLS_RESULTAT)
    file_ = res[res["Statut"].isin(["à valider", "inconnue"])].copy()
    file_["Vaut une revue"] = np.where(file_["Enjeu (€/an, borne)"].isna(), "enjeu inconnu", np.where(file_["Enjeu (€/an, borne)"] >= g.cout_revue, "oui", "non"))
    file_ = file_.sort_values("Enjeu (€/an, borne)", ascending=False, na_position="last")
    file_.insert(len(file_.columns), "Classe validée", "")       # à remplir par la personne qui relit, puis à réimporter
    file_.insert(len(file_.columns), "Validateur", "")
    file_.insert(len(file_.columns), "Motif", "file")
    fiab = cx.fiabilites(DOMAINE, ATTRIBUT).drop(columns=["_a", "_b"])
    statuts = res["Statut"].value_counts().to_dict()
    return {"Composition proposée": res, "File de revue": file_.reset_index(drop=True), "Fiabilité des sources": fiab,
            "Journal des acquisitions": cx.journal(DOMAINE), "Croyances": croyances, "Fiabilités utilisées": fiab_figee,
            "Notes": {"pieces": len(res), "statuts": statuts, "appels_au_modele": int(res["Appels au modèle"].sum()),
                      "cout_des_acquisitions_eur": float(res["Coût des acquisitions (€)"].sum()),
                      "pieces_sans_appel_payant": int((res["Coût des acquisitions (€)"] == 0).sum()),
                      "pieces_hors_referentiel": int(res["Classe retenue"].eq(HORS).sum()), "codes_article_repetes_ignores": doublons,
                      "classes": classes, "seuil_acceptation": g.seuil_acceptation, "couts_hypotheses_de_travail": {
                          "collecte": g.cout_collecte, "lecture par le modèle": g.cout_extraction, "contrôle par le modèle": g.cout_validation, "revue humaine": g.cout_revue},
                      "collecteur": "branché" if collecteur is not None else "absent", "modele": "branché" if modele is not None else "absent",
                      "modele_de_controle": "distinct" if modele_controle is not None and modele_controle is not modele else "le même que le modèle de lecture" if modele is not None else "absent",
                      "cortex": mod_cortex.Cortex.bilan(cx, DOMAINE, ATTRIBUT)}}


# --------------------------------------------------------------------------- dans le dossier : après le pipeline principal
DESCRIPTIONS = {"Composition proposée": "Classe matière la plus probable de chaque pièce, probabilité, sources, statut, suite à donner",
                "File de revue": "Pièces à faire valider par une personne, par enjeu décroissant ; à remplir puis à réimporter",
                "Fiabilité des sources": "Ce que valent les sources, appris sur les pièces validées, à côté de l'a priori de départ",
                "Journal des acquisitions": "Chaque collecte et chaque appel au modèle, avec son coût",
                "Valeur de l'information": "Pièces du modèle de ligne dont la classe n'est pas établie : ce que rapporterait de l'établir"}


def executer(ctx, collecteur=None, modele=None, reglages: Reglages | None = None, modele_controle=None) -> dict:
    """Lance la chaîne sur la nomenclature du dossier et dépose ses tables dans artefacts/composition/.

    ctx : contexte rendu par erc.executer() (au moins jusqu'à l'étape « classement » ; jusqu'à « ligne » pour classer
    les pièces par valeur de l'information dans le modèle de ligne). Sans fichier de nomenclature, la liste des pièces
    consommées sert de nomenclature. En démonstration, un collecteur et un modèle FICTIFS sont utilisés et signalés.
    """
    from . import information
    from . import ligne as mod_ligne
    cfg, src = ctx.cfg, ctx.src
    E = "composition"
    g = reglages or Reglages()
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
    modele_ligne = ctx.res.get("ligne", {}).get("Modèle")
    if modele_ligne:                                             # s'y ajoutent les exemplaires contenus dans les FRU scrapées
        for d in mod_ligne._milieu(modele_ligne["frus"]).values():
            for pc, e in (d.get("pieces") or {}).items():
                e = e or {}
                connu = not any(mod_ligne._inconnu(v) for v in (d.get("scrap_an"), e.get("n_par_fru"), e.get("poids_kg")))
                ajout = float(d["scrap_an"]) * float(e["n_par_fru"]) * float(e["poids_kg"]) if connu else np.nan
                masses[str(pc)] = masses.get(str(pc), 0.0) + ajout
    regles = getattr(ctx.params, "regles", None)
    # Le classement antérieur sert de preuve tel qu'il était AVANT le cortex : une classe reprise du cortex (validée ou
    # acceptée) ne doit pas y revenir comme une preuve de plus, sinon cette source ne pourrait jamais avoir tort.
    c0 = src.classification
    if "Classement avant cortex" in c0:
        classement = c0["Classement avant cortex"].dropna().astype(str).to_dict()
    else:
        du_cortex = c0["Niveau de preuve"].astype(str).str.startswith("cortex") if "Niveau de preuve" in c0 else pd.Series(False, index=c0.index)
        classement = c0.loc[~du_cortex, "Catégorie proposée"].dropna().astype(str).to_dict()
    tau = mod_ligne._milieu(modele_ligne["ligne"]).get("cout_traitement_eur_kg") if modele_ligne else None
    tau_connu = tau is not None and np.isfinite(tau)
    vide = {"Composition proposée": pd.DataFrame(columns=COLS_RESULTAT), "File de revue": pd.DataFrame(), "Fiabilité des sources": pd.DataFrame(),
            "Journal des acquisitions": pd.DataFrame(), "Valeur de l'information": pd.DataFrame(columns=information.COLS_CLASSES)}
    if len(classes) < 2:
        tables = dict(vide, Notes={"motif": "moins de deux classes matière connues : il faut le référentiel des grades (classes et prix)"})
    else:
        with mod_cortex.Cortex(cfg.cortex) as cx:
            importees, illisibles = 0, []
            for f in fichiers_validations(cfg.projet):          # un fichier par personne ou par séance de revue
                try:
                    importees += importer_validations(cx, pd.read_csv(f, sep=";", dtype=object, encoding="utf-8-sig"))
                except (OSError, ValueError) as ex:              # un fichier abîmé ne bloque pas les autres
                    illisibles.append(f"{f.name} : {type(ex).__name__}")
            tables = traiter(cx, bom, classes, prix, regles, g, masses, collecteur, modele, classement, modele_controle, tau if tau_connu else 0.0)
            croyances, fiab_utilisees = tables.pop("Croyances"), tables.pop("Fiabilités utilisées")
            tables["Notes"].update({"nomenclature": origine_bom, "validations_importees": importees, "fichiers_de_validations_illisibles": illisibles,
                                    "regles": 0 if regles is None else len(regles), "regles_invalides": regles_invalides(regles),
                                    "fournisseurs_fictifs": fictifs,
                                    "traitement_evite_dans_l_enjeu": "compté" if tau_connu else "non compté : coût de traitement actuel inconnu",
                                    "masse_annuelle_d_une_piece": "exemplaires remplacés en réparation, plus exemplaires contenus dans les FRU scrapées du modèle de ligne"})
            page = ctx.essayer(E, "page de revue", lambda: composition_outil.construire(
                composition_outil.donnees(cx, tables, classes, prix, bom, g, croyances, fiab_utilisees, demo=cfg.demo),
                cfg.artefacts / "composition" / composition_outil.NOM_PAGE), None)
        if page is not None:
            ctx.depot.fichier(E, "Page de revue", page, "Page autonome : valider ou corriger les classes proposées, puis exporter les validations", "outil")
        # Dans le modèle de ligne : ce que rapporterait d'établir la classe des pièces encore à valider
        a_valider = set(tables["File de revue"]["PN"].astype(str)) if len(tables["File de revue"]) else set()
        incertaines = {pc: croyances[pc] for pc in a_valider if pc in croyances}
        tables["Valeur de l'information"] = information.priorites_classes(modele_ligne["ligne"], modele_ligne["frus"], incertaines, prix, g.cout_revue) \
            if modele_ligne and incertaines else pd.DataFrame(columns=information.COLS_CLASSES)
    for nom, t in tables.items():
        if isinstance(t, pd.DataFrame):
            ctx.depot.table(E, nom, t, DESCRIPTIONS.get(nom, ""))
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
    a.add_argument("--controle-url", help="second serveur, pour contrôler les lectures par un autre modèle (défaut : le même modèle)")
    a.add_argument("--controle-nom", default="qwen")
    a.add_argument("--distant", action="store_true", help="accepter un serveur de modèle qui n'est pas sur ce poste")
    a.add_argument("--fabricant-interne", action="append", default=[], help="nom de l'entreprise ou d'un de ses sites, jamais recherché (répétable)")
    o = a.parse_args(argv)
    cfg = charger(dossier=o.dossier, demo=True if o.demo else None)
    if o.bom:
        cfg.bom = o.bom
    ctx = pipeline("ligne", cfg=cfg, silencieux=True)
    modele = ModeleLocal(o.modele_url, o.modele_nom, distant=o.distant) if o.modele_url else None
    controle = ModeleLocal(o.controle_url, o.controle_nom, distant=o.distant) if o.controle_url else None
    t = executer(ctx, modele=modele, reglages=Reglages(fabricants_internes=tuple(o.fabricant_interne)), modele_controle=controle)
    n = t["Notes"]
    print(f"{n.get('pieces', 0)} pièces | statuts : {n.get('statuts', {})} | appels au modèle : {n.get('appels_au_modele', 0)} | "
          f"sans appel payant : {n.get('pieces_sans_appel_payant', 0)}")
    print("Tables et page de revue : artefacts/composition/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
