"""Agents : un modèle ouvert, hébergé chez vous, pilote le dossier de bout en bout et rédige la note de décision.

    python -m erc.agent              lance tout : diagnostic, calculs, composition des pièces, note de décision
    python -m erc.agent --sans-modele   même enchaînement sans modèle de langage (plan fixe)

Le principe est celui d'un assistant à outils : le modèle ne calcule rien lui-même, il CHOISIT des outils, lit leurs
résultats, décide de la suite, puis écrit. Trois rôles se succèdent, tous tenus par le modèle du réglage
(parametres/modele_local.cfg) :

  pilote      enchaîne les outils : lancer les calculs, lire les tables, voir ce qui manque, lancer la composition ;
  rédacteur   écrit la note de décision à partir des seules preuves que le pilote a réunies ;
  relecteur   relit la note contre ces preuves et consigne ses réserves.

Ce qui tient l'ensemble :
  - Les outils sont une liste fermée de fonctions du dossier. Pas de ligne de commande, pas d'écriture hors de
    artefacts/agent/, pas d'accès au réseau : sur un poste verrouillé, l'agent ne peut rien faire d'autre que ce que le
    dossier fait déjà.
  - Tous les chiffres viennent des calculs du dossier. Un contrôle par programme, sans modèle, vérifie que chaque nombre
    de la note figure dans les preuves ; un nombre qui n'y est pas est signalé en tête de note, jamais laissé passer.
  - Le modèle doit être privé (ce poste, ou une machine déclarée) : les tables qu'il lit sont vos données.
  - Le nombre de pas est borné, chaque pas est journalisé (artefacts/agent/Journal.jsonl), et une panne du modèle ne
    bloque rien : l'enchaînement se termine par le plan fixe.
  - Sans modèle, le plan fixe fait la même chose dans un ordre arrêté d'avance et remplit une note type : la preuve de
    concept tourne sur n'importe quel poste, puis gagne en finesse quand un modèle est branché.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from . import modele as mod_modele
from .config import ETAPES
from .cortex import texte

PAS_MAX = 24
TAILLE_RESULTAT = 1800                   # caractères rendus par un outil : assez pour décider, pas assez pour saturer le modèle
TAILLE_CONVERSATION = 14000              # au-delà, les résultats anciens sont raccourcis


# --------------------------------------------------------------------------- état et outils
class Session:
    """Ce que les agents partagent : le dossier, le contexte de calcul, les preuves réunies, le journal."""

    def __init__(self, cfg, modele=None):
        self.cfg, self.modele = cfg, modele
        self.ctx, self.compo = None, None
        self.preuves, self.journal, self.faits = [], [], set()

    def contexte(self, etape: str = "synthese"):
        from .etapes import executer
        deja = self.ctx is not None and etape in self.ctx.res
        if not deja:
            self.ctx = executer(etape, cfg=self.cfg, silencieux=True)
        return self.ctx

    def noter(self, role: str, quoi: str, **plus):
        self.journal.append({"pas": len(self.journal) + 1, "rôle": role, "quoi": quoi, **plus})


def _table(df: pd.DataFrame, lignes: int = 8) -> str:
    """Une table en texte compact : au plus `lignes` lignes, nombres arrondis à quatre chiffres significatifs."""
    if not isinstance(df, pd.DataFrame) or not len(df):
        return "(table vide)"
    d = df.head(int(lignes)).copy()
    for c in d.columns:
        if pd.api.types.is_float_dtype(d[c]):
            d[c] = d[c].map(lambda v: "" if pd.isna(v) else f"{v:.4g}")
    t = d.to_csv(sep="|", index=False).strip()
    return t + (f"\n… {len(df) - len(d)} autre(s) ligne(s)" if len(df) > len(d) else "")


def outil_diagnostic(s: Session) -> str:
    from . import diagnostic
    manquants = [p["Paquet"] for p in diagnostic.paquets() if p["Nécessaire"] and p["Version"] is None]
    gpu = diagnostic.carte_graphique()
    carte = ", ".join(f"{c['nom']} ({c['memoire_go']} Go)" for c in gpu["cartes"]) or gpu["raison"]
    return (f"Données : {'DÉMONSTRATION (fictives)' if s.cfg.demo else 'réelles'}. Paquets nécessaires manquants : {', '.join(manquants) or 'aucun'}. "
            f"Carte graphique : {carte}. Modèle de langage : {getattr(s.modele, 'modele', None) or 'aucun'}"
            + (f" ({s.modele.nature})." if s.modele is not None and hasattr(s.modele, "nature") else "."))


def outil_lancer_etape(s: Session, etape: str = "synthese") -> str:
    if etape not in ETAPES:
        return f"Étape inconnue. Étapes : {', '.join(ETAPES)}."
    ctx = s.contexte(etape)
    lignes = [f"{e} : " + ", ".join(k for k, v in d.items() if isinstance(v, pd.DataFrame)) for e, d in ctx.res.items() if e in ETAPES]
    return f"Calculs faits jusqu'à « {etape} ». Anomalies : {len(ctx.anomalies)}.\n" + "\n".join(lignes)


def outil_lire_table(s: Session, etape: str = "", nom: str = "", lignes: int = 8) -> str:
    ctx = s.contexte(etape if etape in ETAPES else "synthese")
    tables = {k: v for k, v in ctx.res.get(etape, {}).items() if isinstance(v, pd.DataFrame)}
    if nom not in tables:
        return f"Table inconnue. Tables de « {etape} » : {', '.join(tables) or 'aucune'}."
    return f"{etape} / {nom} ({len(tables[nom])} lignes)\n" + _table(tables[nom], min(int(lignes or 8), 20))


def outil_indicateurs(s: Session) -> str:
    d = s.contexte("synthese").res["synthese"]["Tableau de décision"]
    return "Indicateurs de décision\n" + "\n".join(f"- {r['Indicateur']} : {r['Valeur']} ({r['Lecture']})" for _, r in d.iterrows())


def outil_limites(s: Session) -> str:
    ctx = s.contexte("synthese")
    lim = ctx.res["synthese"]["Limites et lecture"]
    out = ["Limites et lecture"] + [f"- {r.iloc[0]} : {r.iloc[1]}" for _, r in lim.iterrows()]
    manque = ctx.res.get("ligne", {}).get("Données à obtenir")
    if isinstance(manque, pd.DataFrame) and len(manque):
        out += [f"Données à obtenir ({len(manque)} lignes)", _table(manque, 8)]
    out.append(f"Anomalies de calcul : {len(ctx.anomalies)}" + ("" if not ctx.anomalies else " : " + "; ".join(f"{a['Étape']} / {a['Calcul']}" for a in ctx.anomalies[:5])))
    return "\n".join(out)


def outil_composition(s: Session) -> str:
    from . import composition
    s.compo = composition.executer(s.contexte("ligne"))
    n = s.compo["Notes"]
    if "motif" in n:
        return "Composition non calculée : " + n["motif"]
    return (f"Composition des pièces : {n.get('pieces')} pièces ; statuts {n.get('statuts')} ; appels au modèle {n.get('appels_au_modele')} ; "
            f"pièces sans appel payant {n.get('pieces_sans_appel_payant')} ; coût des acquisitions {n.get('cout_des_acquisitions_eur'):.2f} €. "
            f"Modèle : {n.get('modele')}" + (f" ({n.get('modele_heberge')})" if n.get("modele_heberge") else "") + ".")


def outil_file_de_revue(s: Session, lignes: int = 8) -> str:
    if s.compo is None:
        outil_composition(s)
    f = s.compo.get("File de revue", pd.DataFrame())
    cols = [c for c in ("PN", "Description", "Classe retenue", "Probabilité", "Enjeu (€/an, borne)", "Prochaine action") if c in f]
    return f"File de revue ({len(f)} pièces à valider, par enjeu décroissant)\n" + _table(f[cols] if len(f) else f, min(int(lignes or 8), 20))


OUTILS = {
    "diagnostic": ("État du poste : données réelles ou démonstration, paquets, carte graphique, modèle.", {}, outil_diagnostic),
    "lancer_etape": ("Lance les calculs jusqu'à une étape (sources, classement, flux, fiabilite, rex, ligne, synthese) et liste les tables produites.",
                     {"etape": "nom de l'étape ; « synthese » fait tout"}, outil_lancer_etape),
    "lire_table": ("Lit les premières lignes d'une table produite par une étape.", {"etape": "étape", "nom": "nom exact de la table", "lignes": "nombre de lignes, 8 par défaut"},
                   outil_lire_table),
    "indicateurs": ("Les indicateurs de décision de la ligne de démontage et de tri : gain annuel, probabilité d'être rentable, seuil, heures, masse détournée.", {},
                    outil_indicateurs),
    "limites": ("Ce qui limite la portée des résultats : mode, période, données à obtenir, anomalies.", {}, outil_limites),
    "composition": ("Lance la chaîne de composition des pièces et rend son bilan (statuts, appels au modèle, coûts).", {}, outil_composition),
    "file_de_revue": ("Les pièces à faire valider par une personne, par enjeu décroissant.", {"lignes": "nombre de lignes, 8 par défaut"}, outil_file_de_revue),
}
PLAN_FIXE = [("diagnostic", {}), ("lancer_etape", {"etape": "synthese"}), ("indicateurs", {}), ("limites", {}), ("composition", {}), ("file_de_revue", {})]
ESSENTIELS = ["indicateurs", "limites"]


def appeler(s: Session, role: str, nom: str, arguments: dict | None = None) -> str:
    """Exécute un outil de la liste fermée et range son résultat parmi les preuves. Une erreur devient un résultat lisible."""
    arguments = arguments if isinstance(arguments, dict) else {}
    if nom not in OUTILS:
        resultat = f"Outil inconnu : « {nom} ». Outils : {', '.join(OUTILS)}."
    else:
        permis = OUTILS[nom][1]
        try:
            resultat = OUTILS[nom][2](s, **{k: v for k, v in arguments.items() if k in permis})
            s.faits.add(nom)
            s.preuves.append(f"[{nom}] {resultat}")
        except Exception as e:                                 # un outil qui échoue n'arrête pas l'agent
            resultat = f"Erreur de l'outil « {nom} » : {type(e).__name__}."
    resultat = resultat[:TAILLE_RESULTAT] + (" …" if len(resultat) > TAILLE_RESULTAT else "")
    s.noter(role, f"outil {nom}", arguments=arguments, resultat=resultat[:400])
    return resultat


# --------------------------------------------------------------------------- les nombres de la note doivent venir des preuves
MOTIF_NOMBRE = re.compile(r"(?<![\w.,])(?:\d{1,3}(?:[   ]\d{3})+|\d+)(?:[.,]\d+)?(?![\w])")


def nombres(t: str) -> list:
    """Nombres d'un texte, avec leur nombre de décimales : [(valeur, décimales, écriture)]. Les chiffres collés à des
    lettres (« P95 », « FRU-A100 ») ne sont pas des nombres."""
    out = []
    for m in MOTIF_NOMBRE.finditer(texte(t)):
        brut = m.group(0)
        net = re.sub(r"[   ]", "", brut).replace(",", ".")
        out.append((float(net), len(net.split(".")[1]) if "." in net else 0, brut))
    return out


def non_fondes(note: str, preuves, ignorer_sous: int = 10) -> list:
    """Nombres de la note absents des preuves. Un nombre est fondé s'il figure dans les preuves, tel quel, arrondi au
    même nombre de décimales, ou en pourcentage d'une proportion. Les petits entiers (numéros de liste, comptes) sont
    laissés de côté."""
    connus = [v for v, _, _ in nombres("\n".join(preuves))]
    out = []
    for v, dec, brut in nombres(note):
        if dec == 0 and v < ignorer_sous:
            continue
        tol = 0.5 * 10 ** (-dec) + 1e-9
        if not any(abs(p - v) <= tol or abs(100 * p - v) <= tol for p in connus):
            out.append(brut)
    return list(dict.fromkeys(out))


# --------------------------------------------------------------------------- le pilote
CONSIGNE_PILOTE = """Tu pilotes un dossier d'aide à la décision d'un centre de réparation d'équipements : faut-il installer une ligne de démontage et de tri des unités mises au scrap, et que faut-il encore savoir pour en être sûr ?

Tu ne calcules rien toi-même et tu n'inventes aucun chiffre : tu appelles des outils, tu lis leurs résultats, tu décides de la suite. Outils :
{outils}

À chaque tour, réponds par un seul objet JSON : {{"outil": "<nom>", "arguments": {{...}}}}.
Quand tu as ce qu'il faut (les indicateurs, les limites, la composition des pièces et la file de revue), réponds {{"outil": "terminer", "arguments": {{"constats": ["<constat appuyé sur un résultat>", "..."]}}}}.
Tu as {pas} tours au plus. Ne relance pas un outil dont tu as déjà le résultat."""


def _schema_pilote() -> dict:
    return {"type": "object", "properties": {"outil": {"type": "string", "enum": [*OUTILS, "terminer"]}, "arguments": {"type": "object"}}, "required": ["outil", "arguments"]}


def _raccourcir(messages: list) -> list:
    """Garde la conversation sous une taille raisonnable : les résultats les plus anciens sont réduits à leur début."""
    total = sum(len(m["content"]) for m in messages)
    for m in messages[2:-4]:
        if total <= TAILLE_CONVERSATION:
            break
        if m["role"] == "user" and len(m["content"]) > 320:
            total -= len(m["content"]) - 320
            m["content"] = m["content"][:300] + " … (raccourci)"
    return messages


def piloter(s: Session, pas_max: int = PAS_MAX) -> list:
    """Laisse le modèle enchaîner les outils. Renvoie ses constats ; liste vide si le modèle n'a pas pu conclure."""
    outils = "\n".join(f"- {n} : {d}" + (f" Arguments : {a}." if a else "") for n, (d, a, _) in OUTILS.items())
    messages = [{"role": "system", "content": CONSIGNE_PILOTE.format(outils=outils, pas=pas_max)},
                {"role": "user", "content": "Commence. Premier outil ?"}]
    illisibles = 0
    for _ in range(pas_max):
        try:
            reponse = s.modele.converser(_raccourcir(messages), _schema_pilote())
        except mod_modele.Indisponible as e:
            s.noter("pilote", f"modèle indisponible ({e}) : suite par le plan fixe")
            return []
        o = mod_modele._objet_json(reponse)
        if not isinstance(o, dict) or not isinstance(o.get("outil"), str):
            illisibles += 1
            s.noter("pilote", "réponse illisible", reponse=texte(reponse)[:200])
            if illisibles >= 2:
                return []
            messages += [{"role": "assistant", "content": texte(reponse)[:500]},
                         {"role": "user", "content": 'Réponse illisible. Un seul objet JSON : {"outil": "<nom>", "arguments": {...}}.'}]
            continue
        illisibles = 0
        if o["outil"] == "terminer":
            constats = [texte(c).strip() for c in (o.get("arguments") or {}).get("constats", []) if texte(c).strip()] if isinstance(o.get("arguments"), dict) else []
            s.noter("pilote", "terminer", constats=constats)
            return constats or ["(le pilote a conclu sans constat)"]
        resultat = appeler(s, "pilote", o["outil"], o.get("arguments"))
        messages += [{"role": "assistant", "content": json.dumps({"outil": o["outil"], "arguments": o.get("arguments") or {}}, ensure_ascii=False)},
                     {"role": "user", "content": f"Résultat de {o['outil']} :\n{resultat}\n\nOutil suivant ?"}]
    s.noter("pilote", "nombre de tours atteint")
    return []


# --------------------------------------------------------------------------- rédaction et relecture
CONSIGNE_REDACTEUR = """Tu rédiges une note de décision pour le responsable d'un centre de réparation, en français clair, sans jargon.
Règle absolue : tu n'utilises que les chiffres présents dans les preuves, recopiés tels quels, avec leur unité. Si une information manque, tu le dis.
Plan imposé, en Markdown :
## Recommandation
## Ce qui la fonde
## Ce qui manque pour en être sûr
## Prochaines actions
Une page au plus. Si les données sont une démonstration, dis-le dès la première ligne."""

CONSIGNE_RELECTEUR = """Tu relis une note de décision contre les preuves qui ont servi à l'écrire. Cherche ce que la note affirme sans que les preuves le disent, et ce qu'elle oublie d'important (données de démonstration, données manquantes, anomalies).
Réponds par un objet JSON : {"reserves": ["<réserve précise>", "..."]}. Liste vide si la note est fidèle aux preuves."""


def _preuves(s: Session, taille: int = 9000) -> str:
    t = "\n\n".join(s.preuves)
    return t if len(t) <= taille else t[:taille] + "\n… (preuves coupées)"


def note_type(s: Session) -> str:
    """Note écrite sans modèle : les résultats des outils, rangés sous le plan de la note. Aucun chiffre n'est reformulé."""
    preuve = lambda nom: next((p.split("] ", 1)[1] for p in s.preuves if p.startswith(f"[{nom}]")), "(non disponible)")
    return ("## Recommandation\n\nLa note ci-dessous reprend les résultats du dossier tels quels. Aucun modèle de langage n'a été utilisé : "
            "la recommandation se lit dans les indicateurs, à commencer par le gain annuel et la probabilité que la ligne soit rentable.\n\n"
            f"## Ce qui la fonde\n\n{preuve('indicateurs')}\n\n## Ce qui manque pour en être sûr\n\n{preuve('limites')}\n\n"
            f"## Prochaines actions\n\n{preuve('composition')}\n\n{preuve('file_de_revue')}\n")


def rediger(s: Session, constats: list) -> tuple:
    """(note, réserves du relecteur). La note est réécrite une fois si elle contient des nombres absents des preuves."""
    question = "Constats du pilote :\n" + "\n".join(f"- {c}" for c in constats) + "\n\nPreuves :\n" + _preuves(s)
    note = s.modele.demander(CONSIGNE_REDACTEUR, question).strip()
    s.noter("rédacteur", "note écrite", longueur=len(note))
    absents = non_fondes(note, s.preuves)
    if absents:
        note = s.modele.demander(CONSIGNE_REDACTEUR, question + "\n\nTa première version contenait des nombres absents des preuves : " + ", ".join(absents) +
                                 ". Réécris la note sans eux, ou avec les nombres exacts des preuves.\n\nPremière version :\n" + note).strip()
        s.noter("rédacteur", "note réécrite", nombres_absents=absents)
    try:
        o = mod_modele._objet_json(s.modele.demander(CONSIGNE_RELECTEUR, "Note :\n" + note + "\n\nPreuves :\n" + _preuves(s),
                                                     {"type": "object", "properties": {"reserves": {"type": "array", "items": {"type": "string"}}}, "required": ["reserves"]}))
        reserves = [texte(r).strip() for r in (o or {}).get("reserves", []) if texte(r).strip()] if isinstance(o, dict) else []
    except mod_modele.Indisponible:
        reserves = ["Le relecteur n'a pas pu être consulté (modèle indisponible)."]
    s.noter("relecteur", "relecture", reserves=reserves)
    return note, reserves


# --------------------------------------------------------------------------- l'enchaînement complet
def executer(cfg, modele=None, pas_max: int = PAS_MAX) -> dict:
    """Fait tout, de bout en bout, et écrit la note. Avec un modèle privé : pilote, rédacteur, relecteur. Sans modèle, ou
    si le modèle fait défaut : plan fixe et note type. Renvoie {"note", "mode", "nombres_non_fondes", "reserves", "fichiers", "journal"}."""
    if modele is not None and not getattr(modele, "prive", False):
        raise PermissionError("Le modèle n'est pas privé : les agents lui montreraient les tables du dossier. Le brancher sur ce poste, "
                              "ou déclarer sa machine dans parametres/modele_local.cfg.")
    s = Session(cfg, modele)
    constats, mode = [], "plan fixe, sans modèle de langage"
    if modele is not None:
        constats = piloter(s, pas_max)
        mode = f"agents sur le modèle « {getattr(modele, 'modele', '?')} »" if constats else "plan fixe : le modèle n'a pas pu piloter"
    for nom, arguments in PLAN_FIXE:                            # sans modèle : tout le plan ; avec : ce que le pilote aurait oublié d'essentiel
        if (not constats and nom not in s.faits) or (constats and nom in ESSENTIELS and nom not in s.faits):
            appeler(s, "plan fixe", nom, arguments)
    reserves = []
    if constats:
        try:
            note, reserves = rediger(s, constats)
        except mod_modele.Indisponible:
            note, mode = note_type(s), "plan fixe : le modèle n'a pas pu rédiger"
    else:
        note = note_type(s)
    absents = non_fondes(note, s.preuves)
    entete = f"# Note de décision\n\n*Écrite par : {mode}. Données : {'DÉMONSTRATION (fictives)' if cfg.demo else 'réelles'}.*\n\n"
    if absents:
        entete += ("> **Attention : nombres absents des preuves.** La note contient des nombres qui ne figurent dans aucun résultat du dossier : "
                   + ", ".join(absents) + ". Ne pas s'y fier sans les vérifier dans les tables.\n\n")
    if reserves:
        note += "\n\n## Réserves du relecteur\n\n" + "\n".join(f"- {r}" for r in reserves) + "\n"
    note = entete + note.strip() + "\n"
    d = Path(cfg.artefacts) / "agent"
    d.mkdir(parents=True, exist_ok=True)
    fichiers = {"Note de décision": d / "Note_de_decision.md", "Preuves": d / "Preuves.txt", "Journal": d / "Journal.jsonl"}
    fichiers["Note de décision"].write_text(note, encoding="utf-8")
    fichiers["Preuves"].write_text("\n\n".join(s.preuves) + "\n", encoding="utf-8")
    fichiers["Journal"].write_text("".join(json.dumps(j, ensure_ascii=False, default=str) + "\n" for j in s.journal), encoding="utf-8")
    if s.ctx is not None:
        s.ctx.depot.fichier("agent", "Note de décision", fichiers["Note de décision"], "Note écrite par les agents, ou par le plan fixe, à partir des résultats du dossier", "note")
        s.ctx.depot.fichier("agent", "Journal des agents", fichiers["Journal"], "Chaque pas : rôle, outil, arguments, résultat", "journal")
        s.ctx.depot.ecrire_manifeste()
    return {"note": note, "mode": mode, "nombres_non_fondes": absents, "reserves": reserves, "fichiers": fichiers, "journal": s.journal,
            "appels_au_modele": int(getattr(modele, "appels", 0) or 0) if modele is not None else 0}


def main(argv=None) -> int:
    import argparse

    from .config import charger
    a = argparse.ArgumentParser(prog="python -m erc.agent", description="Lance le dossier de bout en bout, piloté par le modèle hébergé chez vous, et écrit la note de décision")
    a.add_argument("--dossier")
    a.add_argument("--demo", action="store_true")
    a.add_argument("--sans-modele", action="store_true", help="plan fixe : aucun modèle de langage n'est appelé")
    a.add_argument("--pas", type=int, default=PAS_MAX, help="nombre maximal de tours du pilote")
    o = a.parse_args(argv)
    cfg = charger(dossier=o.dossier, demo=True if o.demo else None)
    modele = None
    if not o.sans_modele:
        try:
            modele, _ = mod_modele.modeles_du_reglage(mod_modele.lire_reglage(cfg), cfg=cfg)
        except ValueError as e:
            print("Modèle non utilisé :", e)
    r = executer(cfg, modele, o.pas)
    print(r["note"])
    print(f"Écrite par : {r['mode']} | appels au modèle : {r['appels_au_modele']} | pas journalisés : {len(r['journal'])}")
    print("Fichiers : " + ("demo/" if cfg.demo else "") + "artefacts/agent/ (note, preuves, journal)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
