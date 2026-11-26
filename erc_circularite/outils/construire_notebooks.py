"""Construit les sept notebooks du dossier (notebooks/*.ipynb) à partir des textes écrits ci-dessous.

    python outils/construire_notebooks.py               réécrit les notebooks, sans résultats
    python outils/construire_notebooks.py --executer    les exécute aussi, en démonstration, et les enregistre avec leurs résultats
    python outils/construire_notebooks.py --executer --reel
                                                        les exécute sur les données réelles ; les copies exécutées vont dans
                                                        artefacts/notebooks/ (hors du dépôt public), notebooks/ reste intact
    python outils/construire_notebooks.py --executer 02 05     seulement les notebooks dont le nom contient 02 ou 05

Les notebooks ne contiennent aucun calcul : chaque cellule appelle le pipeline (`erc.executer`) ou une fonction
d'affichage (`erc.affichage`). Pour changer un texte ou l'ordre des cellules, modifier ce fichier puis le relancer :
le résultat est identique à chaque exécution (mêmes cellules, mêmes identifiants).

`--executer` force le mode démonstration, parce que les notebooks enregistrés dans le dossier sont publiés avec le
code : ils ne doivent montrer que des données fictives. L'exécution se fait depuis notebooks/, comme dans Jupyter.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent.parent
NOTEBOOKS = DOSSIER / "notebooks"


def md(texte: str) -> tuple:
    return ("markdown", texte.strip("\n"))


def code(texte: str) -> tuple:
    return ("code", texte.strip("\n"))


def depart(etape: str) -> tuple:
    """Première cellule de code, la même dans tous les notebooks : trouver le dossier, charger le code, exécuter le pipeline."""
    return code(f'''
import sys
from pathlib import Path

# Le dossier est celui qui contient le code (erc/) : le parent de notebooks/.
dossier = next((p for p in [Path.cwd(), *Path.cwd().parents] if (p / "erc" / "__init__.py").is_file()), Path.cwd().parent)
sys.path.insert(0, str(dossier))
import erc
from erc import affichage as aff

ctx = erc.executer(jusqua="{etape}")
''')


SUITE = "\n\n---\nNotebook suivant : **{suivant}**. Tous les fichiers affichés ici sont dans le dossier des artefacts, étape `{rep}` ; un classeur Excel du même nom réunit les tables de l'étape."

# =========================================================================== 00
N00 = ("00_Demarrage", [
    md("""
# ERC circularité · 00 · Démarrage

Ce dossier aide à décider quoi faire des FRU scrapées d'un centre de réparation et des pièces qu'elles contiennent. Pour chaque pièce d'un FRU scrapé, trois options sont comparées :

1. **Réemploi** : le FRU est ouvert avec soin, la pièce est extraite, testée, puis réutilisée en réparation.
2. **Recyclage trié** : la pièce est triée dans le bon flux et vendue au kilo à un recycleur.
3. **Laissée dans le FRU** : le FRU part tel quel chez le recycleur actuel. C'est la situation d'aujourd'hui, et la référence de tous les calculs.

Ce premier notebook exécute tout le calcul et vérifie que le dossier est en état de marche : sources lues, paramètres, résultats produits, anomalies. Il se lit sans connaître le code.
"""),
    md("""
## Ce que contient le dossier

| Élément | Contenu |
|---|---|
| `notebooks/` | Sept notebooks, à lire dans l'ordre. Ils ne calculent rien eux-mêmes : ils lancent le calcul et affichent ses résultats. |
| `erc/` | Le code du calcul, en sept étapes : sources, classement, flux, fiabilité, modèle de Rex, ligne, synthèse. |
| `parametres/` | `ERC_Parametres.xlsx`, le classeur des paramètres à saisir (temps, coûts, prix, délais), et `chemins.json`, l'emplacement des données réelles. |
| `artefacts/` | Tout ce que le calcul produit : tables (CSV), figures (PNG), un classeur Excel par étape, `manifeste.json`, et l'outil des décideurs. |
| `demo/` | La démonstration complète : sources fictives, paramètres fictifs et leurs artefacts. |
| `docs/Modele_mathematique.md` | La formulation du modèle de ligne et du modèle de Rex. |
| `outils/construire_notebooks.py` | Régénère les notebooks. |

| Notebook | Question traitée |
|---|---|
| **00 Démarrage** | Le dossier fonctionne-t-il, sur quelles données, que manque-t-il ? |
| **01 Classement et priorisation** | Quelles pièces consomme-t-on, lesquelles étudier en premier ? |
| **02 Flux d'entrée** | Combien de FRU scrapées par semaine, quelle masse par benne, l'estimation est-elle confirmée par les pesées ? |
| **03 Fiabilité** | Une pièce réparée ou récupérée tient-elle aussi bien qu'une pièce neuve ? |
| **04 Modèle de Rex** | Quelle est la probabilité qu'une pièce extraite d'un FRU scrapé soit réutilisable ? |
| **05 Ligne de démontage et de tri** | Une ligne est-elle rentable, avec quelles pièces et combien d'heures opérateur ? |
| **06 Synthèse décideurs** | Que retenir, que reste-t-il à obtenir, où est l'outil de décision ? |

La cellule suivante exécute les sept étapes (une vingtaine de secondes en démonstration). Chaque notebook commence par la même cellule, limitée à l'étape dont il a besoin.
"""),
    depart("synthese"),
    code("aff.etat(ctx)"),
    md("""
## Démonstration ou données réelles

Sans données réelles, le dossier fonctionne en **mode démonstration** : il fabrique des sources entièrement fictives (références du type `FRU-A100-R` et `P-1004`), dans les mêmes formats de fichiers que les sources réelles, et écrit tout dans `demo/`. Le mode est rappelé dans le bandeau ci-dessus, sur chaque figure et dans le manifeste. Les chiffres de démonstration ne décrivent aucun atelier : ils servent à vérifier que tout s'enchaîne et à montrer comment une donnée manquante est signalée.

**Pour travailler sur les données réelles**, exécuter une fois, dans une cellule de ce notebook :

```python
erc.memoriser_chemins(projet=r"C:\\chemin\\du\\dossier\\des\\extractions", racine=r"C:\\chemin\\du\\dossier\\des\\referentiels")
```

puis relancer le notebook en entier. `projet` est le dossier qui contient les extractions `ERC_R26_extraction_AAAAMMJJ_AAAAMMJJ.xlsx` et les sous-dossiers `Classification_matieres/`, `Extraction_R26/` et `Acquisition/` (pesées hebdomadaires, audit de démontage). `racine` est le dossier des référentiels (valorisation, fiche des FRU, fichier de fiabilité) ; s'il est omis, c'est le dossier parent de `projet`.

- Les chemins sont notés dans `parametres/chemins.json`, que tous les notebooks relisent. Les données réelles ne sont jamais copiées dans le dossier : elles sont lues là où elles se trouvent. Les résultats vont dans `artefacts/`, le classeur de paramètres dans `parametres/`.
- Les options d'analyse se mémorisent par la même commande, par exemple `erc.memoriser_chemins(projet=..., racine=..., debut="2026-01-01", fin="2026-07-01")` pour borner la période (début inclus, fin exclue), ou `ateliers_prioritaires=[...]` pour changer les ateliers étudiés en premier. **Chaque appel remplace le précédent** : redonner à chaque fois `projet`, `racine` s'il a été donné, et toutes les options voulues.
- Pour revoir la démonstration sans rien effacer, dans une cellule : `ctx = erc.executer(demo=True)`. Les autres notebooks restent sur les données réelles tant que `parametres/chemins.json` existe ; le supprimer ramène tout le dossier à la démonstration.

**Le dépôt du code est public.** Les artefacts réels (`artefacts/`) et le classeur de paramètres (`parametres/`) en sont exclus, mais un notebook exécuté sur données réelles contient ses résultats : ne pas l'enregistrer dans le dépôt. La commande `python outils/construire_notebooks.py --executer` remet les sept notebooks dans leur état de démonstration.
"""),
    md("""
## Périmètre de cette exécution

Mode, période couverte par les extractions, volumes lus, règle qui date un scrap, emplacement des fichiers. **À vérifier en premier** : la période et le nombre de jours extraits, parce que tous les volumes annuels du dossier en découlent.

La ligne « Classeur de paramètres » dit s'il existait au début de cette exécution : « absent » à la toute première, où il vient d'être créé (section suivante). Les emplacements sont abrégés : seul le dernier élément d'un chemin extérieur au dossier est affiché.
"""),
    code('aff.notes(ctx, "sources", "Périmètre")'),
    md("""
## État des sources

Une ligne par fichier attendu : chargé, absent ou en erreur, et ce à quoi il sert. Aucune source n'est obligatoire : un fichier absent laisse vides les tables qui en dépendent, il n'arrête pas le calcul et n'est jamais remplacé par des zéros.

**Décision éclairée** : quelles extractions ou quels relevés demander avant de se fier aux résultats. Sans pesées, le flux n'est pas vérifié (notebook 02) ; sans le nombre de pièces posées, aucun taux de défaillance (notebook 03) ; sans audit de démontage, la probabilité de réemploi reste une hypothèse (notebook 04).
"""),
    code('aff.table(ctx, "sources", "État des sources")'),
    md("""
## Le classeur de paramètres

Les extractions ne contiennent ni les temps de démontage, ni les coûts, ni les prix des recycleurs, ni les délais d'approvisionnement. Ces paramètres se saisissent dans **`parametres/ERC_Parametres.xlsx`** (en démonstration : `demo/parametres/ERC_Parametres.xlsx`).

- **Création** : le classeur est créé à la première exécution, pré-rempli avec les FRU scrapées des ateliers prioritaires et, pour chacune, ses pièces de plus forte valeur et une ligne `CARCASSE` (le châssis et le reste du FRU). **Il n'est jamais réécrit ensuite** : ce qui y est saisi reste. Pour repartir d'un gabarit neuf, renommer l'ancien classeur et relancer.
- **Ce qu'on écrit dans une cellule** :
    - `45` : une valeur ;
    - `30|70` : une plage, du plus bas au plus haut (toutes les valeurs également plausibles) ;
    - `30|45|70` : une plage avec sa valeur la plus plausible, dans l'ordre bas, mode, haut ;
    - cellule vide : inconnu. Le calcul cherche la valeur dans les données (poids, prix du référentiel, MMICV), sinon la laisse inconnue. Jamais zéro.
- **Couleurs** : les colonnes à en-tête **gris** (cellules grises) sont des informations tirées des données, pour repère : les chiffres qu'elles contiennent ne sont pas relus par le calcul. Seule exception : les colonnes qui désignent la ligne (`FRU`, `Pièce`, `Paramètre`, `Référence`) sont relues, ne pas les modifier. Les colonnes à en-tête **bleu** (cellules jaune pâle) sont à saisir.
- **Colonne `Source`** : noter d'où vient chaque valeur (devis, audit du jour J, service qui l'a fournie). Dans les onglets `Ligne`, `FRU` et `Pieces`, la source est reprise telle quelle dans la provenance des paramètres (notebook 05). Une ligne n'a qu'une cellule `Source` : elle vaut pour toutes les valeurs saisies sur cette ligne.
- **Onglets** : `Lisez_moi` (mode d'emploi), `Ligne` (paramètres de la ligne et valeurs par défaut), `FRU` (un type de FRU par ligne ; retirer une ligne l'exclut du modèle), `Pieces` (les pièces de chaque FRU), `Supply` (délais d'approvisionnement), `Ateliers` (rattachement manuel d'un FRU à un atelier), `Chiffres_a_verifier` (chiffres annoncés à comparer aux extractions).
- **Après une saisie** : enregistrer le classeur, puis relancer le notebook. Le notebook 05 montre, paramètre par paramètre, ce qui est saisi, tiré des données ou encore manquant.

Les deux cellules suivantes affichent le mode d'emploi contenu dans le classeur et l'onglet `Ligne` tel qu'il est sur le disque. En démonstration, les valeurs sont fictives et quelques cellules sont laissées vides exprès.
"""),
    code('aff.classeur(ctx, "Lisez_moi")'),
    code('aff.classeur(ctx, "Ligne")'),
    md("""
## Les artefacts produits

Tout ce que le calcul produit est écrit dans le dossier des artefacts, une étape par sous-dossier :

- une **table** = un fichier CSV (séparateur point-virgule, virgule décimale : il s'ouvre directement dans Excel) ;
- un **classeur Excel par étape**, qui réunit ses tables ;
- les **figures** en PNG, les **notes** de calcul en JSON ;
- `manifeste.json`, la liste ci-dessous.

Les notebooks n'affichent que ce qui est dans ce dépôt : **ce qu'on voit à l'écran est ce qui est sur le disque**. Sous chaque table figure le fichier d'où elle vient. Une case vide est une valeur inconnue. Les tables longues sont coupées aux 30 premières lignes ; le fichier, lui, est complet.
"""),
    code("aff.manifeste(ctx)"),
    md("""
## Anomalies

Un calcul qui échoue n'arrête pas le pipeline : il est inscrit ici, et le résultat correspondant reste vide au lieu d'être inventé. **Table vide = tout a été calculé.** Une anomalie se traite avant de lire les résultats de l'étape concernée.
"""),
    code("aff.anomalies(ctx)"),
    md("""
## Ce que les données ne disent pas

À garder en tête dans tous les notebooks ; la table vient de l'étape de synthèse.

- Le **MMICV** est un coût standard : ni un prix de revente, ni la valeur d'une pièce réemployée.
- Le **nombre de pièces par FRU** est inconnu avant un audit de démontage : les extractions ne donnent qu'un minimum.
- Le **fichier de fiabilité** ne contient que des défaillances : il ne donne pas de durée de vie.
- Les **valeurs** annoncées sont des estimations, distinctes de recettes constatées.
- Le **banc d'essai** du modèle de Rex est une simulation.
"""),
    code('aff.table(ctx, "synthese", "Limites et lecture")'),
    md("---\nNotebook suivant : **01_Classement_et_priorisation**."),
])

# =========================================================================== 01
N01 = ("01_Classement_et_priorisation", [
    md("""
# ERC circularité · 01 · Classement et priorisation

**Question** : quelles pièces les ateliers consomment-ils, pour quelle valeur, et lesquelles se retrouvent dans les FRU scrapées ?

**Décision éclairée** : la liste courte des pièces et des types de FRU à étudier en premier, celle qui entre dans le classeur de paramètres et dans le modèle de ligne (notebook 05).

**Limites** : la valeur utilisée ici est le MMICV, un coût standard. Il classe les pièces entre elles ; il ne dit pas ce que rapporte un réemploi.
"""),
    depart("classement"),
    code("aff.etat(ctx)"),
    md("""
## 1. Les pièces consommées, classées par valeur

Une ligne par pièce consommée sur la période, tous ateliers confondus. **MMICV total** = quantité consommée × MMICV unitaire.

**Lecture** : les premières lignes concentrent l'essentiel du coût standard consommé ; ce sont les pièces dont le réemploi mérite d'être chiffré.

**Limites** : le MMICV est un coût standard, une référence provisoire : ni un prix de revente, ni une valeur de réemploi ; sa devise reste à confirmer. Une pièce sans MMICV connu garde une valeur vide et n'est pas classée (elle n'est pas comptée à zéro). Le type de déchet, la benne et le poids viennent du classement matière, avec son niveau de preuve.
"""),
    code('aff.figures(ctx, "classement", "Top MMICV")'),
    code('''
aff.table(ctx, "classement", "Classement tous ateliers", colonnes=["Référence", "Description", "Ateliers", "Pièces", "PO", "MMICV unitaire (USD)",
          "Source MMICV", "MMICV total (USD)", "Part du MMICV total", "Catégorie proposée", "Benne", "Poids unitaire (kg)", "Niveau de preuve"])
'''),
    md("Le même classement, limité à chaque atelier prioritaire (dix premières lignes) :"),
    code('''
for atelier in ctx.cfg.ateliers_prioritaires:
    display(aff.table(ctx, "classement", f"Classement {atelier}", n=10, colonnes=["Référence", "Description", "Pièces", "MMICV unitaire (USD)", "MMICV total (USD)", "Part du MMICV total"]))
'''),
    md("""
## 2. La période est-elle complète ? Les chiffres annoncés tiennent-ils ?

Avant de discuter de valeur, se mettre d'accord sur les volumes. La première table dit, mois par mois, combien de jours sont couverts par les extractions : **un mois incomplet n'est jamais comparé à un chiffre mensuel**. La seconde compare les chiffres annoncés en réunion (saisis dans l'onglet `Chiffres_a_verifier` du classeur de paramètres) aux pièces réellement sorties chaque mois complet.

**Lecture** : un écart négatif signifie que les extractions montrent moins de pièces que le chiffre annoncé. **Limite** : la comparaison cherche un motif dans la description des pièces ; vérifier la colonne « Références » pour s'assurer que les bonnes pièces sont comptées.
"""),
    code('aff.table(ctx, "classement", "Mois calendrier")'),
    code('aff.table(ctx, "classement", "Chiffres à vérifier")'),
    md("""
## 3. Les FRU scrapées : le gisement

FRU scrapées sur la période, par type, avec leur poids. C'est le gisement que la ligne de démontage et de tri aurait à traiter.

**Lecture** : masse scrapée = nombre de FRU × poids de la fiche du FRU ; elle reste vide si le poids est inconnu. **Limite** : la date qui fait entrer un FRU dans la période dépend d'une règle à confirmer ; elle est rappelée dans les notes en fin de notebook.
"""),
    code('aff.table(ctx, "classement", "FRU scrapées")'),
    md("""
## 4. Quelles pièces dans quels FRU ?

Par couple (type de FRU, pièce), ce que montrent les consommations en réparation :

- **Réparations du FRU** : nombre d'ordres de réparation de ce type de FRU qui ont consommé au moins une pièce ;
- **Part des réparations** : part de ces réparations où la pièce a été changée ;
- **Pièces consommées** et **Réparations du FRU** : la base de la probabilité de défaut utilisée par le modèle de Rex (notebook 04) ;
- **Max par PO** : la plus grande quantité de la pièce consommée sur une même réparation.

**Limite essentielle** : le nombre de pièces par FRU est **inconnu avant un audit de démontage**. « Max par PO » n'est qu'un minimum : un FRU peut contenir quatre exemplaires d'une pièce dont on n'a jamais changé plus de deux à la fois.
"""),
    code('aff.table(ctx, "classement", "Couples FRU x pièce")'),
    md("La table suivante retourne la question : pour chaque pièce, combien de FRU scrapées l'ont dans leur nomenclature de consommation."),
    code('aff.table(ctx, "classement", "Composants des FRU scrapées")'),
    md("""
## 5. Pré-sélection des pièces

Chaque pièce est décrite par plusieurs critères, sans pondération imposée :

- **valeur** : MMICV total consommé ;
- **gisement** : FRU scrapées dont la nomenclature contient la pièce ;
- **risque matière** (0 à 1) : présence de matières premières critiques ou stratégiques selon le type de pièce reconnu dans sa description ;
- **risque d'approvisionnement** (0 à 1) : tiré du délai fourni par les achats (onglet `Supply`), sinon d'une valeur par défaut selon le type de pièce ;
- **fiabilité du réemploi** : ajoutée au notebook 03, quand le fichier de fiabilité le permet.

Une pièce est **sur le front de Pareto** quand aucune autre ne fait au moins aussi bien sur tous les critères et mieux sur au moins un : ce sont les candidates à examiner en premier. Une pièce sans donnée sur un critère y est classée au plus bas. La « note à poids égaux » n'est qu'indicative.

**Limites** : le risque matière repose sur une composition qualitative par type de pièce (présence, pas de teneur), à confirmer par la fiche matière du fabricant. Un critère sans donnée est laissé de côté ; les notes disent lesquels sont actifs.
"""),
    code('aff.figures(ctx, "classement", "Pré-sélection")'),
    code('''
aff.table(ctx, "classement", "Priorisation", colonnes=["Référence", "Description", "Sur le front de Pareto", "MMICV total (USD)", "FRU scrapées (nomenclature)",
          "Score risque matière (0-1)", "Risque supply retenu", "Source supply retenue", "Note (poids égaux, indicatif)", "Type de pièce", "CRM", "Ateliers"])
'''),
    md("## Notes de l'étape\n\nSource des FRU scrapées, critères actifs et inactifs, création du classeur de paramètres."),
    code('aff.notes(ctx, "classement")'),
    md(SUITE.format(suivant="02_Flux_entree", rep="01_classement")),
])

# =========================================================================== 02
N02 = ("02_Flux_entree", [
    md("""
# ERC circularité · 02 · Flux d'entrée

**Question** : que contient le flux de déchets des ateliers, combien de FRU sont scrapées chaque semaine, et la masse estimée à partir des consommations est-elle confirmée par les pesées ?

**Décision éclairée** : à quelle granularité (quelle benne, quel type de déchet) le modèle de ligne peut être utilisé. Un flux dont l'estimation n'est pas confirmée par les pesées n'alimente pas le modèle.

Ce notebook présente, dans l'ordre, les deux tableaux demandés par le responsable du projet, puis le flux des FRU scrapées.
"""),
    depart("flux"),
    code("aff.etat(ctx)"),
    md("""
## Tableau 1 · Composant, FRU, type de déchet

Une ligne par couple (FRU, composant) observé dans les consommations : type de déchet, benne, quantité et poids.

**Lecture** : pour un FRU donné, la table dit dans quelle benne part chaque pièce changée et quelle masse cela représente. **Limites** : le type de déchet et la benne viennent du classement matière, dont le niveau de preuve est indiqué ; une pièce sans poids unitaire a une masse vide, elle n'est pas comptée à zéro.
"""),
    code('''
aff.table(ctx, "flux", "Composant FRU type de déchet", colonnes=["FRU", "Description FRU", "Atelier du FRU", "Référence", "Description", "Type de déchet", "Benne",
          "Pièces sur ce FRU", "Poids unitaire (kg)", "Source poids", "Niveau de preuve", "Kg sur ce FRU (poids connus)"])
'''),
    md("La même information, résumée par benne et type de déchet. Un type dont aucune référence n'a de poids connu est écrit « poids inconnu » sur la figure ; dans la table, sa masse reste vide."),
    code('aff.figures(ctx, "flux", "Pièces et masse par type de déchet")'),
    code('aff.table(ctx, "flux", "Synthèse par benne")'),
    md("""
## Tableau 2 · Estimé contre pesé

Pour chaque semaine et chaque flux : la valeur estimée, la valeur mesurée, la marge d'erreur, les causes possibles de l'écart et une colonne pour la cause constatée.

- **Estimé** = pièces consommées × poids unitaires. **Bas** : seules les pièces au poids connu sont comptées. **Haut** : les pièces sans poids sont comptées au poids moyen du flux. La **marge d'erreur** est la moitié de l'écart entre haut et bas : elle vient uniquement des poids manquants.
- **Dans la marge** : « oui » si la pesée, avec son incertitude, tombe entre le bas et le haut de l'estimation.
- **Causes candidates** : proposées automatiquement selon le sens de l'écart, la part de poids manquants, une semaine incomplète, ou un écart qui se résorbe en cumul.
- **Cause constatée (à saisir)** : ce que l'atelier a constaté sur place. Elle se saisit dans le fichier des pesées (`Acquisition/pesees_hebdo.csv`), dans une colonne facultative nommée `Cause constatée`, sur la ligne de la pesée ; elle est reportée ici à chaque exécution et reste vide tant que rien n'est saisi. Écrire dans la table elle-même ne sert à rien : elle est réécrite à chaque exécution.

Les semaines comparables (une pesée et une estimation) sont affichées d'abord ; la table complète (toutes les semaines) suit.

**Limites** : la marge ne couvre pas l'incertitude des poids unitaires eux-mêmes, tant qu'elle n'est pas mesurée. Une benne partagée avec d'autres ateliers ou d'autres déchets fausse la comparaison : vérifier le périmètre de chaque pesée.
"""),
    code('''
colonnes = ["Semaine", "Flux", "Estimé central (kg)", "Masse mesurée (kg)", "Marge d'erreur (± kg)", "Écart (%)", "Dans la marge", "Écart cumulé (%)",
            "Cause constatée (à saisir)", "Causes candidates de l'écart"]
aff.table(ctx, "flux", "Estimé contre pesé", colonnes=colonnes, ou={"Dans la marge": ["oui", "non"]})
'''),
    code('aff.figures(ctx, "flux", ["Estimé contre pesé", "Cumul estimé contre pesé"])'),
    code('aff.table(ctx, "flux", "Estimé contre pesé", colonnes=colonnes + ["Estimé bas (kg)", "Estimé haut (kg)", "Couverture poids", "Jours extraits", "Périmètre", "Commentaire"])'),
    md("""
### Verdict par flux

Un flux est jugé **utilisable par le modèle** quand il compte au moins trois semaines comparées et que l'écart cumulé final ne dépasse pas 15 %. En dessous de trois semaines, il n'y a pas assez de pesées pour conclure ; au-delà de 15 %, il faut corriger la cause dominante avant d'aller plus loin.

**Décision éclairée** : poursuivre les pesées, élargir ou réduire le périmètre d'une benne, compléter les poids unitaires.
"""),
    code('aff.table(ctx, "flux", "Verdict par flux")'),
    md("""
## FRU scrapées par semaine

C'est le flux d'entrée du modèle de ligne : nombre de FRU scrapées chaque semaine, par type. Une semaine extraite sans scrap compte pour zéro ; une semaine incomplète (moins de sept jours extraits) est signalée et ne sert pas au calcul du scrap annuel.

**Lecture** : l'irrégularité d'une semaine à l'autre compte autant que la moyenne. Une ligne dimensionnée sur la moyenne perd des heures les semaines creuses et laisse des FRU les semaines chargées (chiffré au notebook 05).
"""),
    code('aff.figures(ctx, "flux", "FRU scrapées par semaine")'),
    code('aff.table(ctx, "flux", "FRU scrapées par semaine", n=12)'),
    md("""
## Scrap annuel par type de FRU

Moyenne hebdomadaire des semaines complètes × 52, avec un intervalle à 90 % obtenu en ré-échantillonnant les semaines observées. Ces trois valeurs (bas, moyen, haut) sont reprises par le modèle de ligne quand le scrap annuel n'est pas saisi dans le classeur de paramètres.

**Limite** : l'intervalle ne reflète que l'irrégularité des semaines observées. Une période courte, une saisonnalité ou un changement de politique de scrap n'y sont pas.
"""),
    code('aff.figures(ctx, "flux", "Scrap annuel par type de FRU")'),
    code('''
aff.table(ctx, "flux", "Scrap annuel", colonnes=["FRU", "Semaines complètes", "Moyenne hebdo", "Écart-type hebdo", "Scrap annuel bas (5 %)",
          "Scrap annuel moyen", "Scrap annuel haut (95 %)", "Note"])
'''),
    md("""
## Prévision du flux de la semaine suivante

Pour chaque type de FRU et chaque méthode : la moyenne attendue et des quantiles (q10 à q90) du nombre de FRU scrapées la semaine suivante. Les méthodes sont celles des séries à faibles effectifs et à nombreux zéros : moyenne de l'historique, Croston et ses variantes, un taux propre à chaque type tiré vers celui des autres (gamma-Poisson), et un modèle structurel (FRU arrivées à une décision × taux de scrap).

**Lecture** : comparer les méthodes entre elles avant d'en retenir une ; voir la table suivante.
"""),
    code('aff.table(ctx, "flux", "Prévision des FRU scrapées", n=12)'),
    md("""
## Que valent ces prévisions ?

Chaque semaine est prévue avec les seules semaines précédentes, puis comparée à ce qui s'est passé.

| Colonne | Lecture |
|---|---|
| Prévisions | nombre de (type de FRU, semaine) sur lesquels les méthodes sont notées : les mêmes pour toutes |
| Prévisions de la méthode | ce que cette méthode a su prévoir ; le modèle structurel ne prévoit pas un type dont les arrivées sont inconnues |
| Écart quadratique relatif | erreur rapportée à celle de la simple moyenne ; sous 1, la méthode fait mieux |
| Perte de quantile | note la loi entière, pas seulement la moyenne ; plus bas est mieux |
| Couverture 80 % | part des semaines tombées entre q10 et q90 ; doit être proche de 80 %, un peu au-dessus pour des comptages |
| Biais | prévision moins réalité, en moyenne ; proche de 0 |

**Limite** : sur un flux régulier, aucune méthode ne bat la moyenne, et c'est normal. Aucun modèle de fondation n'a été exécuté pour ce dossier. Les méthodes plus riches ne servent que si le flux change de niveau ou suit le volume des réparations. Les modèles de fondation de séries temporelles (Chronos, TimesFM, Moirai, Toto, Timestral) se comparent avec la même table en les enregistrant par `erc.prevision.enregistrer_modele` sur un poste qui dispose de leurs poids.
"""),
    code('aff.table(ctx, "flux", "Évaluation des prévisions")'),
    md("## Notes de l'étape\n\nRègle qui date un scrap, granularité du suivi (par benne ou par type de déchet), nombre de semaines pesées."),
    code('aff.notes(ctx, "flux")'),
    md(SUITE.format(suivant="03_Fiabilite", rep="02_flux")),
])

# =========================================================================== 03
N03 = ("03_Fiabilite", [
    md("""
# ERC circularité · 03 · Fiabilité

**Question** : une pièce réparée ou récupérée, reposée sur un FRU, tombe-t-elle en panne plus vite qu'une pièce neuve ?

**Décision éclairée** : pour quelles références le réemploi est acceptable du point de vue de la tenue en service, et quelles précautions il demande (test, âge maximal du donneur).

**Ce que le fichier de fiabilité peut dire, et ce qu'il ne peut pas dire** : il ne contient que des **défaillances précoces**, aucune pièce encore en service. Il donne donc la *forme* de la défaillance (plutôt au début, au hasard, ou par usure) et, si l'on connaît le nombre de pièces posées sur la même période, un *taux de défaillance précoce* par origine de pièce. Il ne donne pas de durée de vie. L'origine d'une pièce posée (neuve, réparée, récupérée) est lue dans le suffixe de sa référence.
"""),
    depart("fiabilite"),
    code("aff.etat(ctx)"),
    md("""
## 1. Taux de défaillance précoce, par référence et par origine

Défaillances précoces rapportées aux pièces posées sur la même période. Le point est le taux moyen, le trait son intervalle à 90 %.

**Lecture** : comparer, pour une même référence, la pièce neuve aux pièces réparées ou récupérées. Deux intervalles qui se recouvrent ne permettent pas de conclure. La colonne « Rapport au neuf » divise le taux d'une origine par celui de la pièce neuve : 2 signifie deux fois plus de défaillances précoces. Quand la table donne aussi un rapport bas et un rapport haut, ils encadrent ce rapport : si 1 est entre les deux, l'écart avec la pièce neuve n'est pas établi.

**Limites** : sans le nombre de pièces posées, aucun taux n'est calculé et la figure n'est pas produite. Avec peu de pièces posées, l'intervalle est large : c'est l'information, pas un défaut.
"""),
    code('aff.figures(ctx, "fiabilite", "Taux de défaillance précoce")'),
    code('''
aff.table(ctx, "fiabilite", "Fiabilité par référence", colonnes=["Référence", "Origine posée", "Défaillances ELF", "Pièces posées (même période)",
          "Taux ELF moyen", "IC90 bas", "IC90 haut", "Rapport au neuf (taux)", "Rapport bas (5 %)", "Rapport haut (95 %)", "Lecture du rapport",
          "elf_days médiane", "Part à J0 (DOA)"])
'''),
    md("""
## 2. À quelle vitesse surviennent les défaillances ?

Courbes de Kaplan-Meier des références qui cumulent le plus de défaillances, une courbe par origine.

**Lecture** : une courbe qui descend plus tôt signale des défaillances plus rapides après la pose. **Limite** : toutes les courbes finissent à zéro, parce que le fichier ne contient que des pièces qui ont défailli. Ce ne sont ni des durées de vie ni des probabilités de panne.
"""),
    code('aff.figures(ctx, "fiabilite", "Kaplan-Meier")'),
    md("""
## 3. Forme de la défaillance (Weibull)

La forme *k* dit comment le risque évolue avec l'âge de la pièce :

- *k* < 1 : les défaillances surviennent surtout au début. Une pièce qui a déjà fonctionné est plus sûre qu'une neuve ; un test avant réemploi est utile.
- *k* proche de 1 : le risque ne dépend pas de l'âge. Le réemploi est neutre.
- *k* > 1 : le risque croît avec l'âge (usure). Le réemploi n'a de sens que si l'âge de la pièce donneuse est connu et faible.

**Limites** : *k* est estimé sur des défaillances précoces seulement ; il décrit le début de vie. Avec moins de trois défaillances, il n'est pas calculé. Quand l'intervalle d'incertitude sur *k* n'est pas tracé, c'est qu'il n'est pas calculé : avec une poignée de défaillances, *k* est imprécis.
"""),
    code('aff.figures(ctx, "fiabilite", "Forme de Weibull")'),
    code('''
aff.table(ctx, "fiabilite", "Fiabilité par référence", colonnes=["Référence", "Origine posée", "elf_days renseigné", "Forme Weibull k", "k bas (5 %)", "k haut (95 %)",
          "Lecture de la forme", "Note"])
'''),
    md("""
## 4. Ce que change l'âge de la pièce donneuse (illustration)

Calcul théorique, sur une échelle de temps arbitraire : probabilité qu'une pièce déjà âgée tienne encore la durée de garantie, selon la forme *k*. **Ce ne sont pas des données de l'atelier** : la figure sert seulement à lire la précédente.

Les a priori physiques rappellent, pour deux familles de pièces, le mécanisme d'usure attendu et les paramètres à lire sur la fiche du fabricant.
"""),
    code('aff.figures(ctx, "fiabilite", "Âge du donneur (illustration)")'),
    code('aff.table(ctx, "fiabilite", "A priori physiques")'),
    md("""
## 5. La pré-sélection, avec la fiabilité

La pré-sélection du notebook 01, complétée du critère « fiabilité du réemploi » pour les références où un rapport au neuf a pu être calculé. Le front de Pareto peut donc changer.

**Lecture** : la colonne « Fiabilité réemploi (1/rapport) » est l'inverse du rapport au neuf, pris sur l'origine la plus favorable (réparée ou récupérée). Au-dessus de 1 : moins de défaillances précoces que la pièce neuve ; en dessous : davantage.

**Limites** : le critère n'existe que pour les références présentes dans le fichier de fiabilité avec une origine réparée ou récupérée ; ailleurs il reste vide et la pièce y est classée au plus bas. Il ne tient pas compte de l'incertitude du rapport : fondé sur deux ou trois défaillances, il est fragile (voir les intervalles de la section 1).
"""),
    code('aff.figures(ctx, "fiabilite", "Pré-sélection avec fiabilité")'),
    code('''
aff.table(ctx, "fiabilite", "Priorisation avec fiabilité", colonnes=["Référence", "Description", "Sur le front de Pareto", "MMICV total (USD)", "FRU scrapées (nomenclature)",
          "Score risque matière (0-1)", "Risque supply retenu", "Fiabilité réemploi (1/rapport)", "Note (poids égaux, indicatif)"])
'''),
    md("## Notes de l'étape\n\nNombre de défaillances lues, présence du dénominateur (pièces posées), fenêtre d'observation, durée de garantie utilisée."),
    code('aff.notes(ctx, "fiabilite")'),
    md(SUITE.format(suivant="04_Modele_de_Rex", rep="03_fiabilite")),
])

# =========================================================================== 04
N04 = ("04_Modele_de_Rex", [
    md("""
# ERC circularité · 04 · Modèle de Rex

**Question** : quand on extrait une pièce d'un FRU scrapé, quelle est la probabilité *q* qu'elle soit réutilisable ?

Tout le reste du choix entre réemploi et recyclage se mesure (valeur de la pièce, temps d'extraction et de test, prix au kilo). *q* est la seule grandeur qu'il faut estimer : le « modèle de Rex » est le modèle qui l'estime, par couple (type de FRU, pièce).

**Décision éclairée** : quelles pièces tester en priorité pendant l'audit de démontage, et quelle valeur de *q* transmettre au modèle de ligne (notebook 05).

**Comment il fonctionne** : il part d'un *a priori* tiré de la consommation, puis le corrige avec les résultats de l'audit de démontage (pièces testées, pièces bonnes). Plus l'audit avance, plus l'a priori s'efface. La formulation complète est dans [docs/Modele_mathematique.md](../docs/Modele_mathematique.md), section 8.
"""),
    depart("rex"),
    code("aff.etat(ctx)"),
    md("""
## 1. L'a priori tiré de la consommation

Avant tout audit, la seule information est la consommation en réparation : une pièce souvent changée est souvent défectueuse.

- **p_défaut** = pièces consommées ÷ (réparations du FRU × pièces par FRU), corrigé de la part des remplacements faits par précaution ;
- **q0** = (1 − p_défaut), corrigé d'un facteur « FRU scrapé plus abîmé qu'un FRU réparé », de la casse au démontage et du rendement du test.

**Limites** : le nombre de pièces par FRU (`n_par_fru`) est inconnu avant un audit de démontage ; s'il n'est pas saisi, le calcul prend le maximum observé sur une réparation, qui n'est qu'un minimum, et le signale. Les correctifs non saisis prennent une valeur neutre, signalée dans la colonne « Correctifs ». L'a priori est donc une hypothèse de départ, pas une mesure.
"""),
    code('aff.table(ctx, "rex", "A priori (consommation)")'),
    md("""
## 2. L'audit de démontage

Les données qui entraînent le modèle : pour chaque lot audité, le type de FRU, la pièce, le nombre de pièces testées et le nombre de pièces bonnes. Fichier attendu : `Acquisition/audit_demontage.csv` (colonnes `Date;Type de FRU;Pièce;Pièces testées;Pièces bonnes`).

**Limite** : sans ce fichier, la suite du notebook ne montre que l'a priori.
"""),
    code('aff.table(ctx, "rex", "Audit de démontage", n=10)'),
    md("""
## 3. La probabilité de réemploi après l'audit

Pour chaque couple (type de FRU, pièce) : la valeur de *q* retenue, son intervalle à 90 %, l'a priori de départ et le nombre de pièces testées.

**Lecture** : quand l'audit a porté sur la pièce, le point bleu s'écarte du losange (l'a priori) et l'intervalle se resserre. Quand aucune pièce n'a été testée, la valeur n'est que l'a priori et son intervalle est large : ce sont les pièces à tester en priorité si leur valeur est élevée.

**Limite** : *q* est une moyenne par type de FRU et par pièce. Il ne tient pas compte de l'âge du FRU ni du motif de scrap.
"""),
    code('aff.figures(ctx, "rex", "Probabilité de réemploi")'),
    code('''
aff.table(ctx, "rex", "A posteriori", colonnes=["Type de FRU", "Pièce", "q0", "Pièces testées", "Pièces bonnes", "q moyen", "q bas (5 %)", "q haut (95 %)",
          "Poids des données", "Transmis au modèle de ligne"])
'''),
    md("""
## 4. Le modèle prédit-il bien ?

Chaque lot de l'audit est d'abord prédit avec ce que le modèle savait avant, puis sert à le mettre à jour : aucune donnée ne sert à la fois à apprendre et à noter. Le modèle retenu (Bêta-binomial) est comparé à deux références simples : l'a priori seul, jamais mis à jour, et la fréquence observée, sans a priori.

**Lecture** : Brier, log-perte et écart absolu moyen doivent être les plus bas possible ; la couverture de l'intervalle à 90 % doit être proche de 90 %. Si une référence simple fait aussi bien ou mieux que le modèle retenu, c'est que l'a priori n'apporte rien sur ces données : le dire, et revoir sa force (section suivante).

**Limite** : avec quelques dizaines de lots, les écarts entre modèles sont fragiles.
"""),
    code('aff.figures(ctx, "rex", "Métriques par modèle")'),
    code('aff.table(ctx, "rex", "Métriques")'),
    md("""
### Force de l'a priori (N0)

N0 dit combien de pièces testées « pèse » l'a priori. La table montre la qualité de prédiction pour plusieurs valeurs de N0 ; la figure marque la valeur utilisée par le modèle.

**Lecture** : si la valeur utilisée n'est pas celle qui donne la meilleure prédiction, la note sous la figure le dit. C'est un réglage à revoir quand l'audit réel sera disponible, pas avant.
"""),
    code('aff.figures(ctx, "rex", "Réglage de N0")'),
    code('aff.table(ctx, "rex", "Réglage de N0")'),
    md("""
## 5. Banc d'essai synthétique des règles de décision

**Simulation, pas des données de l'atelier.** Le banc d'essai fabrique une pièce dont la vraie proportion de pièces bonnes est connue du simulateur, donne au modèle un a priori trop pessimiste, et compare trois règles de décision :

- **A priori seul** : décide une fois pour toutes sur l'a priori ;
- **Glouton** : suit la moyenne estimée ;
- **Thompson** : tire une valeur plausible de *q* à chaque pièce, ce qui conduit à tester de temps en temps une pièce jugée mauvaise.

**Lecture** : le regret est le gain perdu par rapport à une règle qui connaîtrait la vraie proportion. On n'apprend l'état d'une pièce que si on la teste : une règle qui ne teste jamais une pièce jugée mauvaise ne corrige jamais son erreur.

**Limite** : le banc d'essai démontre la méthode sur un cas construit. Il ne dit rien des pièces de l'atelier.
"""),
    code('aff.figures(ctx, "rex", "Banc d\'essai (regret)")'),
    code('aff.table(ctx, "rex", "Banc d\'essai des politiques")'),
    md("## Notes de l'étape\n\nNombre de lots et de pièces de l'audit, force de l'a priori, paramètres du banc d'essai synthétique."),
    code('aff.notes(ctx, "rex")'),
    md(SUITE.format(suivant="05_Ligne_demontage_tri", rep="04_rex")),
])

# =========================================================================== 05
N05 = ("05_Ligne_demontage_tri", [
    md("""
# ERC circularité · 05 · Ligne de démontage et de tri

**Question** : faut-il installer une ligne de démontage et de tri des FRU scrapées ? Avec quelles pièces en réemploi, lesquelles en recyclage trié, et combien d'heures opérateur ?

**Décision éclairée** : installer ou non la ligne, la dimensionner en heures, choisir les types de FRU à traiter et les pièces à extraire.

**Principe du modèle** : chaque FRU scrapé reçoit un plan (une option par pièce : réemploi, recyclage trié, ou laissée dans le FRU). La ligne a un coût fixe (installation amortie, frais annuels) et une capacité en heures opérateur. Le modèle choisit les plans qui maximisent le gain par rapport à la situation actuelle, où tout part chez le recycleur actuel. La formulation (ensembles, paramètres, variables, objectif, contraintes, hypothèses) est dans [docs/Modele_mathematique.md](../docs/Modele_mathematique.md).

**Règle tenue partout** : un paramètre inconnu n'est jamais remplacé par zéro. L'option concernée reste « inconnue », et un type de FRU qu'on ne peut pas calculer est déclaré « incomplet » et sorti du calcul.
"""),
    depart("ligne"),
    code("aff.etat(ctx)"),
    md("""
## 1. Paramètres et provenance

Chaque paramètre du modèle arrive avec sa provenance : **saisi** dans le classeur de paramètres, **tiré des données** (poids du classement matière, prix du référentiel des grades, MMICV, scrap annuel du suivi hebdomadaire, probabilité *q* du modèle de Rex), ou **manquant**.

**Lecture de la figure** : seuls les paramètres manquants *qui bloquent un calcul* (en orange) demandent une action ; les manquants facultatifs (transport, délai d'approvisionnement, valeur d'une semaine de délai) laissent simplement de côté le terme correspondant, et une ouverture sommaire non saisie est remplacée par l'ouverture soignée.

**Limite** : « saisi » ne veut pas dire « mesuré ». La colonne « Provenance » reprend la source notée dans le classeur, quand il y en a une ; en démonstration, toutes les valeurs sont fictives.
"""),
    code('aff.figures(ctx, "ligne", "Préparation des paramètres")'),
    md("Les paramètres généraux de la ligne, puis l'ensemble des paramètres (début de la table ; le fichier est complet) :"),
    code('aff.table(ctx, "ligne", "Paramètres effectifs", ou={"FRU": "(ligne)"}, colonnes=["Paramètre", "Valeur", "Provenance", "État"])'),
    code('aff.table(ctx, "ligne", "Paramètres effectifs")'),
    md("""
## 2. Données à obtenir

Ce qui manque pour calculer, regroupé par paramètre, avec le service à qui le demander. Seuls les paramètres qui bloquent un calcul sont listés.

**Décision éclairée** : le contenu de l'audit de démontage chronométré (temps d'ouverture, d'extraction, de test, de tri), les pesées et les consultations de recycleurs à lancer.
"""),
    code('aff.table(ctx, "ligne", "Données à obtenir")'),
    md("""
## 3. Les trois options, pièce par pièce

Valeur nette **par FRU traité** de chaque option, comparée à la pièce laissée dans le FRU (option 3, valeur zéro) :

- **Réemploi** : probabilité *q* × (valeur de la pièce + délai d'approvisionnement évité) + valeur au kilo des pièces qui échouent au test − transport − main-d'œuvre d'extraction et de test, + traitement évité chez le recycleur actuel ;
- **Recyclage trié** : poids × prix du recycleur acheteur − main-d'œuvre de tri, + traitement évité ;
- **Laissée dans le FRU** : zéro, c'est la référence.

L'ouverture du FRU est payée **une seule fois par FRU**, quel que soit le nombre de pièces extraites : elle n'est pas dans ces valeurs, elle est indiquée dans le titre de chaque cadre. C'est pourquoi une pièce peu rentable seule peut le devenir à côté d'une autre.

**Lecture** : une barre à droite du zéro rapporte, à gauche elle coûte. « inconnu » signifie qu'une donnée manque : son nom est celui de la colonne du classeur de paramètres à remplir. La valeur n'est pas calculée et l'option n'est jamais choisie. Dans la table, la colonne « Non compté faute de donnée » dit ce que la valeur du réemploi laisse de côté (transport, délai évité) parce qu'une donnée facultative n'est pas saisie.

**Limites** : la valeur d'une pièce réemployée est une fraction du MMICV, pas un prix constaté ; *q* vient du modèle de Rex. Ce sont des estimations.
"""),
    code('aff.figures(ctx, "ligne", "Options par pièce")'),
    code('''
aff.table(ctx, "ligne", "Options par pièce", colonnes=["Type de FRU", "Pièce", "1 Réemploi (€/FRU)", "2 Recyclage (€/FRU)", "3 Jeté (€/FRU)", "Heures réemploi",
          "Heures recyclage", "Manque réemploi", "Manque recyclage", "Non compté faute de donnée", "Ouverture soignée (€/FRU)", "Ouverture sommaire (€/FRU)"])
'''),
    md("""
## 4. Le plan optimal

Pour chaque type de FRU : traiter ou laisser, quelles pièces réemployer, lesquelles recycler, combien d'heures et quelle marge. Quand les heures manquent, le modèle sert d'abord les plans qui rapportent le plus par heure ; un type de FRU peut alors apparaître sur deux lignes (une partie du flux avec un plan complet, le reste avec un plan plus court).

**Lecture du résumé** : le résultat annuel est la marge variable moins les coûts fixes annualisés. Le *seuil de rentabilité* est le nombre de FRU à traiter par an pour couvrir les coûts fixes. La *valeur d'une heure opérateur en plus* est ce que rapporterait une heure supplémentaire : zéro si la capacité n'est pas saturée.

**Limites** : calcul au centre des plages de paramètres (l'incertitude est traitée en section 7) ; les types de FRU incomplets sont exclus, ce qui sous-estime le gisement.
"""),
    code('''
aff.table(ctx, "ligne", "Plan optimal", colonnes=["Type de FRU", "Décision", "1 Réemploi", "2 Recyclage", "FRU traitées / an", "FRU scrapées / an", "Heures par FRU",
          "Marge par FRU (€)", "Marge par heure (€)", "Heures / an", "Marge variable / an (€)", "Kg détournés / an"])
'''),
    md("Les types de FRU **incomplets**, avec ce qui manque pour les calculer (nom des paramètres du classeur) :"),
    code('aff.table(ctx, "ligne", "Plan optimal", ou={"Décision": "incomplet"}, colonnes=["Type de FRU", "Entrées manquantes"])'),
    md("Le résumé de la ligne au centre des plages :"),
    code('aff.table(ctx, "ligne", "Résumé")'),
    md("""
## 5. Situation actuelle contre ligne

Flux annuels en euros, coût en négatif. La situation actuelle se résume au traitement de tous les FRU scrapés par le recycleur actuel. Avec la ligne s'ajoutent la marge de la ligne et ses coûts fixes, et le traitement résiduel diminue.

**Lecture** : la ligne « TOTAL », colonne « Écart », est le gain annuel attendu de la ligne.

**Limite** : le coût de traitement actuel repose sur un prix au kilo saisi et sur le poids des FRU ; si l'un des deux manque, le poste et le total restent vides.
"""),
    code('aff.figures(ctx, "ligne", "Actuel contre ligne")'),
    code('aff.table(ctx, "ligne", "Actuel contre ligne")'),
    md("""
## 6. Semaine par semaine

Le modèle est rejoué sur le flux réel de chaque semaine : capacité et coût fixe de la semaine, pas de stock d'une semaine à l'autre.

**Lecture** : les semaines creuses paient le coût fixe sans marge ; les semaines chargées saturent les heures et laissent des FRU. L'écart entre ce résultat annualisé et celui du modèle annuel au flux moyen est le **coût de l'irrégularité du flux** : c'est, au plus, ce que rapporterait un stock tampon de FRU en attente.

**Limite** : l'hypothèse « pas de stock » est pessimiste si l'atelier peut garder des FRU quelques semaines.
"""),
    code('aff.figures(ctx, "ligne", "Semaine par semaine")'),
    code('aff.table(ctx, "ligne", "Période par période")'),
    md("""
## 7. Incertitude : tirages de Monte-Carlo

Chaque paramètre saisi comme une plage est tiré au hasard dans sa plage, et la ligne est ré-optimisée à chaque tirage.

**Lecture** : P5 et P95 encadrent neuf tirages sur dix ; la part des tirages à droite de zéro estime la probabilité que la ligne soit rentable, pour les plages saisies.

**Limites** : le résultat ne vaut que ce que valent les plages saisies. Un paramètre saisi comme une valeur unique est traité comme certain. Des plages trop étroites donnent une assurance qui n'existe pas.
"""),
    code('aff.figures(ctx, "ligne", "Monte-Carlo")'),
    code('aff.table(ctx, "ligne", "Monte-Carlo (tirages)", n=5)'),
    md("""
## 8. Sensibilité aux heures opérateur

Le modèle est recalculé pour plusieurs niveaux d'heures disponibles, du quart au triple de la capacité saisie.

**Décision éclairée** : combien d'heures demander. Tant que le résultat monte, les heures manquent ; quand il plafonne, tous les FRU rentables sont déjà traités et une heure de plus ne rapporte rien.
"""),
    code('aff.figures(ctx, "ligne", "Sensibilité aux heures")'),
    code('aff.table(ctx, "ligne", "Sensibilité aux heures")'),
    md("## Notes de l'étape\n\nLes indicateurs du résumé, du comparatif, du calcul semaine par semaine et du Monte-Carlo, tels qu'ils sont repris par la synthèse et par l'outil des décideurs."),
    code('aff.notes(ctx, "ligne")'),
    md(SUITE.format(suivant="06_Synthese_decideurs", rep="05_ligne")),
])

# =========================================================================== 06
N06 = ("06_Synthese_decideurs", [
    md("""
# ERC circularité · 06 · Synthèse pour les décideurs

Ce notebook réunit ce qu'il faut pour décider : les indicateurs, leurs limites, ce qui reste à obtenir, et l'outil qui permet de faire varier les paramètres sans toucher au code. Les notebooks 01 à 05 détaillent comment chaque chiffre est obtenu.
"""),
    depart("synthese"),
    code("aff.etat(ctx)"),
    md("""
## 1. Tableau de décision

Les indicateurs de la ligne de démontage et de tri, au centre des plages de paramètres et en probabilité. La colonne « Lecture » dit comment chaque valeur est obtenue.

**Lecture** : « inconnu » signifie qu'une donnée d'entrée manque ; l'indicateur n'est pas calculé plutôt que calculé faux. Le gain annuel se lit avec sa fourchette (P5, médiane, P95) et avec le nombre de types de FRU incomplets : plus il y en a, plus le gisement réel est sous-estimé.

**Limite** : en démonstration, ces chiffres sont fictifs.
"""),
    code('aff.table(ctx, "synthese", "Tableau de décision")'),
    code('aff.figures(ctx, "ligne", ["Actuel contre ligne", "Monte-Carlo"])'),
    md("""
## 2. Limites et lecture

Ce que les données ne permettent pas d'affirmer. À joindre à toute présentation des chiffres ci-dessus.
"""),
    code('aff.table(ctx, "synthese", "Limites et lecture")'),
    md("""
## 3. Données à obtenir

L'état de préparation des paramètres, puis la liste de ce qui manque pour calculer, avec le service à qui le demander. C'est le plan d'action qui améliore le plus la décision : chaque paramètre obtenu fait entrer un type de FRU ou une option dans le calcul.
"""),
    code('aff.figures(ctx, "synthese", "Préparation des paramètres")'),
    code('aff.table(ctx, "ligne", "Données à obtenir")'),
    md("""
## 4. L'outil des décideurs

Une page autonome, qui s'ouvre dans un navigateur sans installation. Elle reprend les paramètres du modèle avec leur provenance et recalcule la ligne quand on les modifie. Elle est produite par l'étape de synthèse à partir des mêmes données que ce notebook.
"""),
    code("aff.outil(ctx)"),
    md("""
## 5. Anomalies de cette exécution

Table vide = tous les calculs ont abouti. Sinon, traiter l'anomalie avant de présenter les résultats de l'étape concernée.
"""),
    code("aff.anomalies(ctx)"),
    md("---\nFin du parcours. Pour mettre à jour les résultats : compléter le classeur de paramètres ou ajouter des extractions, puis relancer les notebooks dans l'ordre (ou seulement **00_Demarrage**, qui exécute tout)."),
])

# =========================================================================== 07
N07 = ("07_Composition_des_pieces", [
    md("""
# ERC circularité · 07 · Composition des pièces d'une nomenclature

À partir d'une liste de pièces (code article et description), ce notebook propose pour chacune sa **classe matière**, celle qui fixe le prix du recycleur et la filière. C'est une entrée du reste du dossier : une classe validée ici devient le type de déchet de la pièce dans les autres notebooks.

**Comment ça marche.** Chaque source (une règle sur la description, une pièce validée qui lui ressemble, le classement antérieur, un document du fabricant, un modèle de langage) *affirme* une classe. Aucune n'est crue sur parole : le **cortex** garde ces affirmations, les compare aux validations faites par une personne, et en déduit ce que vaut chaque type de source. La probabilité d'une classe combine les affirmations selon cette fiabilité.

**Le moins d'appels possible.** Sans classe, une pièce n'a pas de bac : elle ne peut pas être triée. L'**enjeu** d'une pièce est ce que rapporterait au plus, par an, d'établir sa classe : masse annuelle × moyenne de (prix du recycleur + traitement évité) sur les classes possibles. La chaîne commence par ce qui est gratuit. Une recherche de documents ou un appel à un modèle n'est lancé que si l'enjeu couvre ce qui a déjà été dépensé pour la pièce, plus cette action. Une recherche déjà payée n'est jamais refaite.

**La confiance se gagne.** Tant qu'aucune validation n'a montré qu'un modèle lit juste, sa lecture d'un document ne suffit pas à accepter une classe, même relue par lui. Elle y suffit une fois que les validations l'ont montré.

**Confidentialité.** Aucun code article interne ni aucune description ne sort du poste. Une recherche ne contient que le fabricant, sa référence et un type générique, et n'est émise que si le fabricant est nommé, n'est pas l'entreprise, et si la référence n'est le code article d'aucune pièce. Une pièce déclarée de conception interne n'est jamais recherchée. À vérifier avant de brancher une collecte : la colonne « référence fabricant » de la nomenclature contient bien des références de fabricant.

Vocabulaire : « collecte » désigne ici la recherche de documents sur le web ; « scrapé » reste réservé aux pièces mises au scrap.
"""),
    depart("ligne"),
    code("""
from erc import composition
compo = composition.executer(ctx)      # nomenclature du dossier ; à défaut, les pièces consommées dans les extractions
aff.etat(ctx)
"""),
    md("""
## 1. Composition proposée

Une ligne par pièce : la classe la plus probable, sa probabilité, les sources qui l'affirment, et un statut.

| Statut | Sens |
|---|---|
| validée | une personne a fixé la classe : c'est la vérité du dossier |
| acceptée | la classe est probable (seuil d'acceptation) et une erreur coûterait moins qu'une revue ; contrôlée par sondage |
| à valider | des preuves existent mais ne suffisent pas, ou la classe est probable mais une erreur coûterait plus qu'une revue |
| inconnue | aucune source ne s'est prononcée |

**Lecture** : « Enjeu » borne ce qu'établir la classe peut rapporter par an. « Prochaine action » dit quoi faire, y compris « aucune » quand établir la classe coûterait plus que cela ne rapporte. Une classe affirmée hors du référentiel des grades apparaît comme « hors référentiel » : elle demande une revue.

**Limite** : en démonstration, la nomenclature, les documents et le modèle sont fictifs.
"""),
    code('aff.table(ctx, "composition", "Composition proposée", colonnes=["PN", "Description", "Classe retenue", "Probabilité", "Statut", "Sources", "Enjeu (€/an, borne)", "Appels au modèle", "Prochaine action"])'),
    md("""
## 2. File de revue

Les pièces à faire valider par une personne, par enjeu décroissant.

**Le plus simple : la page de revue.** `artefacts/composition/ERC_Composition_Revue.html` s'ouvre dans un navigateur, sans connexion. Elle montre pour chaque pièce la classe proposée, qui dit quoi, et ce que rapporterait de trancher. La personne confirme ou corrige, puis télécharge un fichier de validations à déposer dans `Acquisition/` (dossier des extractions). Deux files y sont proposées : les pièces **à valider**, et un **sondage** de pièces acceptées tirées au hasard. Le sondage compte autant que la file : sans lui, la fiabilité des sources n'est mesurée que sur les cas douteux, et elle est sous-estimée.

**À la main.** Remplir « Classe validée » et « Validateur » dans la table ci-dessous et la déposer sous `Acquisition/validations_composition.csv` (colonnes `PN;Classe validée;Validateur;Commentaire;Motif`, le motif valant `file` pour ces pièces). Tous les fichiers `validations_composition*.csv` du dossier sont lus : une personne ou une séance par fichier.

À l'exécution suivante, ces validations entrent dans le cortex : elles fixent la classe des pièces validées, servent d'exemples aux pièces de description voisine et mesurent ce que vaut chaque type de source.
"""),
    code('aff.table(ctx, "composition", "File de revue", colonnes=["PN", "Description", "Classe retenue", "Probabilité", "Enjeu (€/an, borne)", "Vaut une revue", "Prochaine action"])'),
    md("""
## 3. Ce que valent les sources

Pour chaque type de source : l'a priori de départ, qui est une hypothèse de travail, puis ce qui est observé sur les pièces validées. Plus il y a de validations, plus la fiabilité repose sur les faits et moins sur l'hypothèse (« Poids des observations »).

**Lecture** : une source souvent contredite par les validations voit sa fiabilité baisser, et pèse moins dans toutes les probabilités. Un modèle de langage est une source comme une autre. Les colonnes « dont par sondage » et « dont dans la file » disent d'où viennent les validations : celles de la file ne renseignent que les pièces non tranchées, celles du sondage que les pièces acceptées.

**Limite** : le calcul suppose que les types de source se trompent indépendamment. Si les règles saisies ici reprennent celles qui ont produit le classement antérieur, les deux comptent en double : ne garder que l'une des deux.
"""),
    code('aff.table(ctx, "composition", "Fiabilité des sources")'),
    md("""
## 4. Journal des acquisitions

Chaque recherche de documents et chaque appel au modèle, avec son coût supposé. Une table courte est le signe que la chaîne s'arrête tôt. Une panne (collecte ou modèle) y figure comme « échec » : elle n'est pas comptée et l'action sera reprise au passage suivant.
"""),
    code('aff.table(ctx, "composition", "Journal des acquisitions")'),
    md("""
## 5. Valeur d'établir une classe, dans le modèle de ligne

Pour les pièces à valider qui figurent dans le modèle de ligne : ce que rapporterait d'établir leur classe, calculé en résolvant le modèle sous chaque classe possible, comparé au modèle où la pièce ne peut pas être triée. « La décision change » dit si la réponse modifierait le plan. Table vide = aucune pièce du modèle de ligne n'attend de validation.

La justification est dans `docs/Formal_framework.md`, section 8.3 (proposition 7).
"""),
    code('aff.table(ctx, "composition", "Valeur de l\'information")'),
    md("""
**Illustration.** Le même calcul sur une pièce du modèle de ligne, en supposant que sa classe hésite entre les deux grades les mieux payés du référentiel. C'est une supposition faite ici pour montrer le calcul, pas un résultat du dossier.
"""),
    code("""
from erc import information
import pandas as pd
m = ctx.res.get("ligne", {}).get("Modèle")
prix = {k: float(v) for k, v in ctx.src.prix_recycleur.items()}
if m and len(prix) >= 2:
    piece = next((pc for d in m["frus"].values() for pc, e in d["pieces"].items() if pc != "CARCASSE" and e.get("poids_kg") is not None), None)
    deux = sorted(prix, key=prix.get, reverse=True)[:2]
    exemple = information.priorites_classes(m["ligne"], m["frus"], {piece: {deux[0]: 0.6, deux[1]: 0.4}}, prix, cout_information=composition.Reglages().cout_revue) if piece else pd.DataFrame()
    display(exemple)
else:
    print("Modèle de ligne ou référentiel des grades absent : pas d'illustration.")
"""),
    md("""
## 6. Brancher le modèle hébergé chez vous et une collecte de documents

**Le modèle.** Les données sont privées : le modèle de langage tourne sur une machine qui vous appartient, de préférence celle qui détient les données. Il se règle sans code dans `parametres/modele_local.cfg` (créé par `python -m erc.modele --preparer`), se vérifie par `python -m erc.modele --verifier`, et la chaîne l'utilise alors d'elle-même. Guide : `docs/Modele_local.md`.

Un modèle hébergé chez vous peut lire les **descriptions internes** des pièces : c'est la seule source automatique pour une pièce de conception interne. Un modèle qui n'est pas chez vous ne reçoit que le texte de documents publics. Pour choisir entre plusieurs modèles, `python -m erc.modele --comparer modele-a modele-b` les note sur vos pièces validées.

**Le modèle apprend de vos validations, sans réentraînement.** `python -m erc.modele --optimiser` fait améliorer par le modèle lui-même les conseils de lecture des descriptions (méthode GEPA, en local), à partir des pièces validées, et mesure le gain sur des pièces qu'il n'a jamais vues. Les conseils ne sont adoptés que s'ils ne font pas moins bien sur ces pièces. Il faut au moins 24 pièces validées.

**En Python**, pour brancher aussi votre collecte de documents :

```python
from erc import composition

def ma_collecte(requete):
    # requete = {"fabricant": ..., "reference_fabricant": ..., "type": ...} : rien d'interne
    # rendre une liste de documents : {"origine": "site ou URL", "texte": "...", "nature": "document" ou "déclaration fabricant"}
    # ajouter "classe": "..." quand le document donne lui-même la classe (déclaration matière structurée) : aucun modèle n'est alors appelé
    return []

qwen = composition.ModeleLocal("http://localhost:11434/v1", "nom-du-modele")   # sur ce poste ; pour une autre de vos machines : confiance=("nom-de-la-machine",)
reglages = composition.Reglages(fabricants_internes=("Nom de l'entreprise",))  # jamais recherché à l'extérieur
compo = composition.executer(ctx, collecteur=ma_collecte, modele=qwen, reglages=reglages)
# un second modèle pour contrôler les lectures du premier : composition.executer(..., modele_controle=autre_modele)
```

Le modèle répond sous contrainte : la classe doit être dans la liste proposée, la citation doit se trouver mot pour mot dans le document, et l'indice qui justifie une classe doit se trouver dans la description ; sinon la réponse est rejetée. Un serveur qui n'est ni ce poste ni l'une de vos machines déclarées est refusé, sauf acceptation explicite (`distant=True`) ; il ne lit alors jamais une description.

Une règle et un modèle qui lisent la même description ne font pas deux preuves : d'accord, ils comptent pour une ; en désaccord, la classe n'est plus acquise et la pièce demande une autre preuve.

Votre méthode de collecte existante se branche telle quelle derrière `ma_collecte` : il suffit qu'elle rende des documents sous cette forme.
"""),
    code('aff.notes(ctx, "composition")'),
    md("---\\nCe notebook est une entrée du dossier : relancer **00_Demarrage** après avoir validé des pièces pour que leurs classes soient reprises partout."),
])

TOUS = [N00, N01, N02, N03, N04, N05, N06, N07]


# =========================================================================== construction et exécution
def construire(nom: str, cellules: list):
    """Notebook nbformat 4 : identifiants de cellules stables, aucun résultat."""
    import nbformat
    nb = nbformat.v4.new_notebook()
    nb.metadata = {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                   "language_info": {"name": "python"}}
    prefixe = nom[:2]
    for i, (genre, texte) in enumerate(cellules):
        cellule = nbformat.v4.new_markdown_cell(texte) if genre == "markdown" else nbformat.v4.new_code_cell(texte)
        cellule["id"] = f"erc-{prefixe}-{i:02d}"
        nb.cells.append(cellule)
    nbformat.validate(nb)
    return nb


def ecrire(nb, chemin: Path) -> None:
    import nbformat
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", encoding="utf-8", newline="\n") as f:
        nbformat.write(nb, f)


def executer(nb, minuteur: int = 900) -> tuple:
    """Exécute le notebook depuis notebooks/. Renvoie (erreurs, avertissements) : une erreur empêche l'enregistrement,
    un avertissement (message écrit par le calcul sur la sortie d'erreur) est seulement signalé."""
    from nbclient import NotebookClient
    from nbclient.exceptions import CellExecutionError
    client = NotebookClient(nb, timeout=minuteur, kernel_name="python3", record_timing=False, resources={"metadata": {"path": str(NOTEBOOKS)}})
    erreurs, avertissements = [], []
    try:
        client.execute()
    except CellExecutionError as e:
        erreurs.append("cellule en erreur : " + str(e).strip().splitlines()[-1][:300])
    for i, cellule in enumerate(nb.cells):
        for sortie in cellule.get("outputs", []):
            if sortie.get("output_type") == "error":
                erreurs.append(f"cellule {i} : {sortie.get('ename')}: {str(sortie.get('evalue'))[:200]}")
            elif sortie.get("output_type") == "stream" and sortie.get("name") == "stderr":
                avertissements.append(f"cellule {i} : {str(sortie.get('text')).strip()[:200]}")
    return erreurs, avertissements


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description="Construit (et exécute) les notebooks du dossier ERC circularité.")
    a.add_argument("--executer", action="store_true", help="exécuter les notebooks et les enregistrer avec leurs résultats (démonstration)")
    a.add_argument("--reel", action="store_true", help="avec --executer : données réelles ; copies exécutées dans artefacts/notebooks/")
    a.add_argument("noms", nargs="*", help="notebooks à traiter (morceau du nom, ex. 02) ; défaut : tous")
    o = a.parse_args(argv)
    try:
        import nbformat  # noqa: F401
    except ImportError:
        print("Le paquet nbformat est nécessaire (il est installé avec Jupyter) : pip install nbformat nbclient")
        return 2
    choisis = [(n, c) for n, c in TOUS if not o.noms or any(m in n for m in o.noms)]
    if not choisis:
        print("Aucun notebook ne correspond à :", ", ".join(o.noms))
        return 2
    if o.executer and not o.reel:
        os.environ["ERC_DEMO"] = "1"                  # les notebooks enregistrés dans le dossier ne montrent que la démonstration
        if not o.noms:                                # tout est refait : la démonstration repart d'un cortex vide, pour que ses
            import shutil                             # résultats enregistrés soient ceux d'un premier lancement, partout les mêmes
            shutil.rmtree(Path(os.environ.get("ERC_DOSSIER") or DOSSIER) / "demo" / "cortex", ignore_errors=True)
    # Données réelles : les copies exécutées vont avec les artefacts (hors du dépôt public), jamais dans notebooks/.
    sortie = Path(os.environ.get("ERC_DOSSIER") or DOSSIER) / "artefacts" / "notebooks" if (o.executer and o.reel) else NOTEBOOKS
    echecs = 0
    for nom, cellules in choisis:
        nb = construire(nom, cellules)
        if not (o.executer and o.reel):
            ecrire(nb, NOTEBOOKS / f"{nom}.ipynb")    # version sans résultats, toujours écrite d'abord
        if not o.executer:
            print(f"  {nom}.ipynb : écrit ({len(nb.cells)} cellules)")
            continue
        t0 = time.time()
        erreurs, avertissements = executer(nb)
        if erreurs:
            echecs += 1
            print(f"  {nom}.ipynb : ÉCHEC en {time.time() - t0:.0f} s (la version enregistrée reste sans résultats)")
            for p in erreurs[:8]:
                print("      " + p)
            continue
        ecrire(nb, sortie / f"{nom}.ipynb")
        poids = (sortie / f"{nom}.ipynb").stat().st_size / 1e6
        print(f"  {nom}.ipynb : exécuté en {time.time() - t0:.0f} s, aucune erreur, {poids:.2f} Mo → {sortie}")
        for p in avertissements[:8]:
            print("      avertissement, " + p)
    if o.executer:
        total = sum(f.stat().st_size for f in sortie.glob("*.ipynb")) / 1e6
        print(f"Taille totale des notebooks de {sortie} : {total:.2f} Mo")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
