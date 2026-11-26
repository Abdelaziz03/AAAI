"""Cortex : base de connaissance à sources faillibles, réutilisable dans n'importe quel domaine.

Idée. Une connaissance n'est jamais stockée comme un fait, mais comme des AFFIRMATIONS de sources (« la source S,
d'origine O, dit que le sujet X a la valeur V pour l'attribut A »). Une VALIDATION humaine ou une déclaration
officielle est la seule vérité. De ces deux tables se déduisent :

  la fiabilité de chaque type de source, apprise : sur les sujets validés, combien de fois ce type de source a eu
      raison (loi Bêta ; un a priori faible, déclaré, sert tant qu'il n'y a pas de validation) ;
  la croyance sur un sujet non validé : probabilité de chaque valeur possible, par fusion des affirmations pondérées
      par la fiabilité de leur source (modèle à classes latentes de Dawid et Skene, cas « une pièce » :
      P(valeur = c | preuves) ∝ a priori(c) × Π [ r si la source dit c, (1 − r) / (C − 1) sinon ]).

Trois règles tiennent le système honnête.
  1. Un modèle de langage est une source comme une autre, avec sa fiabilité apprise ; il n'est jamais la vérité.
  2. Dix pages qui recopient la même fiche comptent pour une : une affirmation par (type de source, origine).
  3. Sans preuve, pas de valeur : la croyance reste l'a priori et le sujet est « inconnu ».

Le domaine (« composition », ou tout autre) n'est qu'une étiquette : la même base sert à d'autres équipes.
Stockage : un fichier SQLite (bibliothèque standard), lisible par n'importe quel outil, sans serveur.
"""
from __future__ import annotations

import json
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
    "déclaration fabricant": 0.95,       # déclaration matière du fabricant (IEC 62474, IPC-1752A) ou fiche officielle
    "document": 0.80,                    # document retrouvé, lu par des règles
    "règle": 0.75,                       # règle sur la description
    "modèle : validation": 0.70,         # second modèle qui confirme ou infirme une extraction
    "analogie": 0.65,                    # même classe qu'une pièce validée de description proche
    "modèle : extraction": 0.60,         # modèle de langage qui lit un document
}
FIABILITE_PAR_DEFAUT = 0.60
FORCE_A_PRIORI = 4.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS sujet(domaine TEXT, sujet TEXT, description TEXT, interne INTEGER DEFAULT 0, maj TEXT,
    PRIMARY KEY(domaine, sujet));
CREATE TABLE IF NOT EXISTS affirmation(id INTEGER PRIMARY KEY, domaine TEXT, sujet TEXT, attribut TEXT, valeur TEXT,
    polarite INTEGER DEFAULT 1, type_source TEXT, origine TEXT, detail TEXT, cree_le TEXT,
    UNIQUE(domaine, sujet, attribut, type_source, origine));
CREATE TABLE IF NOT EXISTS validation(id INTEGER PRIMARY KEY, domaine TEXT, sujet TEXT, attribut TEXT, valeur TEXT,
    validateur TEXT, commentaire TEXT, cree_le TEXT);
CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY, cree_le TEXT, domaine TEXT, sujet TEXT, action TEXT,
    cout REAL, resultat TEXT);
CREATE INDEX IF NOT EXISTS aff_sujet ON affirmation(domaine, attribut, sujet);
CREATE INDEX IF NOT EXISTS val_sujet ON validation(domaine, attribut, sujet);
"""


def _maintenant() -> str:
    return datetime.now().isoformat(timespec="seconds")


def mots(texte) -> set:
    """Mots d'un texte pour comparer deux descriptions : minuscules, sans accent, au moins deux caractères."""
    t = "".join(c for c in unicodedata.normalize("NFKD", str(texte or "").lower()) if not unicodedata.combining(c))
    return {m for m in re.findall(r"[a-z0-9]+", t) if len(m) >= 2}


def ressemblance(a, b) -> float:
    """Part de mots communs à deux descriptions (indice de Jaccard), entre 0 et 1."""
    x, y = mots(a), mots(b)
    return len(x & y) / len(x | y) if x and y else 0.0


class Cortex:
    def __init__(self, chemin):
        self.chemin = Path(chemin) if str(chemin) != ":memory:" else chemin
        if isinstance(self.chemin, Path):
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self.base = sqlite3.connect(str(chemin))
        self.base.executescript(SCHEMA)
        self.base.commit()
        self._valides = {}                                    # (domaine, attribut) → [(sujet, mots de la description, valeur)]

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
        description, interne = str(description or ""), int(bool(interne))
        deja = self.base.execute("SELECT description, interne FROM sujet WHERE domaine=? AND sujet=?", (domaine, str(sujet))).fetchone()
        if deja is not None and deja[0] == description and deja[1] == interne:
            return                                            # rien n'a changé : pas d'écriture, les voisins en mémoire restent valables
        self.base.execute("INSERT INTO sujet(domaine, sujet, description, interne, maj) VALUES(?,?,?,?,?) "
                          "ON CONFLICT(domaine, sujet) DO UPDATE SET description=excluded.description, interne=excluded.interne, maj=excluded.maj",
                          (domaine, str(sujet), description, interne, _maintenant()))
        self._valides.clear()

    def affirmer(self, domaine: str, sujet: str, attribut: str, valeur: str, type_source: str, origine: str,
                 detail=None, polarite: int = 1) -> None:
        """Une source affirme (polarite = 1) ou nie (polarite = −1) que le sujet a cette valeur.
        Une même origine ne compte qu'une fois par type de source : sa dernière affirmation remplace la précédente."""
        if valeur is None or str(valeur).strip() == "":
            return
        self.base.execute("INSERT INTO affirmation(domaine, sujet, attribut, valeur, polarite, type_source, origine, detail, cree_le) "
                          "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(domaine, sujet, attribut, type_source, origine) DO UPDATE SET "
                          "valeur=excluded.valeur, polarite=excluded.polarite, detail=excluded.detail, cree_le=excluded.cree_le",
                          (domaine, str(sujet), attribut, str(valeur), 1 if polarite >= 0 else -1, type_source, str(origine),
                           json.dumps(detail, ensure_ascii=False) if detail is not None else None, _maintenant()))

    def valider(self, domaine: str, sujet: str, attribut: str, valeur: str, validateur: str, commentaire: str = "") -> None:
        """Vérité de terrain : une personne (ou une déclaration officielle) fixe la valeur. La dernière validation fait foi."""
        self.base.execute("INSERT INTO validation(domaine, sujet, attribut, valeur, validateur, commentaire, cree_le) VALUES(?,?,?,?,?,?,?)",
                          (domaine, str(sujet), attribut, str(valeur), str(validateur), str(commentaire or ""), _maintenant()))
        self._valides.clear()

    def noter(self, domaine: str, sujet: str, action: str, cout: float = 0.0, resultat: str = "") -> None:
        """Journal des acquisitions : chaque recherche, chaque appel à un modèle, avec son coût."""
        self.base.execute("INSERT INTO journal(cree_le, domaine, sujet, action, cout, resultat) VALUES(?,?,?,?,?,?)",
                          (_maintenant(), domaine, str(sujet), action, float(cout or 0.0), str(resultat or "")))

    # ------------------------------------------------------------------ lecture
    def _table(self, requete: str, parametres=()) -> pd.DataFrame:
        c = self.base.execute(requete, parametres)
        return pd.DataFrame(c.fetchall(), columns=[d[0] for d in c.description])

    def verites(self, domaine: str, attribut: str) -> dict:
        """{sujet: valeur validée} ; la dernière validation de chaque sujet."""
        t = self._table("SELECT sujet, valeur FROM validation WHERE domaine=? AND attribut=? ORDER BY id", (domaine, attribut))
        return dict(zip(t["sujet"], t["valeur"]))

    def verite(self, domaine: str, sujet: str, attribut: str):
        r = self.base.execute("SELECT valeur FROM validation WHERE domaine=? AND attribut=? AND sujet=? ORDER BY id DESC LIMIT 1",
                              (domaine, attribut, str(sujet))).fetchone()
        return r[0] if r else None

    def affirmations(self, domaine: str, attribut: str, sujet: str | None = None) -> pd.DataFrame:
        if sujet is None:
            return self._table("SELECT * FROM affirmation WHERE domaine=? AND attribut=? ORDER BY id", (domaine, attribut))
        return self._table("SELECT * FROM affirmation WHERE domaine=? AND attribut=? AND sujet=? ORDER BY id", (domaine, attribut, str(sujet)))

    def fiabilites(self, domaine: str, attribut: str) -> pd.DataFrame:
        """Fiabilité de chaque type de source, apprise sur les sujets validés.

        Une affirmation est juste si elle donne la valeur validée ; une négation est juste si elle écarte une valeur
        qui n'est pas la valeur validée. A posteriori : Bêta(a priori × force + justes, (1 − a priori) × force + fausses).
        """
        v = self.verites(domaine, attribut)
        a = self.affirmations(domaine, attribut)
        types = sorted(set(A_PRIORI_SOURCES) | set(a["type_source"]))
        lignes = []
        for t in types:
            g = a[a["type_source"].eq(t) & a["sujet"].isin(list(v))]
            juste = int(sum((r["valeur"] == v[r["sujet"]]) == (r["polarite"] >= 0) for _, r in g.iterrows()))
            m0 = A_PRIORI_SOURCES.get(t, FIABILITE_PAR_DEFAUT)
            al, be = m0 * FORCE_A_PRIORI + juste, (1 - m0) * FORCE_A_PRIORI + (len(g) - juste)
            lignes.append({"Type de source": t, "A priori (hypothèse)": m0, "Affirmations vérifiées": len(g), "Justes": juste,
                           "Fausses": len(g) - juste, "Fiabilité": al / (al + be),
                           "Poids des observations": len(g) / (len(g) + FORCE_A_PRIORI), "_a": al, "_b": be})
        return pd.DataFrame(lignes)

    def croyance(self, domaine: str, sujet: str, attribut: str, classes, a_priori: dict | None = None, fiabilites: pd.DataFrame | None = None) -> dict:
        """Probabilité de chaque valeur possible pour un sujet.

        classes   : valeurs possibles (au moins deux) ; une valeur affirmée hors de la liste y est ajoutée.
        a_priori  : {valeur: probabilité} avant toute preuve ; uniforme par défaut.
        Renvoie {"probabilites", "retenue", "probabilite", "preuves", "validee", "sources"}. Sans preuve : « retenue » vaut None.
        """
        sujet = str(sujet)
        vraie = self.verite(domaine, sujet, attribut)
        a = self.affirmations(domaine, attribut, sujet)
        classes = list(dict.fromkeys([*map(str, classes), *a["valeur"].astype(str), *([str(vraie)] if vraie is not None else [])]))
        if vraie is not None:
            return {"probabilites": {c: float(c == str(vraie)) for c in classes}, "retenue": str(vraie), "probabilite": 1.0,
                    "preuves": len(a), "validee": True, "sources": ["validation humaine"]}
        C = max(len(classes), 2)
        p0 = np.array([float((a_priori or {}).get(c, 0.0)) for c in classes]) if a_priori else np.ones(len(classes))
        p0 = p0 + 1e-12 if p0.sum() > 0 else np.ones(len(classes))
        logp = np.log(p0 / p0.sum())
        f = fiabilites if fiabilites is not None else self.fiabilites(domaine, attribut)
        r_type = dict(zip(f["Type de source"], f["Fiabilité"]))
        for _, e in a.iterrows():
            r = float(np.clip(r_type.get(e["type_source"], FIABILITE_PAR_DEFAUT), 0.01, 0.99))
            dit = np.array([c == str(e["valeur"]) for c in classes])
            if e["polarite"] >= 0:                           # « c'est V » : r si V est vrai, (1 − r) réparti sur les autres sinon
                logp += np.where(dit, np.log(r), np.log((1 - r) / (C - 1)))
            else:                                            # « ce n'est pas V » : 1 − r si V est vrai, r sinon
                logp += np.where(dit, np.log(1 - r), np.log(r))
        p = np.exp(logp - logp.max())
        p = p / p.sum()
        i = int(np.argmax(p))
        return {"probabilites": dict(zip(classes, map(float, p))), "retenue": classes[i] if len(a) else None,
                "probabilite": float(p[i]) if len(a) else float("nan"), "preuves": len(a), "validee": False,
                "sources": sorted(set(a["type_source"]))}

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
        return sorted([o for o in out if o[1] >= seuil], key=lambda o: -o[1])[:k]

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
