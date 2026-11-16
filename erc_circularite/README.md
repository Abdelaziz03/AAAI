# ERC circularité : fiabilité, risques et pré-sélection

- `Brief_Point_Superieur.md` — support du point d'avancement avec le responsable.
- `ERC_Fiabilite_Risques_Priorisation.ipynb` — à placer à côté de `ERC_Aide_Decision_Composants.ipynb` et à exécuter après lui. Lit `ERC_Aide_Decision_Composants.xlsx` et le cache `Extraction_R26/fiabilite_ELF_references_ERC.csv`. Écrit `ERC_Fiabilite_Risques_Priorisation.xlsx`.
- `erc_fiabilite_risques.py` — module appelé par le notebook (numpy + pandas seulement) : tables codées en dur (CRM UE, composition par type, supply par référence), Kaplan-Meier, Weibull avec censure et troncature, taux bayésien, survie conditionnelle, valeur par voie en Monte-Carlo, front de Pareto.

Fichier facultatif qui active les taux de fiabilité : `Extraction_R26/poses_2022_2023_par_reference.csv` (séparateur `;`, colonnes `Référence;Origine;Pièces posées`, origine = `Neuve`, `Réparée` ou `Récupérée`), pour la même période que le fichier Parts_DI_ULS.

Le notebook a été testé sur des données fictives, avec et sans le cache ELF et ce dénominateur ; pas encore sur les données réelles.
