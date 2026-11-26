"""Diagnostic du poste : ce qui est prêt, ce qui manque, et la prochaine chose à faire. Tout se passe sur ce poste.

    python -m erc.diagnostic            écrit le rapport à l'écran et dans artefacts/Diagnostic.txt
    python -m erc.diagnostic --regler   en plus : écrit parametres/modele_local.cfg d'après ce qui est trouvé sur ce poste
                                        (serveur de modèle, modèle qui tient dans la carte graphique), s'il n'existe pas encore

Fait pour un poste verrouillé, où l'on ne veut ni tâtonner ni échanger avec l'extérieur : la commande ne contacte que
ce poste (localhost), n'installe rien, ne modifie rien sans `--regler`, et dit en clair quoi faire ensuite. Le rapport
est un simple fichier texte ; il ne contient ni données du dossier, ni nom de machine, ni chemin complet.

Ce qu'elle regarde : la version de Python et les paquets ; les fichiers de l'archive (empreintes) ; les données
(réelles ou démonstration) ; la carte graphique ; les serveurs de modèle qui tournent sur ce poste et leurs modèles ;
le réglage du modèle, et s'il répond.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

from . import modele as mod_modele

RACINE = Path(__file__).resolve().parent.parent
FICHIER_EMPREINTES = "EMPREINTES.txt"
PAQUETS = [("numpy", True, "calculs"), ("pandas", True, "tables"), ("openpyxl", True, "lecture et écriture des classeurs Excel"),
           ("matplotlib", True, "figures"), ("scipy", False, "comparaison au solveur exact dans les tests"),
           ("nbformat", False, "reconstruction des notebooks"), ("notebook", False, "ouverture des notebooks (ou jupyterlab)"),
           ("jupyterlab", False, "ouverture des notebooks (ou notebook)")]
# Serveurs de modèle cherchés sur ce poste seulement, à leur port habituel.
SERVEURS = [("Ollama", 11434), ("LM Studio", 1234), ("llama-server", 8080), ("vLLM", 8000)]
# Modèles à essayer selon la mémoire de la carte graphique. Noms relevés fin 2026, NON vérifiés sur les pages officielles.
PALIERS = [(20.0, "qwen3.8:27b-q4_K_M"), (7.5, "qwen3.5:9b"), (0.0, "qwen3.5:4b")]


# --------------------------------------------------------------------------- ce que le poste a
def paquets() -> list:
    out = []
    for nom, requis, usage in PAQUETS:
        present = importlib.util.find_spec(nom) is not None
        try:
            version = importlib.metadata.version(nom) if present else None
        except importlib.metadata.PackageNotFoundError:
            version = "installé"
        out.append({"Paquet": nom, "Nécessaire": requis, "Version": version, "Sert à": usage})
    return out


def carte_graphique(commande=subprocess.run) -> dict:
    """Cartes NVIDIA vues par nvidia-smi : {"cartes": [{"nom", "memoire_go"}], "raison": pourquoi rien n'a été lu}."""
    try:
        r = commande(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        return {"cartes": [], "raison": "nvidia-smi est introuvable : pas de carte NVIDIA, ou pilote absent"}
    except Exception as e:                                     # commande bloquée par la sécurité du poste, délai dépassé…
        return {"cartes": [], "raison": f"nvidia-smi n'a pas pu être lancé ({type(e).__name__})"}
    cartes = []
    for ligne in (r.stdout or "").splitlines():
        m = re.match(r"\s*(.+?)\s*,\s*([0-9.]+)\s*$", ligne)
        if m:
            cartes.append({"nom": m.group(1), "memoire_go": round(float(m.group(2)) / 1024, 1)})
    return {"cartes": cartes, "raison": None if cartes else "nvidia-smi n'a rendu aucune carte"}


def serveurs_locaux(serveurs=SERVEURS, delai: float = 1.5) -> list:
    """Serveurs de modèle qui répondent sur ce poste (localhost seulement), avec les modèles qu'ils proposent."""
    out = []
    for nom, port in serveurs:
        url = f"http://127.0.0.1:{port}/v1"
        try:
            out.append({"Serveur": nom, "Adresse": url, "Modèles": mod_modele.ModeleLocal(url, "?", delai=delai).modeles()})
        except mod_modele.Indisponible:
            continue
    return out


# --------------------------------------------------------------------------- quel modèle tient dans la carte
def besoin_memoire_go(nom: str):
    """Mémoire qu'un modèle demande, ESTIMÉE d'après son nom (taille en milliards de paramètres, précision des poids) ;
    None si le nom ne dit pas la taille. Repère : 27 milliards en 4 bits pèsent environ 17 Go."""
    n = nom.lower()
    m = re.search(r"(?<![0-9.])(\d+(?:\.\d+)?)b(?![a-z0-9])", n.split("/")[-1])
    if not m:
        return None
    par_milliard = 2.1 if re.search(r"bf16|fp16|f16", n) else 1.1 if re.search(r"q8|fp8|8bit", n) else 0.82 if "q6" in n else 0.72 if "q5" in n else 0.62
    return round(float(m.group(1)) * par_milliard + 1.5, 1)


def choisir_modele(noms, memoire_go=None):
    """Parmi les modèles d'un serveur, le plus gros qui tient dans la carte ; sans carte connue, ou si aucun ne tient,
    le plus petit. Les modèles de plongement et ceux dont le nom ne dit pas la taille sont laissés de côté."""
    connus = [(besoin_memoire_go(n), n) for n in noms if "embed" not in n.lower() and besoin_memoire_go(n) is not None]
    if not connus:
        return None
    tiennent = [c for c in connus if memoire_go is not None and c[0] <= memoire_go]
    if tiennent:
        return max(tiennent, key=lambda c: (c[0], "qwen" in c[1].lower(), c[1]))[1]
    return min(connus, key=lambda c: (c[0], c[1]))[1]


def modele_conseille(memoire_go=None) -> str:
    return next(nom for seuil, nom in PALIERS if (memoire_go or 0.0) >= seuil)


# --------------------------------------------------------------------------- intégrité de l'archive
def empreinte(chemin: Path) -> str:
    return hashlib.sha256(Path(chemin).read_bytes()).hexdigest()


def verifier_empreintes(racine: Path = RACINE) -> dict:
    """Compare les fichiers du dossier à la liste d'empreintes livrée avec l'archive, si elle est là."""
    f = Path(racine) / FICHIER_EMPREINTES
    if not f.is_file():
        return {"etat": "sans objet", "detail": "pas de liste d'empreintes (dossier venu du dépôt, non d'une archive)"}
    modifies, absents, n = [], [], 0
    for ligne in f.read_text(encoding="utf-8").splitlines():
        if "  " not in ligne:
            continue
        somme, nom = ligne.split("  ", 1)
        n += 1
        p = Path(racine) / nom
        if not p.is_file():
            absents.append(nom)
        elif empreinte(p) != somme:
            modifies.append(nom)
    if modifies or absents:
        return {"etat": "différent", "detail": f"{len(modifies)} fichier(s) modifié(s), {len(absents)} absent(s) sur {n} : " + ", ".join((modifies + absents)[:6])}
    return {"etat": "intact", "detail": f"{n} fichiers identiques à l'archive"}


# --------------------------------------------------------------------------- le diagnostic
def diagnostiquer(cfg, commande=subprocess.run, serveurs=SERVEURS) -> dict:
    """Rapport complet : un dictionnaire de sections, et « À faire », la liste ordonnée des prochaines actions."""
    a_faire = []
    python_ok = sys.version_info >= (3, 9)
    if not python_ok:
        a_faire.append("Installer Python 3.9 ou plus récent : cette version est trop ancienne pour le dossier.")
    pq = paquets()
    manquants = [p["Paquet"] for p in pq if p["Nécessaire"] and p["Version"] is None]
    if manquants:
        a_faire.append("Installer les paquets nécessaires : pip install " + " ".join(manquants) +
                       "   (sans accès à internet : voir INSTALLATION.md, « Installer les paquets hors ligne »)")
    if not any(p["Version"] for p in pq if p["Paquet"] in ("notebook", "jupyterlab")):
        a_faire.append("Facultatif : installer Jupyter pour ouvrir les notebooks. Sans lui, tout reste accessible en ligne de commande "
                       "(python -m erc, python -m erc.composition) et par les pages HTML des artefacts.")
    gpu = carte_graphique(commande)
    memoire = max((c["memoire_go"] for c in gpu["cartes"]), default=None)
    locaux = serveurs_locaux(serveurs)
    reglage = mod_modele.lire_reglage(cfg)
    fichier = mod_modele.chemin_reglage(cfg)
    etat_modele = {"Fichier de réglage": "présent" if fichier.exists() else "absent", "Adresse": reglage.url or None, "Modèle": reglage.nom or None,
                   "Réponse": None, "À corriger": list(reglage.erreurs)}
    if reglage.url and reglage.nom:
        try:
            m, _ = mod_modele.modeles_du_reglage(reglage, cfg=cfg)
            bilan = m.verifier()
            etat_modele["Réponse"] = "prêt" if bilan["Prêt"] else "ne répond pas comme attendu"
            etat_modele["Conseils"] = bilan["Conseils"]
            if not bilan["Prêt"]:
                a_faire.append("Le modèle réglé ne répond pas comme attendu : " + (bilan["Conseils"][0] if bilan["Conseils"] else "voir python -m erc.modele --verifier"))
        except ValueError as e:
            etat_modele["Réponse"] = "refusé"
            a_faire.append(str(e))
    elif locaux:
        choix = [(s, choisir_modele(s["Modèles"], memoire)) for s in locaux]
        trouve = next(((s, n) for s, n in choix if n), None)
        if trouve:
            a_faire.append(f"Un serveur de modèle tourne sur ce poste ({trouve[0]['Serveur']}) avec le modèle « {trouve[1]} » : "
                           "lancer  python -m erc.diagnostic --regler  pour écrire le réglage et le vérifier.")
        else:
            a_faire.append(f"Un serveur de modèle tourne sur ce poste ({locaux[0]['Serveur']}) mais sans modèle utilisable : y télécharger « {modele_conseille(memoire)} » "
                           "(nom à confirmer dans la bibliothèque du serveur), puis relancer cette commande.")
    else:
        a_faire.append("Facultatif : installer un serveur de modèle sur ce poste (Ollama est le plus simple), y télécharger « " + modele_conseille(memoire) +
                       " » (nom à confirmer dans sa bibliothèque), puis lancer  python -m erc.diagnostic --regler . "
                       "Sans modèle, le dossier fonctionne : la composition des pièces s'arrête aux sources gratuites.")
    if cfg.demo:
        a_faire.append("Les extractions réelles ne sont pas trouvées : le dossier est en démonstration (données fictives). Pour les données réelles, "
                       "indiquer leur dossier une fois :  python -c \"import erc; erc.memoriser_chemins(r'CHEMIN_DES_EXTRACTIONS')\"")
    a_faire.append("Lancer le dossier :  python -m erc   puis  python -m erc.composition   (résultats dans artefacts/).")
    return {"Python": {"Version": ".".join(map(str, sys.version_info[:3])), "Convient": python_ok},
            "Paquets": pq,
            "Fichiers de l'archive": verifier_empreintes(),
            "Données": {"Mode": "démonstration (données fictives)" if cfg.demo else "données réelles"},
            "Carte graphique": {"Cartes": gpu["cartes"], "Mémoire retenue (Go)": memoire, "Remarque": gpu["raison"]},
            "Serveurs de modèle sur ce poste": locaux,
            "Modèle conseillé pour cette carte": {"À télécharger": modele_conseille(memoire),
                                                  "Remarque": "nom relevé fin 2026, non vérifié sur la page officielle ; estimation d'après la mémoire de la carte"},
            "Réglage du modèle": etat_modele,
            "À faire": a_faire}


def regler(cfg, commande=subprocess.run, serveurs=SERVEURS) -> str:
    """Écrit parametres/modele_local.cfg d'après ce qui tourne sur ce poste, s'il n'existe pas encore. Renvoie ce qui a été fait."""
    fichier = mod_modele.chemin_reglage(cfg)
    if fichier.exists():
        return f"{fichier.name} existe déjà : il n'est pas réécrit. Le corriger à la main, ou le supprimer pour le refaire."
    memoire = max((c["memoire_go"] for c in carte_graphique(commande)["cartes"]), default=None)
    for s in serveurs_locaux(serveurs):
        nom = choisir_modele(s["Modèles"], memoire)
        if not nom:
            continue
        m = mod_modele.ModeleLocal(s["Adresse"].replace("127.0.0.1", "localhost"), nom, delai=180)
        essai = m.diagnostiquer()                              # quel réglage coupe le raisonnement sur ce serveur
        corps = essai["Réglage conseillé"] if essai["Réglage conseillé"] not in (None, "{}") else ""
        texte = mod_modele.GABARIT_REGLAGE.replace("\nurl =\n", f"\nurl = {m.url}\n", 1).replace("\nnom =\n", f"\nnom = {nom}\n", 1)
        texte = texte.replace("\ncorps_supplementaire =\n", f"\ncorps_supplementaire = {corps}\n", 1)
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text(texte, encoding="utf-8")
        return (f"{fichier.name} écrit : serveur {s['Serveur']} sur ce poste, modèle « {nom} »" + (f", champs ajoutés {corps}" if corps else "") +
                ". Vérification :  python -m erc.modele --verifier")
    return "Aucun serveur de modèle avec un modèle utilisable n'a répondu sur ce poste : rien n'a été écrit."


def en_texte(rapport: dict) -> str:
    dire = lambda v: "—" if v is None else "oui" if v is True else "non" if v is False else ", ".join(map(str, v)) if isinstance(v, list) else str(v)
    lignes = ["DIAGNOSTIC DU POSTE (ERC circularité)", ""]
    for titre, contenu in rapport.items():
        if titre == "À faire":
            continue
        lignes.append(titre.upper())
        if isinstance(contenu, list):
            if not contenu:
                lignes.append("  (rien)")
            for x in contenu:
                lignes.append("  " + (" | ".join(f"{k} : {dire(v)}" for k, v in x.items()) if isinstance(x, dict) else str(x)))
        else:
            for k, v in contenu.items():
                if isinstance(v, list):
                    v = "; ".join(" ".join(f"{a}={b}" for a, b in x.items()) if isinstance(x, dict) else str(x) for x in v) or "(rien)"
                lignes.append(f"  {k} : {dire(v)}")
        lignes.append("")
    lignes.append("À FAIRE, DANS L'ORDRE")
    lignes += [f"  {i}. {a}" for i, a in enumerate(rapport["À faire"], 1)]
    return "\n".join(lignes) + "\n"


def main(argv=None) -> int:
    import argparse

    from .config import charger
    a = argparse.ArgumentParser(prog="python -m erc.diagnostic", description="Diagnostic du poste, hors ligne : ce qui est prêt, ce qui manque, quoi faire")
    a.add_argument("--dossier")
    a.add_argument("--demo", action="store_true")
    a.add_argument("--regler", action="store_true", help="écrit le réglage du modèle d'après ce qui tourne sur ce poste, s'il n'existe pas")
    o = a.parse_args(argv)
    cfg = charger(dossier=o.dossier, demo=True if o.demo else None)
    if o.regler:
        print(regler(cfg), "\n")
    texte = en_texte(diagnostiquer(cfg))
    print(texte)
    try:
        f = Path(cfg.artefacts) / "Diagnostic.txt"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(texte, encoding="utf-8")
        print("Rapport écrit dans " + ("demo/" if cfg.demo else "") + f"{cfg.artefacts.name}/{f.name}")
    except OSError as e:                                       # dossier en lecture seule : le rapport reste à l'écran
        print(f"Le rapport n'a pas pu être écrit ({type(e).__name__}) : le dossier n'est pas modifiable ici.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
