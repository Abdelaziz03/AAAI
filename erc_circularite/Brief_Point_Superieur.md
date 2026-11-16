# ERC : circularité des pièces et FRU — point d'avancement

*Support pour le point avec le responsable. Les chiffres sont des ordres de grandeur issus des extractions R26 et de `ERC_Valorisation_MICV_v1.xlsx`, à valider ; aucune recette n'est encore réalisée.*

---

## 1. Ce qui est fait

| Chantier | État | Livrable |
|---|---|---|
| **Campagne de pesée et caractérisation** | Lancée. Pesée de la benne DEEE passée de mensuelle à **hebdomadaire (vendredi) avec photo**. Fiches terrain prêtes (contenants, lots, pesées, transferts, inventaires). | `ERC_R26_Visite_Terrain_Acquisition.ipynb` |
| **Rapprochement dashboards ↔ terrain** | Méthode prête : bilan par lot = stock final − stock initial + sorties − entrées. Pas encore de série complète de 14 jours. | idem, sections 6 à 8 |
| **Extraction R26 cumulée** | Composants consommés par jour, FRU rebutées (vwERT), MMICV fiche article. | `ERC_Aide_Decision_Composants.ipynb` |
| **Classement des pièces** | MR, TSUI, tous ateliers : volume, MMICV unitaire et total. | idem, section 2 |
| **Lien FRU rebutées → composants** | Par la nomenclature de consommation. | idem, section 4 |
| **Recycleurs / réparateurs EMEA** | Première liste longue (ex. WEEECycling, Global Biomedical Service). Aucun contact pris. | `EMEA_Partner_Research_Initial.md` |
| **Prototype simulation + RL** | Simulateur cohérent avec l'historique (40/40 contrôles). RL testé sur cas synthétique : **ne bat pas encore une règle simple**. | `local_twin/` |
| **Nouveau : fiabilité et risques** | Risque matière, risque supply, fiabilité du réemploi, durée de vie résiduelle, valeur par voie en probabilité, pré-sélection Pareto. | `ERC_Fiabilite_Risques_Priorisation.ipynb` |

**Premiers signaux (à confirmer) :** sur MR, le SSSA (`5453107-2-R`, 411 FRU rebutées dans l'historique) concentre les IGBT 400 A 600/1200 V (~3 900 chacun), les condensateurs 450 V 4700 µF (~3 900) et la Gate Driver Board (438, MMICV ~325). Sur TSUI, ce sont surtout des pièces mécaniques et plastiques de la Smart Box : peu de valeur matière, mais un enjeu de réemploi.

## 2. Limites à dire franchement

1. **MMICV** : couvre ~60 % des quantités ; c'est un coût standard, pas un prix de revente ; devise USD/EUR à confirmer.
2. **Nomenclature** : on sait qu'une pièce a déjà été changée sur un type de FRU, pas **combien** il y en a dans une FRU rebutée → audit de démontage nécessaire.
3. **Fichier de fiabilité** (`Parts_DI_ULS`) : il ne contient **que des défaillances** (probablement *early life failures*). Il dit **comment** les pièces lâchent, pas **combien de temps** elles durent (voir §4).
4. **Aucun prix recycleur, devis de réparation, coût de transport ou temps de démontage** : les voies ne peuvent pas encore être classées par rentabilité. Le modèle les calcule automatiquement dès qu'une entrée arrive.
5. **Benne partagée** et bacs individuels : poids non attribuable à un seul atelier, décalage consommation / déchet.

## 3. Pré-sélection des FRU et pièces rebutées : le modèle

Pour chaque pièce, cinq critères, **sans pondération imposée** :

| Critère | Mesure | Statut |
|---|---|---|
| Valeur en jeu | Pièces × MMICV | disponible |
| Gisement | FRU rebutées contenant la pièce | disponible (nombre par FRU inconnu) |
| **Risque matière** | Matières critiques / stratégiques UE (CRMA 2024/1252) et métaux précieux présents | codé en dur, présence seulement |
| **Risque supply** | Délai, source unique, fin de vie (EOL/LTB) | table codée en dur, **à remplir avec les achats** ; a priori de type en attendant |
| **Fiabilité du réemploi** | Taux de défaillance précoce d'une pièce réparée ou récupérée ÷ celui d'une neuve | dès que l'on a le dénominateur (§4) |

Sortie : un **front de Pareto** (les pièces qu'aucune autre ne bat sur tous les critères) = la liste courte à instruire. Puis, par pièce et par voie, une **valeur nette en probabilité** (moyenne, P5–P95, **probabilité d'être rentable**), qui intègre main-d'œuvre hors plan de charge, démontage, test, transport, devis et coût d'une défaillance terrain.

Exemple de lecture attendue : *« IGBT 1200 V : réemploi rentable dans 80 % des tirages si le rendement du test dépasse 60 % ; vente recycleur toujours positive mais faible. »*

## 4. Fiabilité opérationnelle et durée de vie : l'approche

Trois niveaux, du disponible au plus exigeant :

1. **Le réemploi est-il aussi fiable que le neuf ?** Taux ELF = défaillances ÷ pièces posées sur la même période, séparé neuf / réparé (`-R`) / récupéré (`-H`), avec intervalle de confiance bayésien. **Besoin : sorties de stock 2022-2023 par référence et suffixe (SQL).**
2. **Comment la pièce lâche-t-elle ?** Forme de Weibull `k` estimée sur les durées `elf_days` (vraisemblance tronquée à la fenêtre ELF) :
   - `k < 1` mortalité infantile → une pièce qui a déjà tourné est *plus* sûre : **réemploi après test**, argument fort pour le harvest ;
   - `k ≈ 1` aléatoire → l'âge ne compte pas ;
   - `k > 1` usure → réemploi seulement si l'âge du donneur est connu (ex. condensateurs électrolytiques : **recyclage** plutôt que réemploi).
3. **Combien de vie reste-t-il à une pièce récupérée ?** Probabilité de tenir la garantie `R(âge + garantie) / R(âge)` et vie résiduelle moyenne. **Besoins : âge du donneur** (n° de série de la FRU rebutée → date de pose) et **données de survivants** (base installée) pour l'échelle de vie absolue. En attendant, **a priori physiques** paramétrés par fiche technique : Arrhenius pour les condensateurs, Coffin-Manson pour les IGBT.

Ce découpage évite de présenter une « durée de vie » que les données actuelles ne permettent pas de calculer.

## 5. Le modèle complet visé

```
Données           SQL R26 · vwERT · pesées terrain · fiabilité terrain · achats · devis acheteurs
   ↓
Jumeau des flux   FRU → composants → bacs/lots → benne → acheteur (masse mesurée / estimée / allouée)
   ↓
Évaluation        valeur par voie (Monte-Carlo) · fiabilité · risques matière et supply
   ↓
Optimisation      règle simple → optimisation sous contraintes (heures techniciens, place, garantie) → RL si gain prouvé
   ↓
Décision          liste courte, scénario pilote, validation financière (Thomas)
```

Puis extension au côté production.

## 6. Ce que je demande

| Demande | À qui | Pourquoi |
|---|---|---|
| Accès ou contact pour les **sorties de stock 2022-2023 par suffixe** | SQL / IT | Dénominateur du taux de fiabilité |
| Sens de **DI, ULS, ELF, `elf_days`** et durée de la fenêtre | Auteur du fichier Parts_DI_ULS | Interprétation de la fiabilité |
| Données de **base installée** (dates de pose) | Qualité / service terrain | Durée de vie absolue |
| **Délais, source unique, fin de vie** des ~30 premières références | Achats | Risque supply |
| **Temps de démontage et de test, coût horaire hors charge** | Stéphan, Lewis | Coûts main-d'œuvre |
| Feu vert pour **consulter 3 à 5 recycleurs** avec un format de réponse commun | Robert / responsable | Prix réels, premier pilote |
| **Audit de démontage** de 5 SSSA rebutés | Atelier MR | Nombre réel de pièces par FRU, état, rendement du test |
| Date de revue avec **Thomas** | Finance supply chain | Validation économique avant déploiement |

## 7. Prochaines 4 semaines

| Semaine | Action |
|---|---|
| S1 | Série complète de pesées hebdomadaires + bilans par lot ; demandes achats et SQL envoyées |
| S2 | Audit de démontage SSSA ; consultation recycleurs lancée ; taux ELF neuf vs réparé calculé |
| S3 | Premières valeurs par voie sur la liste courte Pareto ; critère de décision fixé avec l'équipe |
| S4 | Dossier pilote (1 recycleur, 1–2 références) pour la revue avec Thomas |
