# Le manuscrit

`manuscrit.pdf` est la version compilée, lisible tout de suite. Elle porte un bandeau « Demonstration data » tant que
les chiffres de l'étude de cas viennent des données fictives du dossier.

## Mettre vos chiffres dans le papier

Sur le poste qui a vos données, depuis le dossier `erc_circularite` :

```bash
python -m erc.papier --compiler
```

Cette commande refait tous les calculs sur vos données, écrit le dossier `site/` (chiffres, corps des tableaux,
figures) et compile `manuscrit_site.pdf` : le même papier, avec vos chiffres et sans le bandeau. Rien dans `site/`
ne se tape à la main.

**Vos chiffres ne partent pas sur GitHub.** Le dossier `site/` et `manuscrit_site.pdf` sont exclus du dépôt
(`.gitignore`) et de l'archive (`outils/empaqueter.py`). La version de démonstration (`genere/`, `manuscrit.pdf`)
est la seule versionnée.

Deux options :

- `--echelle 0.4` multiplie tous les montants de l'étude de cas par un facteur que vous gardez pour vous ; le papier
  dit alors que les montants sont multipliés par une constante non publiée.
- sans `--compiler`, seuls les chiffres sont réécrits. Sans LaTeX sur le poste (MiKTeX ou TeX Live), compiler
  ailleurs : copier le dossier `papier/` et lancer `pdflatex manuscrit_site`, `bibtex manuscrit_site`, puis
  `pdflatex manuscrit_site` deux fois. Attention : un service en ligne comme Overleaf recevrait alors vos chiffres.

Ce qui sort du dossier vers le papier : des agrégats seulement. Ni code article, ni description de pièce, ni nom de
type de FRU. Un test le vérifie (`tests/test_papier.py`).

## Ce qui reste à écrire par vous

Les passages en rouge « To write after the run on site data » marquent ce qu'aucun programme ne peut écrire à votre
place : la description du site, la lecture de vos résultats, les décisions prises, le modèle de langage réellement
utilisé, les remerciements. Il y en a une douzaine, tous dans les sections 7, 9 et 10. Chercher `\apres{` dans
`sections/`.

À remplacer aussi : les auteurs et l'affiliation, dans `document.tex` (ligne `\author`).

## Ce qui est vérifié, et ce qui ne l'est pas

Vérifié ici :

- le manuscrit compile (35 pages) ;
- chaque macro employée dans le texte est écrite par `erc.papier`, chaque référence citée existe dans
  `references.bib` ;
- les résultats mathématiques sont contrôlés par des essais numériques : propositions 1 à 7 (tests antérieurs),
  borne de la proposition 9 contre simulation, formule du biais de la proposition 10, invariant de budget du lemme 1,
  contrôle des nombres du lemme 3.

Pas vérifié :

- **Aucun relecteur humain n'a lu les démonstrations.** Elles ont été relues par des agents automatiques et par des
  essais numériques. Ce n'est pas une relecture par les pairs : à faire relire par un collègue de recherche
  opérationnelle avant toute soumission.
- **Les références.** Celles dont la note dit « to verify » dans `references.bib` ont été citées de mémoire. Les
  autres ont été rapprochées d'une notice d'éditeur, pas de l'article. Ce que chaque article contient est décrit
  d'après son résumé. Tout est à contrôler sur les textes.
- **La nouveauté.** L'affirmation que les contributions ne figurent pas dans la littérature repose sur des résumés et
  une dizaine de recherches ciblées. À confirmer par une recherche systématique.
- **Le modèle de langage.** Les agents, la lecture des descriptions et l'amélioration des consignes n'ont tourné
  qu'avec des doublures. Leur comportement avec un vrai modèle est à mesurer sur votre poste.

## Avant de viser l'INFORMS Journal on Applied Analytics

- La revue demande, pour un article d'application, une **lettre de vérification** d'une personne de l'organisation
  qui n'est pas auteur, confirmant que le travail est utilisé et quels bénéfices il a apportés. Sans ligne pilote en
  service, cette lettre ne peut pas être écrite : le papier n'est soumissible là qu'après le pilote. (Lu en novembre
  2026 dans des extraits de recherche des pages de la revue, pas sur les pages elles-mêmes : à relire sur le site.)
- Le manuscrit est en classe `article` standard. La revue a son propre gabarit LaTeX, à télécharger sur son site ; le
  texte, les énoncés et la bibliographie s'y transportent tels quels.
- Les revues INFORMS demandent de déclarer l'usage d'outils d'intelligence artificielle générative. Le paragraphe
  « Disclosure » de la section 10 le fait ; à adapter à la règle en vigueur le jour de la soumission.
- Un prix du meilleur article ne se promet pas. Ce que le manuscrit a pour lui : un problème réel, une structure
  mathématique démontrée, un système qui tourne et des essais reproductibles. Ce qui lui manque encore : des résultats
  de terrain, et un pilote.

## Contenu du dossier

| Fichier | Rôle |
|---|---|
| `document.tex` | le papier : préambule, résumé, enchaînement des sections. Ne se compile pas seul |
| `manuscrit.tex` | enveloppe « démonstration » : lit `genere/`, donne `manuscrit.pdf` |
| `manuscrit_site.tex` | enveloppe « vos données » : lit `site/`, donne `manuscrit_site.pdf` |
| `sections/01` à `10` | le texte |
| `sections/A_proofs.tex` | toutes les démonstrations |
| `sections/B_reproducibility.tex` | commandes, correspondance texte ↔ code ↔ tests |
| `references.bib` | bibliographie |
| `genere/` | écrit par `python -m erc.papier --demo` : `macros.tex`, corps des tableaux `t_*.tex`, figures `fig_*.pdf` |
| `site/` | la même chose sur vos données, écrit par `python -m erc.papier` ; absent du dépôt et de l'archive |
