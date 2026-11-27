# ERC circularité

Que faire des FRU scrapées d'un centre de réparation et des pièces qu'elles contiennent : les démonter pour
réemployer des pièces, les trier pour les vendre au kilo à un recycleur, ou les laisser au recycleur actuel ?
Ce dossier va des données brutes à la décision.

Le dépôt ne contient **aucune donnée réelle**. Un jeu de démonstration entièrement fictif permet de tout faire
tourner ; les données réelles sont lues là où elles se trouvent et leurs résultats ne quittent pas le poste.

**Tout d'un geste** : `Lancer.bat` (ou `./lancer.sh`, ou `python -m erc.agent`) diagnostique le poste, fait les calculs, lance la composition des pièces et écrit une note de décision. Avec un modèle ouvert hébergé chez vous, des agents pilotent et rédigent par une liste fermée d'outils, et chaque nombre de la note est vérifié contre les résultats ; sans modèle, un plan fixe fait le même enchaînement.

**Poste verrouillé, sans échange avec l'extérieur** : voir `INSTALLATION.md`. Une commande dit ce qui est prêt, ce qui manque et quoi faire : `python -m erc.diagnostic`. L'archive à déposer sur le poste se fabrique par `python outils/empaqueter.py`.

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

Sur les données réelles : déposer la nomenclature (colonnes code article et description, et si possible fabricant, référence du fabricant, conception interne) dans `BOM/` sous le dossier des extractions, ou la désigner par `--bom`. Les règles description → classe se saisissent dans l'onglet `Regles_composition` du classeur de paramètres. Un modèle local se branche par `--modele-url` (et un second, pour contrôler le premier, par `--controle-url`) ; une collecte de documents se branche en Python (notebook 07). Aucun code article interne ni aucune description ne sort du poste ; le nom de l'entreprise se déclare par `--fabricant-interne` pour qu'elle ne soit jamais recherchée comme fabricant. Avant de brancher une collecte, vérifier que la colonne « référence fabricant » de la nomenclature contient bien des références de fabricant.

**Le modèle de langage tourne chez vous.** Les données étant privées, le modèle (Qwen ou un autre modèle à poids ouverts) est hébergé sur une machine qui vous appartient, de préférence celle qui détient les données. `python -m erc.modele --preparer` crée `parametres/modele_local.cfg` ; `python -m erc.modele --verifier` interroge le serveur et dit ce qui manque ; `python -m erc.modele --comparer modele-a modele-b` note plusieurs modèles sur vos pièces validées. Un modèle hébergé chez vous peut lire les descriptions internes ; un autre ne reçoit que des documents publics. `python -m erc.modele --optimiser` fait améliorer par le modèle ses propres conseils de lecture à partir de vos pièces validées (méthode GEPA, en local, sans réentraînement), et ne les adopte que s'ils tiennent sur des pièces jamais vues. Guide : `docs/Modele_local.md`.

La chaîne produit `artefacts/composition/ERC_Composition_Revue.html`, une page de revue qui s'ouvre dans un navigateur sans connexion : la personne qui connaît les pièces y confirme ou corrige les classes proposées (file « à valider », puis sondage de pièces acceptées tirées au hasard), télécharge le fichier de validations et le dépose dans `Acquisition/`. Au passage suivant, ces validations sont la référence du cortex. Une recherche déjà payée pour une pièce n'est pas refaite.

Fichiers de terrain facultatifs, à déposer dans le dossier des extractions :
`Acquisition/pesees_hebdo.csv` (`Semaine;Flux;Masse mesurée (kg)`) et
`Acquisition/audit_demontage.csv` (`Date;Type de FRU;Pièce;Pièces testées;Pièces bonnes`) et
`Acquisition/validations_composition*.csv` (`PN;Classe validée;Validateur;Commentaire;Motif` ; un fichier par personne ou par séance).

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
| `test_ligne.py` | Le modèle de ligne : formules du document, optimalité contre un solveur exact, valeur d'une heure, entrées inconnues, types de plus de huit pièces sans énumération |
| `test_outil.py` | L'outil des décideurs recalcule exactement comme le modèle Python (scénarios tirés au hasard, exécutés par `node`) |
| `test_stats.py` | Fiabilité (forme retrouvée, intervalle, lectures prudentes), modèle de Rex (pas de fuite, exploration), flux hebdomadaire, risques |
| `test_donnees.py` | Premier lancement sur données réelles, fichiers manquants ou abîmés, classeur jamais réécrit, manifeste, répétabilité |
| `test_information.py` | Valeur de l'information et valeur d'établir une classe ; les propositions du cadre formel sur des cas tirés au hasard |
| `test_prevision.py` | Prévision du flux : méthodes, lois prédictives, évaluation sans fuite et sur les mêmes prévisions pour toutes les méthodes |
| `test_composition.py` | Cortex et chaîne de composition : fusion des preuves, fiabilité par strates, budget par pièce, recherche jamais payée deux fois, pannes, rien d'interne ne sort |
| `test_modele.py` | Modèle privé : serveurs acceptés ou refusés, descriptions jamais envoyées hors de chez vous, réponses contraintes, réglage, comparaison de modèles |
| `test_gepa.py` | Amélioration des consignes en local : sélection de Pareto, budget tenu, consignes refusées si elles recopient un code article ou une désignation, gain mesuré sur des pièces jamais vues |
| `test_agent.py` | Agents : outils fermés, nombres de la note vérifiés contre les résultats, repli sur le plan fixe quand le modèle fait défaut |
| `test_diagnostic.py` | Diagnostic du poste (carte graphique, serveur de modèle, modèle qui tient dans la carte, réglage écrit une fois) et archive sans données, avec ses empreintes |
| `test_composition_outil.py` | Page de revue : fidèle au cortex, autonome, et boucle fermée (décision dans la page → fichier → validation dans le cortex) |

Les tests tournent sur Python 3.9 avec pandas 1.5 comme sur les versions récentes.

Régénérer les notebooks exécutés sur la démonstration : `python outils/construire_notebooks.py --executer`.

La modélisation (ensembles, variables de décision, hypothèses, fonctions de coût et de valorisation, fonction
objectif, modèle de Rex) est dans `docs/Modele_mathematique.md`.
