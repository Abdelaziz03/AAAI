# ERC circularité

Que faire des FRU scrapées d'un centre de réparation et des pièces qu'elles contiennent : les démonter pour
réemployer des pièces, les trier pour les vendre au kilo à un recycleur, ou les laisser au recycleur actuel ?
Ce dossier va des données brutes à la décision.

Le dépôt ne contient **aucune donnée réelle**. Un jeu de démonstration entièrement fictif permet de tout faire
tourner ; les données réelles sont lues là où elles se trouvent et leurs résultats ne quittent pas le poste.

## Ce que contient le dossier

| Élément | Rôle |
|---|---|
| `erc/` | Le code : lecture des sources, calculs, dépôt des artefacts, outil des décideurs |
| `notebooks/` | Sept notebooks qui lancent une étape et affichent ses artefacts, avec le mode de lecture |
| `artefacts/` | Tout ce qui est produit à partir des données réelles (non versionné) |
| `parametres/` | Le classeur des paramètres saisis et les chemins des sources (non versionné) |
| `demo/` | Le même dossier pour les données fictives : `demo/artefacts/` montre à quoi ressemble le résultat |
| `cortex/` | La base de connaissance (classes matière, preuves, validations), non versionnée |
| `docs/` | La modélisation mathématique : `Modele_mathematique.md` pour l'équipe, `Formal_framework.md` (en anglais) pour une revue |
| `tests/` | Les tests |

Un artefact est une table (CSV lisible dans Excel, et un classeur par étape), une figure (PNG) ou un fichier JSON.
`artefacts/manifeste.json` les liste tous, avec leur description et leur date.

## Les sept étapes

| # | Étape | Ce qu'elle produit | Notebook |
|---|---|---|---|
| 0 | sources | État de chaque fichier attendu, période couverte | `00_Demarrage` |
| 1 | classement | Pièces les plus consommées et les plus chères, FRU scrapées, pré-sélection (valeur, gisement, risque matière, risque supply) | `01_Classement_et_priorisation` |
| 2 | flux | Composant × FRU × type de déchet ; FRU scrapées par semaine ; masse estimée contre masse pesée, marge d'erreur, cause d'écart | `02_Flux_entree` |
| 3 | fiabilite | Défaillances précoces par origine de pièce (neuve, réparée, récupérée), forme de la défaillance | `03_Fiabilite` |
| 4 | rex | Modèle de Rex : probabilité qu'une pièce extraite soit réutilisable, entraînement sur l'audit, métriques | `04_Modele_de_Rex` |
| 5 | ligne | Ligne de démontage et de tri : trois options par pièce, plan optimal, comparaison au recycleur actuel, incertitude | `05_Ligne_demontage_tri` |
| 6 | synthese | Tableau de décision, données à obtenir, outil des décideurs | `06_Synthese_decideurs` |
| + | composition | Classe matière de chaque pièce d'une nomenclature, file de revue, fiabilité des sources | `07_Composition_des_pieces` |

L'étape « flux » donne aussi la prévision du flux de la semaine suivante et son évaluation. La composition est une entrée du dossier : une classe validée devient le type de déchet de la pièce à l'exécution suivante.

## Démarrer

Prérequis : Python 3.9 ou plus, `pandas`, `numpy`, `openpyxl`, `matplotlib`, Jupyter. `pyxlsb` seulement pour la
première lecture du fichier de fiabilité.

**Voir la démonstration**

```bash
python -m erc --demo
```

Les résultats sont dans `demo/artefacts/`. L'outil des décideurs est `demo/artefacts/outil/ERC_Outil_Decision.html` :
il s'ouvre dans un navigateur, sans installation ni connexion.

**Travailler sur les données réelles**

1. Ouvrir `notebooks/00_Demarrage.ipynb` et indiquer une fois où sont les extractions :
   `erc.memoriser_chemins(projet=r"...\ERC_Flux_Dechets_Ateliers")`. Les référentiels sont cherchés dans le dossier parent.
2. Exécuter le notebook. Au premier lancement, le pipeline crée `parametres/ERC_Parametres.xlsx`, pré-rempli avec
   les FRU scrapées et leurs pièces trouvées dans les données.
3. Remplir le classeur : temps de démontage, coût horaire, prix des recycleurs, délais. Une cellule accepte un
   nombre (`45`), une plage (`30|70`) ou un triangle (`30|45|70`). Une cellule vide reste « inconnu ».
   Le pipeline ne réécrit jamais ce classeur.
4. Relancer. Les notebooks 01 à 06 affichent les résultats ; `06_Synthese_decideurs` donne le tableau de décision
   et l'outil.

**Composition des pièces d'une nomenclature**

```bash
python -m erc.composition --demo
```

Sur les données réelles : déposer la nomenclature (colonnes code article et description, et si possible fabricant, référence du fabricant, conception interne) dans `BOM/` sous le dossier des extractions, ou la désigner par `--bom`. Les règles description → classe se saisissent dans l'onglet `Regles_composition` du classeur de paramètres. Un modèle local se branche par `--modele-url` ; une collecte de documents se branche en Python (notebook 07). Aucun code article interne ni aucune description ne sort du poste.

Fichiers de terrain facultatifs, à déposer dans le dossier des extractions :
`Acquisition/pesees_hebdo.csv` (`Semaine;Flux;Masse mesurée (kg)`) et
`Acquisition/audit_demontage.csv` (`Date;Type de FRU;Pièce;Pièces testées;Pièces bonnes`) et
`Acquisition/validations_composition.csv` (`PN;Classe validée;Validateur;Commentaire`).

## Règles du dossier

- Une valeur inconnue reste inconnue : elle n'est jamais remplacée par zéro, et le résultat qui en dépend reste vide.
- Chaque paramètre garde sa provenance : saisi, tiré des données, ou manquant.
- Une estimation est présentée comme une estimation. Le MMICV est un coût standard, pas un prix de revente.
- Un calcul qui échoue n'arrête pas le pipeline : il est inscrit dans la table « Anomalies ».

## Tests

```bash
python -m pytest tests
```

| Fichier | Ce qu'il vérifie |
|---|---|
| `test_ligne.py` | Le modèle de ligne : formules du document, optimalité contre un solveur exact, valeur d'une heure, entrées inconnues |
| `test_outil.py` | L'outil des décideurs recalcule exactement comme le modèle Python (scénarios tirés au hasard, exécutés par `node`) |
| `test_stats.py` | Fiabilité (forme retrouvée, intervalle, lectures prudentes), modèle de Rex (pas de fuite, exploration), flux hebdomadaire, risques |
| `test_donnees.py` | Premier lancement sur données réelles, fichiers manquants ou abîmés, classeur jamais réécrit, manifeste, répétabilité |
| `test_information.py` | Valeur de l'information, et les six propositions du cadre formel sur des cas tirés au hasard |
| `test_prevision.py` | Prévision du flux : méthodes, lois prédictives, évaluation sans fuite |
| `test_composition.py` | Cortex et chaîne de composition : fusion des preuves, minimum d'appels, rien d'interne ne sort |

Les tests tournent sur Python 3.9 avec pandas 1.5 comme sur les versions récentes.

Régénérer les notebooks exécutés sur la démonstration : `python outils/construire_notebooks.py --executer`.

La modélisation (ensembles, variables de décision, hypothèses, fonctions de coût et de valorisation, fonction
objectif, modèle de Rex) est dans `docs/Modele_mathematique.md`.
