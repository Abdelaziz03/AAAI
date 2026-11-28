# Les deux papiers de conférence : ce que chaque appel exige

Lu les 27 et 28 novembre 2026 **dans des extraits de recherche** des appels à communications, recoupés par un second
lecteur indépendant. Les sites officiels n'étaient pas joignables depuis l'environnement de travail : chaque point est
à relire sur la page elle-même avant de s'y fier.

## KDD 2027, piste Applied Data Science (dossier `kdd/`)

| Point | Ce qui a été lu |
|---|---|
| Lieu et dates | San Jose, Californie, 1er au 5 août 2027 |
| Échéance du cycle 2 | **non publiée**. L'an dernier : résumé le 1er février, papier le 8 février. Projection non officielle : 31 janvier et 7 février 2027 |
| Longueur | 8 pages de contenu, puis références et annexe sans limite à la soumission ; version finale : 9 pages de contenu + 3 pages pour références et annexe réunies |
| Gabarit | ACM `acmart`, option `sigconf,review` |
| Anonymat | **aucun** : noms et affiliations obligatoires, leur absence vaut rejet |
| Ce que la piste exige | une application **déployée**, avec une **mesure des performances après mise en service**. Sans elle : rejet sans relecture. Des essais hors ligne, même sur données réelles, ne comptent pas |
| IA générative | la politique de l'ACM demande de déclarer son usage dans le papier |
| Soumission | OpenReview ; au plus 5 papiers par auteur ; résumé et liste d'auteurs figés à l'échéance du résumé |

**Conséquence.** Tel qu'il est, le papier `kdd/` n'est pas soumissible : ses essais sont synthétiques et son étude de cas
tourne sur des données fictives. Il le devient quand le dossier a tourné sur vos données, avec de vrais utilisateurs,
et que la section « Deployment and post-launch results » est remplie de mesures réelles. Un pilote limité peut
suffire dans des domaines très réglementés ; rien ne dit qu'un centre de réparation en fasse partie.

## ICAPS 2027, piste principale (dossier `icaps/`)

| Point | Ce qui a été lu |
|---|---|
| Lieu et dates | Columbia, Caroline du Sud, 27 juin au 2 juillet 2027 ; présentation en personne par un auteur |
| Échéances | résumé le **7 décembre 2026**, papier le **14 décembre 2026** (23 h 59, UTC−12) |
| Longueur | 8 pages, plus des pages de références seulement ; pas d'annexe dans le papier ; un supplément anonyme séparé (100 Mo au plus) |
| Gabarit | kit auteur AAAI-27, **non téléchargeable d'ici** : le brouillon est dans une mise en page voisine, à transporter dans le kit |
| Anonymat | double aveugle : ni noms, ni affiliation, ni lien identifiant |
| Pistes | piste principale et piste « Planning Under a Different Name » ; plus de piste applications cette année |
| Reproductibilité | à écrire **dans le papier** : machine, système, limites de temps et de mémoire, jeux d'essai, versions ; pour un modèle de langage : identifiant exact, paramètres, consignes, dates |
| IA générative | clause 2027 **non trouvée**. Éditions 2025 et 2026 : le texte doit être **écrit par des humains**, l'IA ne servant qu'à polir un texte déjà écrit par les auteurs |
| Double soumission | interdit de soumettre ailleurs le même travail pendant la relecture (14 décembre 2026 au 26 février 2027) |

**Conséquences.**

- Si la règle des années précédentes est maintenue, le brouillon `icaps/` ne peut pas être soumis tel quel : il vous
  sert de plan, de démonstrations et de résultats, et le texte est à réécrire par vous. À vérifier sur l'appel 2027.
- Le sujet est jugé moyennement adapté : le papier doit se présenter comme un travail de modélisation et d'algorithmes
  motivé par une application, pas comme une application déployée.
- Les papiers `kdd/` et `icaps/` portent sur deux couches différentes du même système (connaissance, planification)
  pour ne pas se recouvrir. Ni l'un ni l'autre ne doit reprendre le manuscrit de revue s'il est en relecture.

## La bibliographie

`kdd/references.bib` et `icaps/references.bib` portent, dans la note de chaque entrée, son niveau de vérification :
notice vue dans un extrait de recherche, ou citée de mémoire. Aucune n'a été rapprochée de l'article lui-même.

## Commandes

```bash
python -m erc.papier --demo --compiler --papier kdd
```

```bash
python -m erc.papier --demo --overleaf --papier icaps
```

Sans `--demo`, les mêmes commandes écrivent les versions à vos chiffres (`*_site.pdf`), qui ne sont ni versionnées ni
mises dans l'archive du dossier.
