"""Cortex : base de connaissance à sources faillibles, réutilisable dans n'importe quel domaine.

Idée. Une connaissance n'est jamais stockée comme un fait, mais comme des AFFIRMATIONS de sources (« la source S,
d'origine O, dit que le sujet X a la valeur V pour l'attribut A »). Une VALIDATION par une personne est la seule
vérité. De ces deux tables se déduisent :

  la fiabilité de chaque type de source : sur les sujets validés, combien de fois ce type de source a eu raison
      (loi Bêta ; un a priori faible, déclaré, sert tant qu'il n'y a pas de validation) ;
  la croyance sur un sujet non validé : probabilité de chaque valeur possible, par fusion des affirmations selon la
      fiabilité de leur source (docs/Formal_framework.md, section 8.2).

Deux sortes d'affirmation, deux vraisemblances :
  « c'est V »            la source nomme une valeur parmi les C possibles. Fiable à r : elle dit la vraie valeur avec
                         la probabilité r, et sinon une des C − 1 autres, au hasard.
  verdict oui / non      la source répond à la question « est-ce V ? ». Fiable à r : sa réponse est juste avec la
                         probabilité r, quelle que soit la vraie valeur. Un « ce n'est pas V » est un verdict « non ».
Les affirmations d'un même type de source partagent une fiabilité inconnue : la fusion intègre sur sa loi Bêta au lieu
d'y brancher sa moyenne, de sorte que trois documents d'accord ne valent pas trois preuves indépendantes.

Règles qui tiennent le système honnête.
  1. Un modèle de langage est une source comme une autre, avec sa fiabilité apprise ; il n'est jamais la vérité.
  2. Dix pages qui recopient la même fiche comptent pour une : une affirmation par (type de source, origine). Et deux
     lecteurs du même texte (une règle et un modèle qui lisent la même description) ne font pas deux preuves quand ils
     sont d'accord : les affirmations qui partagent une même BASE et disent la même valeur comptent pour une seule, la
     plus fiable. S'ils se contredisent, les deux comptent.
  3. Sans preuve, pas de valeur : le sujet est « inconnu ».
  4. Une valeur affirmée hors de la liste de référence va dans la case « hors référentiel » : elle n'est ni perdue ni
     prise pour une valeur de la liste.
  5. La fiabilité se mesure sur des validations qui ne sont pas choisies parce que les sources se contredisent. Une
     validation porte son motif : « sondage » (sujet accepté tiré au hasard), « file » (sujet que le système n'a pas
     su trancher), « choix » (sujet que la personne a choisi de corriger), ou rien (validation faite sans regarder ce
     que disent les sources). « Sondage » et « file » ne renseignent que leur strate, pondérée par sa taille ; « choix »
     fixe la valeur du sujet mais ne juge pas les sources. Sans cela, valider seulement les cas douteux ferait croire
     que toutes les sources sont mauvaises.

Le domaine (« composition », ou tout autre) n'est qu'une étiquette : la même base sert à d'autres équipes.
Stockage : un fichier SQLite (bibliothèque standard), lisible par n'importe quel outil, sans serveur. Le mode de
journalisation par défaut est gardé : le mode WAL ne convient pas à un dossier synchronisé ou partagé en réseau. Chaque
action payante est écrite aussitôt, pour ne pas la payer deux fois si le traitement s'arrête.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Fiabilité a priori par type de source : HYPOTHÈSES DE TRAVAIL, de poids faible (FORCE_A_PRIORI observations
# équivalentes), remplacées par les validations dès qu'il y en a. Elles ordonnent les sources par bon sens ;
# aucune n'est mesurée. La table « Fiabilité des sources » montre toujours l'a priori à côté de ce qui est observé.
A_PRIORI_SOURCES = {
    "déclaration fabricant": 0.95,          # classe donnée par une déclaration matière structurée du fabricant
    "document": 0.80,                       # classe donnée explicitement par un document retrouvé
    "règle": 0.75,                          # règle sur la description
    "modèle : extraction confirmée": 0.75,  # lecture d'un document par un modèle, relue et confirmée par ce même modèle
    "modèle : validation": 0.70,            # verdict oui / non d'un second modèle sur une classe proposée
    "analogie": 0.65,                       # même classe qu'une pièce validée de description proche
    "modèle : extraction": 0.60,            # lecture d'un document par un modèle de langage
}
FIABILITE_PAR_DEFAUT = 0.60
FORCE_A_PRIORI = 4.0
HORS = "hors référentiel"
VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS sujet(domaine TEXT, sujet TEXT, description TEXT, interne INTEGER DEFAULT 0, maj TEXT,
    PRIMARY KEY(domaine, sujet));
CREATE TABLE IF NOT EXISTS affirmation(id INTEGER PRIMARY KEY, domaine TEXT, sujet TEXT, attribut TEXT, valeur TEXT,
    polarite INTEGER DEFAULT 1, type_source TEXT, origine TEXT, detail TEXT, cree_le TEXT, nature TEXT DEFAULT 'affirmation',
    base TEXT DEFAULT '', UNIQUE(domaine, sujet, attribut, type_source, origine));
CREATE TABLE IF NOT EXISTS validation(id INTEGER PRIMARY KEY, domaine TEXT, sujet TEXT, attribut TEXT, valeur TEXT,
    validateur TEXT, commentaire TEXT, cree_le TEXT, motif TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY, cree_le TEXT, domaine TEXT, sujet TEXT, action TEXT,
    cout REAL, resultat TEXT);
CREATE TABLE IF NOT EXISTS conclusion(domaine TEXT, sujet TEXT, attribut TEXT, valeur TEXT, probabilite REAL, statut TEXT, maj TEXT,
    PRIMARY KEY(domaine, sujet, attribut));
CREATE INDEX IF NOT EXISTS aff_sujet ON affirmation(domaine, attribut, sujet);
CREATE INDEX IF NOT EXISTS val_sujet ON validation(domaine, attribut, sujet);
CREATE INDEX IF NOT EXISTS jou_sujet ON journal(domaine, sujet, action);
"""
# Colonnes ajoutées depuis la première version : un fichier plus ancien les reçoit à l'ouverture.
COLONNES_AJOUTEES = {"sujet": {"interne": "INTEGER DEFAULT 0"},
                     "affirmation": {"polarite": "INTEGER DEFAULT 1", "nature": "TEXT DEFAULT 'affirmation'", "base": "TEXT DEFAULT ''"},
                     "validation": {"motif": "TEXT DEFAULT ''"}}
COLONNES_ATTENDUES = {"sujet": {"domaine", "sujet", "description", "interne", "maj"},
                      "affirmation": {"id", "domaine", "sujet", "attribut", "valeur", "polarite", "type_source", "origine", "detail", "cree_le", "nature", "base"},
                      "validation": {"id", "domaine", "sujet", "attribut", "valeur", "validateur", "commentaire", "cree_le", "motif"},
                      "journal": {"id", "cree_le", "domaine", "sujet", "action", "cout", "resultat"}}
MOTIFS_STRATE = {"sondage": "acceptée", "file": "file", "choix": "exclue"}
STATUTS_FILE = ("à valider", "inconnue")     # conclusions des sujets que la chaîne envoie à une personne ; « laissée » n'en est pas


def _maintenant() -> str:
    return datetime.now().isoformat(timespec="seconds")


def texte(v) -> str:
    """Texte d'une cellule ; vide pour une cellule absente (None, NaN), qui ne doit jamais devenir le mot « nan »."""
    if v is None:
        return ""
    if not isinstance(v, str):
        try:
            if pd.isna(v):
                return ""
        except (TypeError, ValueError):
            pass
    return str(v)


def plier(t) -> str:
    """Minuscules sans accent ni ligature, pour comparer deux textes."""
    t = texte(t).lower().replace("œ", "oe").replace("æ", "ae").replace("ß", "ss")
    return "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))


def mots(t) -> set:
    """Mots d'un texte pour comparer deux descriptions : minuscules, sans accent, au moins deux caractères (un seul
    pour une écriture sans espaces)."""
    return {m for m in re.findall(r"\w+", plier(t)) if len(m) >= 2 or not m.isascii()}


def ressemblance(a, b) -> float:
    """Part de mots communs à deux descriptions (indice de Jaccard), entre 0 et 1."""
    x, y = mots(a), mots(b)
    return len(x & y) / len(x | y) if x and y else 0.0


def _betaln(x: float, y: float) -> float:
    return math.lgamma(x) + math.lgamma(y) - math.lgamma(x + y)


class Cortex:
    def __init__(self, chemin):
        self.chemin = Path(chemin) if str(chemin) != ":memory:" else chemin
        if isinstance(self.chemin, Path):
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self.base = sqlite3.connect(str(chemin), timeout=30)
        self._ouvrir()
        self._valides = {}                                    # (domaine, attribut) → [(sujet, mots de la description, valeur)]

    def _ouvrir(self) -> None:
        version = int(self.base.execute("PRAGMA user_version").fetchone()[0])
        if version > VERSION:
            raise ValueError(f"Cortex {self.chemin} : fichier écrit par une version plus récente du dossier (schéma {version}, attendu {VERSION}).")
        existantes = {r[0] for r in self.base.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, ajouts in COLONNES_AJOUTEES.items():           # fichier d'une version antérieure : colonnes manquantes ajoutées
            if table in existantes:
                presentes = {r[1] for r in self.base.execute(f"PRAGMA table_info({table})")}
                for colonne, definition in ajouts.items():
                    if colonne not in presentes:
                        self.base.execute(f"ALTER TABLE {table} ADD COLUMN {colonne} {definition}")
        for table, attendues in COLONNES_ATTENDUES.items():      # une table du même nom mais d'une autre forme : pas un cortex
            if table in existantes:
                manquantes = attendues - {r[1] for r in self.base.execute(f"PRAGMA table_info({table})")}
                if manquantes:
                    raise ValueError(f"Cortex {self.chemin} : la table « {table} » n'a pas les colonnes {sorted(manquantes)}. "
                                     "Ce fichier n'est pas un cortex de ce dossier ; le renommer pour en créer un nouveau.")
        self.base.executescript(SCHEMA)
        self.base.execute(f"PRAGMA user_version = {VERSION}")
        self.base.commit()

    def fermer(self) -> None:
        self.base.commit()
        self.base.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fermer()

    # ------------------------------------------------------------------ écriture
    def declarer(self, domaine: str, sujet: str, description: str = "", interne: bool = False) -> None:
        """Enregistre un sujet et sa description. `interne` : jamais envoyé à l'extérieur (conception maison)."""
        description, interne = texte(description), int(bool(interne))
        deja = self.base.execute("SELECT description, interne FROM sujet WHERE domaine=? AND sujet=?", (domaine, str(sujet))).fetchone()
        if deja is not None and deja[0] == description and deja[1] == interne:
            return                                            # rien n'a changé : pas d'écriture, les voisins en mémoire restent valables
        self.base.execute("INSERT INTO sujet(domaine, sujet, description, interne, maj) VALUES(?,?,?,?,?) "
                          "ON CONFLICT(domaine, sujet) DO UPDATE SET description=excluded.description, interne=excluded.interne, maj=excluded.maj",
                          (domaine, str(sujet), description, interne, _maintenant()))
        self._valides.clear()

    def affirmer(self, domaine: str, sujet: str, attribut: str, valeur: str, type_source: str, origine: str,
                 detail=None, polarite: int = 1, nature: str = "affirmation", base: str = "") -> None:
        """Une source dit quelque chose du sujet.

        nature « affirmation » : la source nomme la valeur (polarite = 1) ou l'écarte (polarite = −1) ;
        nature « verdict »     : la source répond oui (polarite = 1) ou non (polarite = −1) à « est-ce cette valeur ? ».
        base : le texte sur lequel la source s'appuie, quand d'autres sources lisent le même (par exemple « description »).
        Une même origine ne compte qu'une fois par type de source : sa dernière affirmation remplace la précédente."""
        if not texte(valeur).strip():
            return
        if nature not in ("affirmation", "verdict"):
            raise ValueError("nature : « affirmation » ou « verdict »")
        self.base.execute("INSERT INTO affirmation(domaine, sujet, attribut, valeur, polarite, nature, base, type_source, origine, detail, cree_le) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(domaine, sujet, attribut, type_source, origine) DO UPDATE SET "
                          "valeur=excluded.valeur, polarite=excluded.polarite, nature=excluded.nature, base=excluded.base, detail=excluded.detail, "
                          "cree_le=excluded.cree_le",
                          (domaine, str(sujet), attribut, texte(valeur).strip(), 1 if polarite >= 0 else -1, nature, texte(base), type_source, str(origine),
                           json.dumps(detail, ensure_ascii=False) if detail is not None else None, _maintenant()))

    def retirer(self, domaine: str, sujet: str, attribut: str, type_source: str, origine: str | None = None) -> int:
        """Retire ce qu'une source disait du sujet (toutes ses origines si `origine` n'est pas donnée) : une règle
        modifiée ou une lecture contredite ne doit pas laisser de trace qui compte encore. Renvoie le nombre retiré."""
        q, p = "DELETE FROM affirmation WHERE domaine=? AND sujet=? AND attribut=? AND type_source=?", [domaine, str(sujet), attribut, type_source]
        if origine is not None:
            q, p = q + " AND origine=?", p + [str(origine)]
        return self.base.execute(q, p).rowcount

    def valider(self, domaine: str, sujet: str, attribut: str, valeur: str, validateur: str, commentaire: str = "", motif: str = "") -> None:
        """Vérité de terrain : une personne fixe la valeur. La dernière validation fait foi.
        motif : « sondage » (sujet accepté tiré au hasard), « file » (sujet que le système n'a pas su trancher),
        « choix » (sujet choisi par la personne), ou vide (validation indépendante de ce que disent les sources)."""
        self.base.execute("INSERT INTO validation(domaine, sujet, attribut, valeur, validateur, commentaire, motif, cree_le) VALUES(?,?,?,?,?,?,?,?)",
                          (domaine, str(sujet), attribut, texte(valeur).strip(), str(validateur), texte(commentaire), plier(motif).strip(), _maintenant()))
        self._valides.clear()
        self.base.commit()

    def noter(self, domaine: str, sujet: str, action: str, cout: float = 0.0, resultat: str = "") -> None:
        """Journal des acquisitions : chaque recherche, chaque appel à un modèle, avec son coût. Écrit aussitôt sur le
        disque : une action payée reste connue même si le traitement s'arrête juste après."""
        self.base.execute("INSERT INTO journal(cree_le, domaine, sujet, action, cout, resultat) VALUES(?,?,?,?,?,?)",
                          (_maintenant(), domaine, str(sujet), action, float(cout or 0.0), str(resultat or "")))
        self.base.commit()

    def conclure(self, domaine: str, sujet: str, attribut: str, valeur, probabilite, statut: str) -> None:
        """Ce que le système a conclu pour ce sujet à son dernier passage : valeur retenue, probabilité, statut."""
        p = None if probabilite is None or not np.isfinite(probabilite) else float(probabilite)
        self.base.execute("INSERT INTO conclusion(domaine, sujet, attribut, valeur, probabilite, statut, maj) VALUES(?,?,?,?,?,?,?) "
                          "ON CONFLICT(domaine, sujet, attribut) DO UPDATE SET valeur=excluded.valeur, probabilite=excluded.probabilite, "
                          "statut=excluded.statut, maj=excluded.maj", (domaine, str(sujet), attribut, valeur, p, statut, _maintenant()))

    # ------------------------------------------------------------------ lecture
    def _table(self, requete: str, parametres=()) -> pd.DataFrame:
        c = self.base.execute(requete, parametres)
        return pd.DataFrame(c.fetchall(), columns=[d[0] for d in c.description])

    def verites(self, domaine: str, attribut: str) -> dict:
        """{sujet: valeur validée} ; la dernière validation de chaque sujet."""
        t = self._table("SELECT sujet, valeur FROM validation WHERE domaine=? AND attribut=? ORDER BY id", (domaine, attribut))
        return dict(zip(t["sujet"], t["valeur"]))

    def motifs(self, domaine: str, attribut: str) -> dict:
        """{sujet: motif de sa dernière validation}."""
        t = self._table("SELECT sujet, motif FROM validation WHERE domaine=? AND attribut=? ORDER BY id", (domaine, attribut))
        return dict(zip(t["sujet"], t["motif"].fillna("")))

    def verite(self, domaine: str, sujet: str, attribut: str):
        r = self.base.execute("SELECT valeur FROM validation WHERE domaine=? AND attribut=? AND sujet=? ORDER BY id DESC LIMIT 1",
                              (domaine, attribut, str(sujet))).fetchone()
        return r[0] if r else None

    def affirmations(self, domaine: str, attribut: str, sujet: str | None = None) -> pd.DataFrame:
        if sujet is None:
            return self._table("SELECT * FROM affirmation WHERE domaine=? AND attribut=? ORDER BY id", (domaine, attribut))
        return self._table("SELECT * FROM affirmation WHERE domaine=? AND attribut=? AND sujet=? ORDER BY id", (domaine, attribut, str(sujet)))

    def conclusions(self, domaine: str, attribut: str) -> pd.DataFrame:
        return self._table("SELECT sujet, valeur, probabilite, statut, maj FROM conclusion WHERE domaine=? AND attribut=? ORDER BY sujet", (domaine, attribut))

    def actions(self, domaine: str, sujet: str, action: str) -> list:
        """Résultats déjà notés au journal pour cette action sur ce sujet, du plus ancien au plus récent.
        Sert à ne pas payer deux fois la même recherche."""
        return [r[0] for r in self.base.execute("SELECT resultat FROM journal WHERE domaine=? AND sujet=? AND action=? ORDER BY id",
                                                (domaine, str(sujet), action))]

    def depense(self, domaine: str, sujet: str) -> float:
        """Coût cumulé des acquisitions déjà faites pour ce sujet, tous passages confondus."""
        return float(self.base.execute("SELECT COALESCE(SUM(cout), 0) FROM journal WHERE domaine=? AND sujet=?", (domaine, str(sujet))).fetchone()[0])

    def fiabilites(self, domaine: str, attribut: str) -> pd.DataFrame:
        """Fiabilité de chaque type de source, apprise sur les sujets validés.

        Une affirmation est juste si elle donne la valeur validée ; un verdict « non » ou une négation est juste s'il
        écarte une valeur qui n'est pas la valeur validée.

        Les validations sans motif (faites indépendamment de ce que disent les sources) mettent à jour l'a priori :
        Bêta(a priori × force + justes, (1 − a priori) × force + fausses). Les autres ne renseignent que leur strate :
          « file »     sujets que la chaîne envoie à une personne (conclusion « à valider ») : ce sont ceux où les sources
                       se contredisent, on y trouve plus d'erreurs qu'ailleurs ;
          « sondage »  sujets tirés au hasard parmi ceux que la chaîne ne montre à personne (acceptés, ou laissés faute
                       d'enjeu, conclusion « laissée »).
        La fiabilité retenue est la moyenne des deux strates, pondérée par le nombre d'affirmations de ce type qui restent
        à juger dans chacune. Sans sujet restant, toutes les validations sont réunies. Les validations « choix » ne sont
        pas comptées : ni tirées au hasard ni exhaustives, elles ne disent rien de fiable sur les sources.
        """
        v, motif = self.verites(domaine, attribut), self.motifs(domaine, attribut)
        a = self.affirmations(domaine, attribut)
        c = self.conclusions(domaine, attribut)
        en_file = set(c.loc[c["statut"].isin(STATUTS_FILE), "sujet"]) - set(v)
        types = sorted(set(A_PRIORI_SOURCES) | set(a["type_source"]))
        lignes = []
        for t in types:
            g = a[a["type_source"].eq(t)]
            juge = g[g["sujet"].isin([sj for sj in v if MOTIFS_STRATE.get(motif.get(sj, ""), "") != "exclue"])]
            juste = np.array([(r["valeur"] == v[r["sujet"]]) == (r["polarite"] >= 0) for _, r in juge.iterrows()], dtype=bool)
            strate = np.array([MOTIFS_STRATE.get(motif.get(s, ""), "") for s in juge["sujet"]], dtype=object)
            compte = lambda s: (int(juste[strate == s].sum()), int((strate == s).sum())) if len(juge) else (0, 0)
            (k0, n0), (ks, ns), (kf, nf) = compte(""), compte("acceptée"), compte("file")
            m0 = A_PRIORI_SOURCES.get(t, FIABILITE_PAR_DEFAUT)
            al, be = m0 * FORCE_A_PRIORI + k0, (1 - m0) * FORCE_A_PRIORI + (n0 - k0)
            reste = g[~g["sujet"].isin(list(v))]
            n_file = int(reste["sujet"].isin(list(en_file)).sum())
            n_acc = len(reste) - n_file                         # acceptés, laissés, ou pas encore passés par la chaîne
            if n_acc + n_file:
                m_acc, m_file = (al + ks) / (al + be + ns), (al + kf) / (al + be + nf)
                r = (n_acc * m_acc + n_file * m_file) / (n_acc + n_file)
            else:
                r = (al + ks + kf) / (al + be + ns + nf)
            force = al + be + ns + nf
            lignes.append({"Type de source": t, "A priori (hypothèse)": m0, "Affirmations vérifiées": len(juge), "Justes": int(juste.sum()),
                           "Fausses": len(juge) - int(juste.sum()), "dont par sondage": ns, "dont dans la file": nf, "Fiabilité": r,
                           "Poids des observations": len(juge) / (len(juge) + FORCE_A_PRIORI), "_a": r * force, "_b": (1 - r) * force})
        return pd.DataFrame(lignes)

    def croyance(self, domaine: str, sujet: str, attribut: str, classes, a_priori: dict | None = None, fiabilites: pd.DataFrame | None = None,
                 en_plus=None, sans=None) -> dict:
        """Probabilité de chaque valeur possible pour un sujet.

        classes   : valeurs de référence (au moins une). La case « hors référentiel » leur est toujours ajoutée : elle
                    reçoit toute valeur affirmée hors de la liste, et le nombre de valeurs possibles est le même pour
                    tous les sujets.
        a_priori  : {valeur: poids} avant toute preuve ; uniforme par défaut.
        en_plus   : affirmations supposées, pour savoir ce que deviendrait la croyance (dictionnaires « type_source »,
                    « valeur », et au besoin « polarite », « nature ») ; rien n'est écrit.
        sans      : affirmations à ignorer dans ce calcul, [(type de source, origine)].
        Renvoie {"probabilites", "retenue", "probabilite", "preuves", "validee", "sources"}. Sans preuve : « retenue » vaut None.
        """
        sujet = str(sujet)
        reference = list(dict.fromkeys(map(str, classes)))
        if not reference:
            raise ValueError("croyance : il faut au moins une valeur de référence")
        vraie = self.verite(domaine, sujet, attribut)
        a = self.affirmations(domaine, attribut, sujet)
        valeurs = reference + [HORS]
        if vraie is not None:
            valeurs = valeurs if str(vraie) in valeurs else valeurs + [str(vraie)]
            return {"probabilites": {c: float(c == str(vraie)) for c in valeurs}, "retenue": str(vraie), "probabilite": 1.0,
                    "preuves": len(a), "validee": True, "sources": ["validation humaine"]}
        ignorees = {(str(t), str(o)) for t, o in (sans or [])}
        preuves = [{"type_source": r["type_source"], "valeur": r["valeur"], "polarite": r["polarite"], "nature": r["nature"] or "affirmation",
                    "base": r["base"] or ""} for _, r in a.iterrows() if (str(r["type_source"]), str(r["origine"])) not in ignorees]
        n_stockees = len(preuves)
        sources = sorted({e["type_source"] for e in preuves})
        preuves += [dict({"polarite": 1, "nature": "affirmation", "base": ""}, **e) for e in (en_plus or [])]
        C = len(valeurs)
        p0 = np.array([float((a_priori or {}).get(c, 0.0)) for c in valeurs]) if a_priori else np.ones(C)
        p0 = p0 + 1e-12 if p0.sum() > 0 else np.ones(C)
        logp = np.log(p0 / p0.sum())
        f = fiabilites if fiabilites is not None else self.fiabilites(domaine, attribut)
        beta = {t: (float(x), float(y)) for t, x, y in zip(f["Type de source"], f["_a"], f["_b"])} if len(f) else {}
        moyenne = lambda t: (lambda x: x[0] / (x[0] + x[1]))(beta.get(t, (A_PRIORI_SOURCES.get(t, FIABILITE_PAR_DEFAUT), 1 - A_PRIORI_SOURCES.get(t, FIABILITE_PAR_DEFAUT))))
        # Deux lecteurs du même texte qui disent la même valeur comptent pour un : on garde le plus fiable.
        retenues, vus = [], {}
        for e in sorted(preuves, key=lambda e: (-moyenne(e["type_source"]), str(e["type_source"]))):
            cle = (e["base"], str(e["valeur"])) if e["base"] and e["nature"] == "affirmation" and e["polarite"] >= 0 else None
            if cle is not None and vus.get(cle, e["type_source"]) != e["type_source"]:
                continue                                        # un autre lecteur du même texte, plus fiable, a déjà dit cette valeur
            if cle is not None:
                vus[cle] = e["type_source"]
            retenues.append(e)
        par_type = {}
        for e in retenues:
            par_type.setdefault(e["type_source"], []).append(e)
        for t, liste in par_type.items():
            m0 = A_PRIORI_SOURCES.get(t, FIABILITE_PAR_DEFAUT)
            al, be = beta.get(t, (m0 * FORCE_A_PRIORI, (1 - m0) * FORCE_A_PRIORI))
            juste, faux, repartis = np.zeros(C), np.zeros(C), np.zeros(C)     # si la vraie valeur est c : affirmations justes, fausses
            for e in liste:
                dit = np.array([c == (str(e["valeur"]) if str(e["valeur"]) in valeurs else HORS) for c in valeurs])
                if e["nature"] == "affirmation" and e["polarite"] >= 0:      # « c'est V » : une erreur tombe sur l'une des C − 1 autres valeurs
                    juste, faux, repartis = juste + dit, faux + ~dit, repartis + ~dit
                else:                                                       # verdict oui / non, ou négation : juste ou faux, sans répartition
                    bon = dit == (e["polarite"] >= 0)
                    juste, faux = juste + bon, faux + ~bon
            # vraisemblance intégrée sur la fiabilité inconnue du type de source, de loi Bêta(al, be)
            logp += np.array([_betaln(al + j, be + x) for j, x in zip(juste, faux)]) - _betaln(al, be) - repartis * math.log(max(C - 1, 1))
        p = np.exp(logp - logp.max())
        p = p / p.sum()
        i = int(np.argmax(p))
        return {"probabilites": dict(zip(valeurs, map(float, p))), "retenue": valeurs[i] if preuves else None,
                "probabilite": float(p[i]) if preuves else float("nan"), "preuves": n_stockees, "validee": False,
                "sources": sources}

    def voisins(self, domaine: str, attribut: str, description: str, k: int = 3, seuil: float = 0.5, sauf: str | None = None) -> list:
        """Sujets VALIDÉS dont la description ressemble le plus : [(sujet, ressemblance, valeur validée)]."""
        cle = (domaine, attribut)
        if cle not in self._valides:                          # descriptions des sujets validés, découpées en mots une seule fois
            v = self.verites(domaine, attribut)
            t = self._table("SELECT sujet, description FROM sujet WHERE domaine=?", (domaine,))
            self._valides[cle] = [(r["sujet"], mots(r["description"]), v[r["sujet"]]) for _, r in t.iterrows() if r["sujet"] in v]
        x = mots(description)
        if not x:
            return []
        out = [(sj, len(x & y) / len(x | y), val) for sj, y, val in self._valides[cle] if y and sj != sauf]
        return sorted([o for o in out if o[1] >= seuil], key=lambda o: (-o[1], str(o[0])))[:k]

    def journal(self, domaine: str | None = None) -> pd.DataFrame:
        if domaine is None:
            return self._table("SELECT cree_le, domaine, sujet, action, cout, resultat FROM journal ORDER BY id")
        return self._table("SELECT cree_le, domaine, sujet, action, cout, resultat FROM journal WHERE domaine=? ORDER BY id", (domaine,))

    def bilan(self, domaine: str, attribut: str) -> dict:
        """Ce que contient la base pour un domaine : sujets, affirmations, validations, coût cumulé des acquisitions."""
        n = lambda q, *p: int(self.base.execute(q, p).fetchone()[0] or 0)
        return {"sujets": n("SELECT COUNT(*) FROM sujet WHERE domaine=?", domaine),
                "affirmations": n("SELECT COUNT(*) FROM affirmation WHERE domaine=? AND attribut=?", domaine, attribut),
                "sujets validés": len(self.verites(domaine, attribut)),
                "coût cumulé des acquisitions": float(self.base.execute("SELECT COALESCE(SUM(cout), 0) FROM journal WHERE domaine=?", (domaine,)).fetchone()[0])}
