# Modélisation mathématique : ligne de démontage et de tri des FRU rebutées

Formulation du modèle codé dans `erc/ligne.py` (optimisation) et `erc/rex.py` (choix réemploi / recyclage). Les noms de champ sont ceux du classeur `parametres/ERC_Parametres.xlsx` et du code.

## 0. Le schéma de décision

```
Flux des FRU rebutées ──► Démontage ou scrap direct ? ──non──► coût actuel de traitement des déchets
   (suivi hebdomadaire)              │oui
                                     ▼
                  coût fixe de la ligne par période + coût variable (temps de démontage et de tri)
                                     ▼
                       Modèle de Rex : réemploi ou recyclage trié ?  ──► valeur tirée de chaque solution
```

Deux décisions : (A) ouvrir la FRU ou la laisser au recycleur actuel ; (B) pour chaque pièce d'une FRU ouverte, réemploi ou recyclage trié. La décision B dépend d'une probabilité estimée par le **modèle de Rex** (§8).

## 1. Sets

| Symbole | Ensemble |
|---|---|
| $t \in T$ | périodes (semaine ou mois ; le code traite une période d'un an) |
| $f \in F$ | types de FRU rebutées (une ligne de l'onglet « FRU » du classeur de paramètres) |
| $p \in P_f$ | pièces contenues dans une FRU de type $f$ (la carcasse peut être déclarée comme une pièce) |
| $o \in O = \{1, 2, 3\}$ | devenir d'une pièce : 1 réemploi, 2 recyclage trié, 3 laissée dans la FRU |
| $s \in S_f$ | plans de traitement d'une FRU $f$ = une option par pièce ; $s_0$ = tout en option 3 = scrap direct |

## 2. Paramètres

| Symbole | Sens | Champ | Source |
|---|---|---|---|
| $N_{ft}$ | FRU de type $f$ rebutées sur la période | `rebut_an` | vwERT, suivi hebdomadaire |
| $m_f$, $m_p$ | masse d'une FRU, d'une pièce (kg) | `poids_fru_kg`, `poids_kg` | pesées |
| $n_{fp}$ | exemplaires de $p$ dans $f$ | `n_par_fru` | audit de démontage |
| $t^{ouv}_f$, $t^{tri,ouv}_f$ | ouverture soignée / sommaire d'une FRU (h) | `ouverture_min`, `ouverture_tri_min` | audit chronométré |
| $t^{ext}_p$, $t^{test}_p$, $t^{tri}_p$ | extraction, test, tri d'un exemplaire (h) | `extraction_min`, `test_min`, `tri_min` | audit chronométré |
| $c^{h}_f$ | coût horaire hors plan de charge, selon le type de FRU (€/h) | `taux_horaire_eur` | responsables d'atelier |
| $H_t$ | heures opérateur disponibles sur la période | `heures_operateur_an` | responsables d'atelier |
| $q_{fp}$ | probabilité qu'un exemplaire extrait soit réutilisable | `p_reutilisable` | **modèle de Rex** (§8) |
| $v_p$ | valeur d'une pièce réemployée (€) | `valeur_eur` | fraction du MMICV, à fixer |
| $L_p$, $\lambda_p$ | délai d'approvisionnement (semaines), valeur d'une semaine évitée (€) | `delai_semaines`, `valeur_semaine_eur` | achats |
| $\pi_p$ | prix payé par le recycleur acheteur (€/kg) | `prix_recycleur_eur_kg` | consultation |
| $\tau_p$ | transport par pièce réemployée (€) | `transport_eur` | registre partenaires |
| $c^{trait}$ | coût de traitement du recycleur actuel (€/kg ; 0 si gratuit) | `cout_traitement_eur_kg` | contrat actuel |
| $I$, $A$ | investissement d'installation (€), amortissement (périodes) | `cout_installation_eur`, `amortissement_ans` | devis |
| $C^{fix}_t$ | coûts fixes de la période : place, encadrement, étalonnage | `couts_fixes_annuels_eur` | atelier |

## 3. Variables de décision

| Variable | Décision du schéma | Sens |
|---|---|---|
| $y \in \{0, 1\}$ | — | installer la ligne (1) ou rester en situation actuelle (0) |
| $x_{fst} \ge 0$ | A et B | nombre de FRU de type $f$ traitées sur la période $t$ selon le plan $s$ |

$x_{f s_0 t}$ = FRU en scrap direct (décision A = non). Tout autre $s$ = FRU démontée, et $s$ fixe l'option $o_s(p)$ de chaque pièce (décision B).

## 4. Hypothèses

1. **Flux connu par période** : $N_{ft}$ vient du suivi hebdomadaire ; le modèle n'est utilisé qu'à la granularité où l'estimé est confirmé par les pesées (§9).
2. **Linéarité** : temps et valeurs proportionnels au nombre de FRU ; pas d'effet d'apprentissage ni de lot minimal de l'acheteur.
3. **Capacité = heures opérateur** : la place et le banc de test ne sont pas limitants (contraintes à ajouter si l'audit le montre).
4. **Indépendance des pièces** d'une même FRU ; le facteur « FRU rebutée » du modèle de Rex corrige en moyenne.
5. **Demande** : toute pièce réemployable est absorbée par la réparation (sinon ajouter $\sum_f n_{fp}\,q_{fp}\,x \le D_{pt}$).
6. **Poids inconnu** : aucun traitement évité compté pour la pièce (prudent).
7. **Carcasse** : reste chez le recycleur actuel sauf si elle est déclarée comme pièce à trier ; elle porte l'essentiel de la masse.
8. **Coût fixe par période** : payé dès que la ligne existe, quel que soit le volume de la période.
9. **Valeur de réemploi** $v_p$ : fraction du MMICV, pas un prix de vente ; la tenue en service (taux de défaillance précoce d'une pièce réemployée) s'en retranche via le coût d'une défaillance terrain.
10. **Pas de stock entre périodes** : une FRU rebutée en $t$ est traitée ou jetée en $t$ (à lever avec une variable de stock si la place le permet).

## 5. Fonctions coûts

**Temps par FRU pour le plan $s$** (l'ouverture est payée une fois par FRU) :

$$h_{fs} = t^{ouv}_f\,\mathbb{1}[\exists p : o_s(p)=1] + t^{tri,ouv}_f\,\mathbb{1}[\nexists p : o_s(p)=1 \ \wedge\ \exists p : o_s(p)=2] + \sum_{p:\,o_s(p)=1} n_{fp}\,(t^{ext}_p + t^{test}_p) + \sum_{p:\,o_s(p)=2} n_{fp}\, t^{tri}_p$$

**Coût variable par FRU** : $C^{var}_{fs} = c^{h}_f \cdot h_{fs}$

**Coût fixe de la ligne par période** : $C^{ligne}_t = \dfrac{I}{A} + C^{fix}_t$

**Coût de la situation actuelle** (scrap direct de tout le flux) : $C^{actuel}_t = c^{trait} \sum_f N_{ft}\, m_f$

## 6. Fonctions valorisation

Par FRU traitée selon le plan $s$ :

$$V^{1}_{fp} = n_{fp}\,\big[\,q_{fp}\,(v_p + L_p \lambda_p) + (1 - q_{fp})\,m_p \pi_p - \tau_p\,\big] \qquad \text{réemploi ; l'exemplaire qui échoue au test est vendu au kg}$$

$$V^{2}_{fp} = n_{fp}\, m_p\, \pi_p \qquad \text{recyclage trié}$$

$$E_{fs} = c^{trait} \sum_{p:\,o_s(p) \in \{1,2\}} n_{fp}\, m_p \qquad \text{traitement évité : masse sortie de la benne actuelle}$$

$$V_{fs} = \sum_{p:\,o_s(p)=1} V^{1}_{fp} + \sum_{p:\,o_s(p)=2} V^{2}_{fp} + E_{fs}$$

## 7. Fonction objectif

Marge d'une FRU traitée selon $s$, par rapport au scrap direct : $g_{fs} = V_{fs} - C^{var}_{fs}$, avec $g_{f s_0} = 0$.

$$\max_{x,\,y} \; Z = \sum_{t \in T} \Big[ \sum_{f \in F} \sum_{s \in S_f} g_{fs}\, x_{fst} \;-\; y\, C^{ligne}_t \Big]$$

sous les contraintes

$$\sum_{s \in S_f} x_{fst} = N_{ft} \quad \forall f, t \qquad \text{(chaque FRU rebutée reçoit un plan)}$$

$$\sum_{f}\sum_{s} h_{fs}\, x_{fst} \le H_t\, y \quad \forall t \qquad \text{(capacité ; aucune heure sans ligne)}$$

$$x_{fst} \ge 0,\quad y \in \{0,1\}$$

$Z$ est le **gain par rapport au recycleur actuel**. On installe la ligne si $Z^* > 0$ ; coût total avec la ligne $= \sum_t C^{actuel}_t - Z^*$.

**Résolution.** À $y = 1$ le problème est linéaire et séparable par période. Le multiplicateur $\mu_t$ de la contrainte d'heures donne pour chaque type de FRU le plan qui maximise $g_{fs} - \mu_t h_{fs}$ ; $\mu_t$ est trouvé par dichotomie. **$\mu_t$ est la valeur nette d'une heure opérateur supplémentaire.**

**Indicateurs.** Seuil de rentabilité $= C^{ligne} / \bar g$ (FRU par période) ; retour sur investissement $= I / (\sum g\,x - C^{fix})$ ; part de masse détournée.

**Période par période.** `erc.ligne.resultat_par_periode` rejoue le modèle sur le flux hebdomadaire réel : capacité et coût fixe de la semaine, pas de stock. L'écart avec le modèle annuel au flux moyen est le **coût de la variabilité du flux** (heures perdues les semaines creuses, FRU non traitées les semaines chargées) ; il chiffre ce que rapporterait un stock tampon.

**Incertitude.** Chaque paramètre peut être une plage ; le problème est résolu pour chaque tirage (Monte-Carlo) → distribution de $Z^*$ et $P(Z^* > 0)$.

## 8. Modèle de Rex : choix, justification, paramètres, entraînement, métriques

**Ce qu'il décide.** Pour une pièce d'une FRU ouverte, réemploi plutôt que recyclage si

$$q_{fp}\,(v_p + L_p\lambda_p) + (1-q_{fp})\,m_p\pi_p - \tau_p - c^h_f\,(t^{ext}_p + t^{test}_p) \;>\; m_p\pi_p - c^h_f\, t^{tri}_p$$

Tout est mesurable sauf $q_{fp}$ : le modèle de Rex est le modèle qui **estime $q_{fp}$**.

| Élément | Contenu |
|---|---|
| **Choix** | Estimation : Bêta-binomial bayésien par couple (type de FRU, pièce). Décision : échantillonnage de Thompson |
| **Justification de l'estimation** | Peu de données au départ (quelques FRU auditées) ; fournit une incertitude, nécessaire au Monte-Carlo ; se met à jour chaque semaine sans ré-entraînement ; lisible par l'atelier |
| **Justification de la décision** | On n'observe l'état d'une pièce que si on la teste. Une règle qui suit la moyenne estimée ne teste jamais une pièce jugée mauvaise au départ et ne corrige donc jamais un a priori trop pessimiste. Thompson tire chaque période un $q$ plausible dans l'a posteriori et optimise la ligne avec ce tirage : les pièces incertaines sont essayées de temps en temps, de moins en moins à mesure que l'audit tranche. C'est un bandit, la forme la plus simple d'apprentissage par renforcement qui règle ce problème |
| **Paramètres** | A priori $q^0_{fp} = (1 - \rho_f\, d_{fp})(1 - b_p)\,r_p$ avec $d_{fp} = \dfrac{\text{pièces consommées} \times (1 - \text{part préventive})}{\text{FRU réparées} \times n_{fp}}$ ; $\rho_f \ge 1$ facteur « FRU rebutée plus abîmée » ; $b_p$ casse au démontage ; $r_p$ rendement du test. Hyperparamètre : force de l'a priori $N_0$ (pièces équivalentes) |
| **Entraînement** | Données = audit de démontage (date, type de FRU, pièce, pièces testées, pièces bonnes). A posteriori : $q_{fp} \sim \text{Bêta}(q^0 N_0 + \text{bonnes},\ (1-q^0) N_0 + \text{mauvaises})$. $N_0$ réglé sur la log-perte |
| **Validation** | Prequentielle : chaque lot d'audit est prédit avec ce que le modèle savait avant, puis sert à le mettre à jour. Aucune donnée ne sert à apprendre et à noter |
| **Métriques d'estimation** | Brier (0 parfait, 0,25 = pile ou face) ; log-perte ; écart absolu moyen entre taux prédit et observé ; couverture de l'intervalle prédictif à 90 % (cible ≈ 90 %) |
| **Métrique de décision** | Regret cumulé = gain d'un oracle qui connaîtrait $q$ − gain obtenu ; mesuré sur banc d'essai synthétique (`erc.rex.simuler_politiques`), puis suivi en réel par l'écart entre marge prévue et marge constatée |
| **Références à battre** | « A priori seul » (consommation, jamais mise à jour) et « fréquence observée » (sans a priori) |
| **Sortie** | (bas 5 %, moyenne, haut 95 %) de $q_{fp}$ → `p_reutilisable` de la ligne de tri |
| **Évolution** | Régression logistique ou gradient boosting sur l'âge du donneur, le motif de rebut, l'atelier, quand l'audit dépasse quelques centaines de pièces, et seulement s'ils battent le Bêta-binomial sur ces métriques. Apprentissage par renforcement à plusieurs états : seulement si un stock entre périodes est autorisé, car la décision d'une semaine engage alors les suivantes |

**Résultat du banc d'essai synthétique** (a priori 0,2 alors que 60 % des pièces sont bonnes, seuil de réemploi 0,27) : la règle « a priori seul » et la règle gloutonne ne testent jamais la pièce et perdent 17 € par pièce ; Thompson en teste 97 %, retrouve $q \approx 0{,}59$ et perd 0,6 € par pièce. Chiffres de simulation, pas de l'ERC.

Fichier d'audit attendu dans le dossier des extractions : `Acquisition/audit_demontage.csv`, colonnes `Date;Type de FRU;Pièce;Pièces testées;Pièces bonnes`.

## 9. Du flux d'entrée au modèle

L'étape « flux » du pipeline (notebook `02_Flux_entree.ipynb`) produit les tableaux qui conditionnent le modèle :

1. **Composant, FRU, type de déchet** : une ligne par couple (FRU, composant), avec benne et poids.
2. **FRU rebutées par semaine et par type** : c'est $N_{ft}$. Une semaine sans rebut compte pour 0. Le rebut annuel (bas, moyen, haut) en est tiré par ré-échantillonnage des semaines et repris automatiquement par le modèle de ligne.
3. **Semaine, valeur estimée et mesurée, marge d'erreur, cause de déviation** : masse estimée (SQL × poids unitaires) avec ses bornes, masse pesée, écart, causes candidates, cause constatée.

Quand l'écart cumulé d'un flux tient dans la marge sur au moins trois semaines, $N_{ft}$, $m_p$ et les types de déchet de ce flux alimentent le modèle ; sinon la cause dominante désigne la donnée à corriger d'abord.
