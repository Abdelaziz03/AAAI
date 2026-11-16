# Modèle : ligne de démontage et de tri contre le recycleur actuel

Formulation du modèle codé dans `erc_ligne_tri.py`. Entre parenthèses : le nom du champ dans le code.

## 1. Question posée

Aujourd'hui, une FRU rebutée part entière dans la benne DEEE du recycleur actuel (coût de traitement, pas de recette). Faut-il installer une ligne qui ouvre ces FRU pour **réemployer** certaines pièces et **trier** les autres vers des acheteurs qui paient au kilo, et si oui, pour quelles FRU et quelles pièces ?

## 2. Ensembles

| Symbole | Ensemble |
|---|---|
| $f \in F$ | types de FRU rebutées (ex. SSSA `5453107-2-R`) |
| $p \in P_f$ | pièces contenues dans une FRU de type $f$ |
| $o \in O = \{1, 2, 3\}$ | option d'une pièce : 1 démontage + réemploi, 2 tri + recyclage, 3 laissée dans la FRU (recycleur actuel) |
| $s \in S_f$ | plans de traitement d'une FRU $f$ : une option par pièce ; $s_0$ = tout en option 3 = FRU non ouverte |
| $w \in W$ | semaines (flux d'entrée et suivi terrain) |

## 3. Paramètres (variables de coût et de valeur)

**Flux d'entrée**

| Symbole | Sens | Champ | Source |
|---|---|---|---|
| $N_f$ | FRU rebutées par an | `rebut_an` | vwERT, suivi hebdomadaire |
| $m_f$ | masse d'une FRU (kg) | `poids_fru_kg` | pesée |
| $n_{fp}$ | exemplaires de $p$ dans $f$ | `n_par_fru` | audit de démontage |
| $m_p$ | masse d'une pièce (kg) | `poids_kg` | pesée, fiche |

**Main-d'œuvre**

| Symbole | Sens | Champ |
|---|---|---|
| $t^{ouv}_f$, $t^{tri,ouv}_f$ | ouverture soignée / sommaire d'une FRU (h) | `ouverture_min`, `ouverture_tri_min` |
| $t^{ext}_p$, $t^{test}_p$, $t^{tri}_p$ | extraction, test, tri d'un exemplaire (h) | `extraction_min`, `test_min`, `tri_min` |
| $c^{h}_f$ | coût horaire hors plan de charge, selon le type de FRU (€/h) | `taux_horaire_eur` |
| $H$ | heures opérateur disponibles par an | `heures_operateur_an` |

**Valeur**

| Symbole | Sens | Champ |
|---|---|---|
| $q_p$ | probabilité qu'un exemplaire extrait soit réutilisable | `p_reutilisable` |
| $v_p$ | valeur d'une pièce réemployée (€) | `valeur_eur` |
| $L_p$, $\lambda_p$ | délai d'approvisionnement (semaines), valeur d'une semaine évitée (€) | `delai_semaines`, `valeur_semaine_eur` |
| $\pi_p$ | prix payé par le recycleur acheteur (€/kg) | `prix_recycleur_eur_kg` |
| $\tau_p$ | transport par pièce réemployée (€) | `transport_eur` |

**Situation actuelle et ligne**

| Symbole | Sens | Champ |
|---|---|---|
| $c^{trait}$ | coût de traitement du recycleur actuel (€/kg ; 0 si gratuit, négatif s'il paie) | `cout_traitement_eur_kg` |
| $I$, $A$ | investissement d'installation (€), durée d'amortissement (ans) | `cout_installation_eur`, `amortissement_ans` |
| $C^{fix}$ | coûts fixes annuels : place, encadrement, étalonnage (€/an) | `couts_fixes_annuels_eur` |

$q_p$ vient de la consommation : $q_p = (1 - \rho_f \cdot d_p)(1 - b_p)\,r_p$ avec $d_p = \dfrac{\text{pièces consommées} \times (1 - \text{part préventive})}{\text{FRU réparées} \times n_{fp}}$, $\rho_f \ge 1$ le facteur « FRU rebutée plus abîmée », $b_p$ la casse au démontage, $r_p$ le rendement du test.

## 4. Variables de décision

| Variable | Sens |
|---|---|
| $x_{fs} \ge 0$ | nombre de FRU de type $f$ traitées par an selon le plan $s$ |
| $y \in \{0, 1\}$ | installer la ligne (1) ou garder la situation actuelle (0) |

Le plan $s$ fixe l'option $o_s(p)$ de chaque pièce. Les FRU non traitées ($x_{f s_0}$) restent chez le recycleur actuel.

## 5. Fonctions de valorisation (par FRU, plan $s$)

$$V^{1}_{fp} = n_{fp}\,\big[\,q_p\,(v_p + L_p \lambda_p) + (1 - q_p)\,m_p \pi_p - \tau_p\,\big] \qquad \text{réemploi ; l'exemplaire qui échoue au test est vendu au kg}$$

$$V^{2}_{fp} = n_{fp}\, m_p\, \pi_p \qquad \text{recyclage trié}$$

$$E_{fs} = c^{trait} \sum_{p:\,o_s(p) \in \{1,2\}} n_{fp}\, m_p \qquad \text{traitement évité : masse sortie de la benne actuelle}$$

$$V_{fs} = \sum_{p:\,o_s(p)=1} V^{1}_{fp} + \sum_{p:\,o_s(p)=2} V^{2}_{fp} + E_{fs}$$

## 6. Fonctions de coût

**Temps par FRU**

$$h_{fs} = \underbrace{t^{ouv}_f\,[\exists p : o_s(p)=1] + t^{tri,ouv}_f\,[\nexists\, o_s(p)=1 \wedge \exists p : o_s(p)=2]}_{\text{ouverture, payée une fois}} + \sum_{p:\,o_s(p)=1} n_{fp}\,(t^{ext}_p + t^{test}_p) + \sum_{p:\,o_s(p)=2} n_{fp}\, t^{tri}_p$$

**Coût variable par FRU** : $C^{var}_{fs} = c^{h}_f \cdot h_{fs}$

**Coût fixe annualisé de la ligne** : $C^{ligne} = \dfrac{I}{A} + C^{fix}$

**Coût de la situation actuelle** : $C^{actuel} = c^{trait} \sum_f N_f\, m_f$

## 7. Fonction objectif

Marge d'une FRU traitée selon $s$, par rapport à la situation actuelle : $g_{fs} = V_{fs} - C^{var}_{fs}$, avec $g_{f s_0} = 0$.

$$\max_{x,\,y} \; Z = \sum_{f \in F} \sum_{s \in S_f} g_{fs}\, x_{fs} \;-\; y\, C^{ligne}$$

sous les contraintes

$$\sum_{s} x_{fs} = N_f \quad \forall f \qquad \text{(chaque FRU rebutée reçoit un plan)}$$

$$\sum_{f}\sum_{s} h_{fs}\, x_{fs} \le H\, y \qquad \text{(capacité en heures ; aucune heure sans ligne)}$$

$$x_{fs} \ge 0,\quad y \in \{0,1\}$$

$Z$ est le **gain annuel par rapport au recycleur actuel**. On installe la ligne si $Z^* > 0$. Coût total avec la ligne $= C^{actuel} - Z^*$.

**Résolution.** À $y = 1$, le problème est linéaire en $x$. Le multiplicateur $\mu$ de la contrainte d'heures donne, pour chaque type de FRU, le plan qui maximise $g_{fs} - \mu\, h_{fs}$ ; $\mu$ est trouvé par dichotomie. **$\mu$ est la valeur nette d'une heure opérateur supplémentaire.**

**Indicateurs dérivés.** Seuil de rentabilité $= C^{ligne} / \bar g$ (FRU par an) ; retour sur investissement $= I / (\sum g\,x - C^{fix})$ ; part de masse détournée $= \sum \text{kg sortis} / \sum_f N_f m_f$.

## 8. Incertitude

Tout paramètre peut être une plage (bas, haut) ou un triangle (bas, mode, haut). Le problème est résolu pour chaque tirage (Monte-Carlo) : on obtient la distribution de $Z^*$ et $P(Z^* > 0)$, la probabilité que la ligne soit rentable.

## 9. Hypothèses

1. **Régime annuel stationnaire** : $N_f$ constant ; à vérifier avec le suivi hebdomadaire du flux d'entrée.
2. **Linéarité** : temps et valeurs proportionnels au nombre de FRU ; pas d'effet d'apprentissage ni de lot minimal de l'acheteur.
3. **Capacité = heures opérateur** : la place et le banc de test ne sont pas limitants (à ajouter comme contraintes si l'audit le montre).
4. **Indépendance des pièces** dans une FRU : l'état d'une pièce ne dépend pas de celui des autres ; $\rho_f$ corrige en moyenne.
5. **Tout ce qui est réemployable est absorbé** par la demande de réparation (à borner par la consommation : contrainte $\sum_f n_{fp} q_p x \le D_p$ à ajouter si une pièce sature).
6. **Poids inconnu** : aucun traitement évité compté pour la pièce (prudent).
7. **La carcasse** (châssis, tôlerie) reste chez le recycleur actuel, sauf si elle est déclarée comme une « pièce » avec son poids, son prix au kg et son temps de tri. C'est elle qui porte l'essentiel de la masse.
8. **Valeur de réemploi** $v_p$ : fraction du MMICV à fixer par l'équipe concernée ; elle n'est pas un prix de vente.
9. **Fiabilité** : $q_p$ ne couvre que l'état à l'extraction ; la tenue en service d'une pièce réemployée (taux ELF réparé / neuf, survie sur la garantie) se retranche de $v_p$ via le coût d'une défaillance terrain (voir `erc_fiabilite_risques.valeur_voies`).

## 10. Du flux d'entrée au modèle

Le modèle est alimenté à la granularité où le flux est vérifié (`erc_flux_hebdo.py`, notebook `ERC_Flux_Entree_Suivi_Hebdo.ipynb`) :

1. tableau composants → type de déchet → benne ;
2. par semaine et par flux : masse estimée (SQL × poids unitaires) avec marge d'erreur, masse pesée, écart, cause ;
3. quand l'écart tient dans la marge sur plusieurs semaines, $N_f$, $m_p$ et les types de déchet sont jugés fiables et alimentent le modèle ; sinon la cause (poids manquants, benne partagée, décalage des bacs) désigne la donnée à corriger d'abord.
