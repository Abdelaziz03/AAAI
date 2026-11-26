"""GEPA en local : le modèle hébergé chez vous améliore ses propres consignes à partir de vos pièces validées.

GEPA (« Genetic-Pareto », Agrawal et al. 2025, « GEPA: Reflective Prompt Evolution Can Outperform Reinforcement
Learning ») améliore la consigne d'un modèle sans toucher à ses poids. Ce module en est une écriture autonome, sans
dépendance ni service extérieur ; ce n'est pas le paquet officiel. Il en reprend la boucle :

  1. garder une population de consignes candidates, notées exemple par exemple sur un jeu de sélection ;
  2. choisir un candidat parmi ceux qui sont LES MEILLEURS SUR AU MOINS UN EXEMPLE (front de Pareto), avec une chance
     proportionnelle au nombre d'exemples où il gagne : on ne suit pas seulement le meilleur en moyenne ;
  3. l'essayer sur un petit lot d'exemples, et montrer ses erreurs à un modèle de RÉFLEXION, qui écrit une consigne
     corrigée ;
  4. n'accepter la nouvelle consigne que si elle fait mieux que son parent sur ce même lot ; elle est alors notée sur
     tout le jeu de sélection et rejoint la population ;
  5. s'arrêter au budget d'appels, et rendre la consigne la meilleure en moyenne sur le jeu de sélection.
L'étape de croisement de deux candidats (« merge »), facultative dans l'article, n'est pas écrite.

Ce que cela apporte au dossier.
  Moins d'appels : une meilleure lecture des descriptions, faite chez vous, résout plus de pièces sans recherche
      extérieure ; le budget de l'amélioration est borné, chaque couple (consigne, exemple) n'est exécuté qu'une fois,
      et la longueur de la consigne est plafonnée puisqu'elle se paie à chaque appel.
  Pas de raccourcis : la consigne apprise doit énoncer des règles, pas une table de réponses. Elle est refusée si elle
      contient un code article ou recopie une désignation du jeu ; une réponse sans indice dans la désignation est
      comptée fausse ; se taire vaut mieux que se tromper (crédit d'abstention) ; et le gain est mesuré sur des pièces
      d'ESSAI que la recherche n'a jamais vues. La consigne n'est adoptée que si elle ne fait pas moins bien sur cet essai.

Seul le texte des CONSEILS change ; le cadre de la consigne (tâche, liste des classes, forme de la réponse) est fixé
par erc/modele.py et ne peut pas être réécrit. Tout se passe entre le dossier et votre modèle : les deux modèles
(lecture et réflexion) doivent être privés. Les conseils appris restent dans parametres/, hors du dépôt.

    python -m erc.modele --optimiser [--budget 200] [--reflexion AUTRE_MODELE]
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .cortex import plier, texte
from .modele import LONGUEUR_MAX_CONSEILS, _intervalle, _mcnemar

MINIMUM_DE_PIECES = 24                   # en dessous, les trois jeux sont trop petits pour mesurer quoi que ce soit


@dataclass(frozen=True)
class Exemple:
    cle: str                             # identifiant de l'exemple (jamais montré au modèle)
    entree: tuple                        # ce que le modèle lit, par exemple (désignation, type de pièce)
    attendu: str                         # la réponse validée par une personne


# --------------------------------------------------------------------------- sélection de Pareto
def choisir(scores: list, rng) -> int:
    """Indice du candidat à faire évoluer (algorithme 2 de l'article).

    scores[k][i] : note du candidat k sur l'exemple i du jeu de sélection. Pour chaque exemple, les candidats qui y
    obtiennent la meilleure note sont « en tête ». Un candidat en tête nulle part n'est jamais choisi ; un candidat
    dont tous les exemples en tête le sont aussi pour un autre, qui en a davantage (ou autant, et une meilleure
    moyenne, ou à égalité le plus récent), est écarté. Parmi les restants, le tirage est proportionnel au nombre
    d'exemples en tête.
    """
    S = np.asarray(scores, float)
    if S.ndim != 2 or not S.size:
        return 0
    en_tete = S >= S.max(axis=0) - 1e-12                       # (candidat, exemple)
    restants = [k for k in range(len(S)) if en_tete[k].any()]
    cle = lambda k: (int(en_tete[k].sum()), float(S[k].mean()), k)
    gardes = [k for k in restants
              if not any(j != k and (en_tete[j] | ~en_tete[k]).all() and cle(j) > cle(k) for j in restants)]
    poids = np.array([en_tete[k].sum() for k in gardes], float)
    return int(gardes[int(rng.choice(len(gardes), p=poids / poids.sum()))])


# --------------------------------------------------------------------------- la boucle
def optimiser(depart: str, executer, reflechir, retour: list, selection: list, budget: int = 200, lot: int = 4, graine: int = 0,
              valide=None, patience: int = 12) -> dict:
    """Fait évoluer une consigne.

    depart    : consigne de départ.
    executer  : (consigne, exemple) -> (note entre 0 et 1, commentaire, réponse) ; un appel au modèle de lecture.
    reflechir : (consigne, [(exemple, note, commentaire, réponse)]) -> nouvelle consigne, ou None ; un appel au modèle de réflexion.
    retour    : exemples dont les erreurs sont montrées au modèle de réflexion, par petits lots.
    selection : exemples sur lesquels les candidats sont notés et choisis (front de Pareto).
    budget    : nombre maximal d'appels au modèle de lecture, notation de départ comprise.
    valide    : (consigne) -> raison du refus, ou None ; une consigne refusée n'est pas essayée.
    patience  : arrêt après ce nombre de propositions sans aucune acceptée.

    Renvoie {"meilleure", "candidats" (table), "scores", "appels", "journal"}. Chaque couple (consigne, exemple) n'est
    exécuté qu'une fois ; la même graine redonne le même déroulement si les modèles sont eux-mêmes répétables.
    """
    rng = np.random.default_rng(graine)
    memoire, appels = {}, {"lecture": 0, "réflexion": 0}

    def noter(consigne: str, e: Exemple):
        cle = (hashlib.sha256(consigne.encode("utf-8")).hexdigest(), e.cle)
        if cle not in memoire:
            appels["lecture"] += 1
            note, commentaire, reponse = executer(consigne, e)
            memoire[cle] = (float(note), texte(commentaire), reponse)
        return memoire[cle]

    candidats, parents, journal = [depart], [None], []
    if len(selection) > budget or not retour:
        return {"meilleure": depart, "candidats": pd.DataFrame(), "scores": [], "appels": appels,
                "journal": ["budget trop petit pour noter la consigne de départ, ou aucun exemple de retour : rien n'a été essayé"]}
    scores = [[noter(depart, e)[0] for e in selection]]
    lot, sans_acceptation = max(1, min(lot, len(retour))), 0
    while appels["lecture"] + 2 * lot + len(selection) <= budget and sans_acceptation < patience:
        if min(scores[int(np.argmax([np.mean(s) for s in scores]))]) >= 1.0:
            journal.append("le meilleur candidat répond juste sur tout le jeu de sélection : arrêt")
            break
        k = choisir(scores, rng)
        M = [retour[i] for i in rng.choice(len(retour), size=lot, replace=False)]
        avant = [noter(candidats[k], e) for e in M]
        if all(a[0] >= 1.0 for a in avant):
            sans_acceptation += 1
            journal.append(f"candidat {k} : rien à corriger sur ce lot")
            continue
        appels["réflexion"] += 1
        proposition = texte(reflechir(candidats[k], [(e, *a) for e, a in zip(M, avant)])).strip()
        refus = "aucune proposition" if not proposition else "identique à un candidat existant" if proposition in candidats else (valide(proposition) if valide else None)
        if refus:
            sans_acceptation += 1
            journal.append(f"candidat {k} : proposition refusée ({refus})")
            continue
        apres = [noter(proposition, e) for e in M]
        gain = sum(a[0] for a in apres) - sum(a[0] for a in avant)
        if gain <= 1e-12:                                      # pas mieux que son parent sur le même lot : écartée
            sans_acceptation += 1
            journal.append(f"candidat {k} : proposition écartée (lot {sum(a[0] for a in avant):.2f} → {sum(a[0] for a in apres):.2f})")
            continue
        candidats.append(proposition)
        parents.append(k)
        scores.append([noter(proposition, e)[0] for e in selection])
        sans_acceptation = 0
        journal.append(f"candidat {len(candidats) - 1} accepté, issu de {k} (lot {sum(a[0] for a in avant):.2f} → {sum(a[0] for a in apres):.2f} ; "
                       f"sélection {np.mean(scores[k]):.3f} → {np.mean(scores[-1]):.3f})")
    moyennes = [float(np.mean(s)) for s in scores]
    # la meilleure en moyenne ; à égalité, la plus courte (elle coûte moins à chaque appel), puis la plus ancienne
    meilleur = min(range(len(candidats)), key=lambda i: (-round(moyennes[i], 12), len(candidats[i]), i))
    table = pd.DataFrame({"Candidat": range(len(candidats)), "Issu de": parents, "Note sur la sélection": moyennes,
                          "Longueur (caractères)": [len(c) for c in candidats], "Retenu": [i == meilleur for i in range(len(candidats))]})
    return {"meilleure": candidats[meilleur], "candidats": table, "scores": scores, "appels": appels, "journal": journal,
            "textes": candidats}


# --------------------------------------------------------------------------- lecture des descriptions
CONSIGNE_DE_REFLEXION = """J'ai donné à un assistant les conseils ci-dessous pour classer des pièces de rechange d'après leur désignation, parmi ces classes matière : {classes}.

Conseils actuels :
```
{conseils}
```

Voici des désignations, ce que l'assistant a répondu, et ce qu'il fallait répondre :
```
{exemples}
```

Écris de meilleurs conseils. Cherche ce qui explique les erreurs : vocabulaire du métier, abréviations, mots trompeurs, cas où il vaut mieux répondre « aucune » que deviner. Formule des règles générales, utiles pour d'autres pièces. Ne recopie aucun code article ni aucune désignation entière, et ne dresse pas la liste des exemples. Garde ce qui marchait dans les conseils actuels. {longueur} caractères au plus. Ne parle pas de la forme de la réponse : elle est fixée par ailleurs.

Donne les nouveaux conseils, et rien d'autre, entre deux lignes ```."""


def _bloc(reponse: str) -> str:
    """Texte du dernier bloc entre ``` d'une réponse ; la réponse entière s'il n'y en a pas. Le raisonnement est retiré."""
    t = re.sub(r"<think>.*?</think>", " ", texte(reponse), flags=re.S | re.I).split("</think>")[-1]
    blocs = re.findall(r"```[a-zA-Z]*\n?(.*?)```", t, flags=re.S)
    return (blocs[-1] if blocs else t).strip()


def partager(pieces: list, graine: int = 0, part_essai: float = 0.3) -> tuple:
    """(retour, sélection, essai) : trois jeux disjoints, tirés au hasard à graine fixe, classe par classe pour que
    chacun voie toutes les classes. L'essai n'est jamais montré à la recherche."""
    rng = np.random.default_rng(graine)
    par_classe = {}
    for e in sorted(pieces, key=lambda e: e.cle):
        par_classe.setdefault(e.attendu, []).append(e)
    jeux = ([], [], [])
    for classe in sorted(par_classe):
        g = par_classe[classe]
        g = [g[i] for i in rng.permutation(len(g))]
        n_essai = int(round(part_essai * len(g)))
        reste = g[n_essai:]
        jeux[2].extend(g[:n_essai])
        jeux[0].extend(reste[0::2])
        jeux[1].extend(reste[1::2])
    return jeux


def optimiser_descriptions(cx, modele, classes, reflexion=None, domaine: str = "composition", attribut: str = "classe matière",
                           budget: int = 200, lot: int = 4, graine: int = 0, credit_abstention: float = 0.5, part_essai: float = 0.3) -> dict:
    """Améliore les conseils de lecture des descriptions sur les pièces validées du cortex, puis mesure le résultat
    sur des pièces d'essai tenues à l'écart.

    modele    : modèle de lecture (privé). reflexion : modèle qui écrit les nouveaux conseils (privé ; défaut : le même).
    credit_abstention : note d'une absence de réponse, entre 0 (faux) et 1 (juste). À 0,5, le modèle a intérêt à ne
                        répondre que s'il a plus d'une chance sur deux d'avoir raison.
    Renvoie {"conseils", "adopte", "raison", "resume", "essai", "candidats", "journal", "appels"} ; rien n'est écrit.
    """
    from .risques import type_piece
    reflexion = reflexion if reflexion is not None else modele
    for nom, m in (("lecture", modele), ("réflexion", reflexion)):
        if not getattr(m, "prive", False):
            raise PermissionError(f"Le modèle de {nom} n'est pas privé : l'amélioration des consignes lui montrerait des descriptions internes.")
    classes = list(classes)
    v = cx.verites(domaine, attribut)
    t = cx._table("SELECT sujet, description FROM sujet WHERE domaine=?", (domaine,))
    pieces = []
    for _, r in t.iterrows():
        d = texte(r["description"]).strip()
        if r["sujet"] in v and d and v[r["sujet"]] in classes:
            ty = type_piece(d)
            pieces.append(Exemple(str(r["sujet"]), (d, "" if ty.startswith("(") else ty), v[r["sujet"]]))
    depart = texte(getattr(modele, "conseils", {}).get("description", "")).strip()
    vide = {"conseils": depart, "adopte": False, "resume": pd.DataFrame(), "essai": pd.DataFrame(), "candidats": pd.DataFrame(), "journal": [],
            "appels": {"lecture": 0, "réflexion": 0, "essai": 0}}
    if len(pieces) < MINIMUM_DE_PIECES:
        return dict(vide, raison=f"{len(pieces)} pièces validées avec description : il en faut au moins {MINIMUM_DE_PIECES} pour améliorer les consignes "
                                 "et mesurer le résultat. Valider d'abord des pièces dans la page de revue.")
    retour, selection, essai = partager(pieces, graine, part_essai)
    interdits = [plier(e.cle) for e in pieces if len(e.cle) >= 4]
    recopiables = [plier(e.entree[0]) for e in pieces if len(e.entree[0]) >= 12]

    def valide(consigne: str):
        pliee = plier(consigne)
        if len(consigne) > LONGUEUR_MAX_CONSEILS:
            return f"plus de {LONGUEUR_MAX_CONSEILS} caractères"
        if any(c in pliee for c in interdits):
            return "contient un code article"
        if any(d in pliee for d in recopiables):
            return "recopie une désignation entière"
        return None

    def executer(consigne: str, e: Exemple):
        try:
            d = modele.classer_detail(e.entree[0], classes, e.entree[1], conseils=consigne)
        except Exception as ex:                                # une panne n'apprend rien : comptée fausse, et dite
            return 0.0, f"Panne du modèle ({type(ex).__name__}).", None
        if d["classe"] == e.attendu:
            return 1.0, "Juste.", d["classe"]
        if d["classe"] is None:
            return credit_abstention, f"Pas de réponse retenue ({d['rejet']}" + (f" ; il avait répondu « {d['repondu']} »" if d["repondu"] else "") + f"). Il fallait « {e.attendu} ».", None
        return 0.0, f"Faux : il a répondu « {d['classe']} » (indice « {d['indice']} »), il fallait « {e.attendu} ».", d["classe"]

    def reflechir(consigne: str, traces: list):
        lignes = [f"{i}. Désignation : {e.entree[0]}" + (f" | Type de pièce : {e.entree[1]}" if e.entree[1] else "") + f"\n   Retour : {commentaire}"
                  for i, (e, _, commentaire, _) in enumerate(traces, 1)]
        question = CONSIGNE_DE_REFLEXION.format(classes=" ; ".join(classes), conseils=consigne or "(aucun pour l'instant)",
                                                exemples="\n".join(lignes), longueur=LONGUEUR_MAX_CONSEILS)
        try:
            return _bloc(reflexion.demander("Tu améliores les consignes données à un assistant. Réponds en français.", question))
        except Exception:
            return None

    r = optimiser(depart, executer, reflechir, retour, selection, budget, lot, graine, valide)
    meilleure = r["meilleure"]
    # Mesure sur l'essai, jamais vu par la recherche : consigne de départ contre consigne retenue
    avant_essai = r["appels"]["lecture"]
    notes = {"de départ": [executer(depart, e) for e in essai]}
    notes["retenue"] = notes["de départ"] if meilleure == depart else [executer(meilleure, e) for e in essai]
    n_essai = len(essai) * (1 if meilleure == depart else 2)
    lignes = []
    for nom, liste in notes.items():
        justes = int(sum(x[0] >= 1.0 for x in liste))
        muets = int(sum(x[2] is None for x in liste))
        bas, haut = _intervalle(justes, len(liste))
        lignes.append({"Consigne": nom, "Pièces d'essai": len(liste), "Justes": justes, "Sans réponse": muets, "Fausses": len(liste) - justes - muets,
                       "Taux de justes": justes / len(liste) if liste else np.nan, "Borne basse (90 %)": bas, "Borne haute (90 %)": haut,
                       "Note moyenne": float(np.mean([x[0] for x in liste])) if liste else np.nan})
    resume = pd.DataFrame(lignes)
    a, b = np.array([x[0] >= 1.0 for x in notes["de départ"]]), np.array([x[0] >= 1.0 for x in notes["retenue"]])
    p_hasard = _mcnemar(int((b & ~a).sum()), int((a & ~b).sum()))
    resume["Écart entre les deux : hasard possible (p)"] = p_hasard
    table_essai = pd.DataFrame({"PN": [e.cle for e in essai], "Description": [e.entree[0] for e in essai], "Classe validée": [e.attendu for e in essai],
                                "Consigne de départ": [x[2] for x in notes["de départ"]], "Consigne retenue": [x[2] for x in notes["retenue"]]})
    sel = r["candidats"]
    gain_selection = float(sel["Note sur la sélection"].max() - sel["Note sur la sélection"].iloc[0]) if len(sel) else 0.0
    note_avant, note_apres = (float(resume["Note moyenne"].iloc[0]), float(resume["Note moyenne"].iloc[1])) if len(resume) == 2 else (np.nan, np.nan)
    if meilleure == depart:
        adopte, raison = False, "aucune consigne essayée n'a fait mieux que la consigne de départ sur le jeu de sélection"
    elif note_apres < note_avant:
        adopte, raison = False, (f"la consigne retenue fait mieux sur le jeu de sélection (+{gain_selection:.3f}) mais moins bien sur les pièces d'essai "
                                 f"({note_avant:.3f} → {note_apres:.3f}) : elle n'est pas adoptée")
    else:
        adopte = True
        raison = (f"note sur les pièces d'essai {note_avant:.3f} → {note_apres:.3f}" +
                  (" ; l'écart peut être dû au hasard (p = {:.2f}), à confirmer avec plus de pièces validées".format(p_hasard) if p_hasard > 0.10 else
                   " ; écart peu compatible avec le hasard (p = {:.3f})".format(p_hasard)))
    return {"conseils": meilleure, "adopte": adopte, "raison": raison, "resume": resume, "essai": table_essai, "candidats": sel, "journal": r["journal"],
            "appels": {"lecture": avant_essai, "réflexion": r["appels"]["réflexion"], "essai": n_essai},
            "jeux": {"retour": len(retour), "sélection": len(selection), "essai": len(essai)}, "textes": r.get("textes", [depart])}
