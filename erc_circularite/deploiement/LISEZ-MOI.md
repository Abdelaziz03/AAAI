# Du poste de travail au poste puissant, puis, plus tard, à la machine virtuelle

Le même dossier tourne à trois échelles. Ce qui change de l'une à l'autre tient dans un fichier de réglage,
`parametres/modele_local.cfg`. Les calculs, eux, sont les mêmes partout : un modèle plus gros lit mieux les
descriptions et rédige mieux la note, il ne change aucun chiffre.

| Étape | Machine | Modèle de langage | Ce qu'on y prouve |
|---|---|---|---|
| 1. Preuve de concept | ce poste, sans carte graphique | aucun, ou un petit | tout l'enchaînement tourne, de bout en bout |
| 2. Passage à l'échelle | le poste puissant (carte graphique) | un modèle plus gros | lecture de toute la nomenclature, agents |
| 3. Machine virtuelle (plus tard) | un serveur à vous | le même, en conteneur | le dossier tourne sans poste dédié |

## 1. Preuve de concept, sur ce poste

1. Décompresser `ERC_circularite_<version>.zip`.
2. Double-cliquer sur `Lancer.bat` (ou `./lancer.sh`).

Le poste est diagnostiqué, les sept étapes sont calculées, la composition des pièces est lancée, la note de décision
est écrite. Sans modèle de langage, un plan fixe fait l'enchaînement et remplit une note type : c'est la preuve que
tout tourne. Rien ne sort du poste.

Pour voir les agents à l'œuvre sur ce poste, installer un serveur de modèle local et un petit modèle, puis :

```bash
python -m erc.diagnostic --regler
```

```bash
python -m erc.agent
```

La première commande écrit le réglage d'après ce qui tourne sur le poste ; la seconde relance tout, cette fois
piloté par le modèle.

## 2. Passage à l'échelle, sur le poste puissant

Deux façons, selon l'endroit où sont les données.

**Tout sur le poste puissant** (le plus simple, et c'est là que sont vos données) : y déposer la même archive, y
installer le serveur de modèle, lancer `Lancer.bat`. Le diagnostic lit la mémoire de la carte graphique et propose
une taille de modèle qui y tient.

**Le poste puissant sert le modèle, un autre poste fait les calculs** : sur le poste de calcul, écrire dans
`parametres/modele_local.cfg` l'adresse du poste puissant et le déclarer :

```
[modele]
url = http://nom-du-poste-puissant:11434/v1
nom = <nom du modèle sur ce serveur>
serveurs_de_confiance = nom-du-poste-puissant
```

Sans cette déclaration, le dossier refuse le serveur : un modèle qui n'est ni sur ce poste ni sur une machine
déclarée ne lit jamais une description interne. Sur un réseau partagé, passer par un tunnel SSH ou par https
(`docs/Modele_local.md`, sections 1, 3 et 4).

Vérifier, puis lancer :

```bash
python -m erc.modele --verifier
```

```bash
python -m erc.agent
```

Quand une trentaine de pièces ont été validées dans la page de revue, faire apprendre au modèle de meilleurs conseils
de lecture, sur vos validations, sans rien entraîner :

```bash
python -m erc.modele --optimiser
```

## 3. Machine virtuelle (pour plus tard)

Rien de ce qui précède n'en dépend : cette étape peut attendre. La recette est prête et a été essayée avec une doublure de
modèle (voir la fin de cette page).

Deux conteneurs sur un réseau interne sans sortie : le dossier, et le serveur de modèle. Aucun port n'est publié.
Les données entrent par un volume en lecture seule ; ce que le dossier écrit reste sur la machine, hors de l'image.

Préparer, depuis le dossier `erc_circularite` :

```bash
cp deploiement/.env.exemple deploiement/.env
```

Écrire dans `deploiement/.env` le chemin de vos extractions. Puis créer les dossiers que le dossier remplira, et les
donner au compte sans privilège du conteneur (numéro 10001) :

```bash
mkdir -p deploiement/volumes/parametres deploiement/volumes/artefacts deploiement/volumes/cortex deploiement/volumes/papier_site
```

```bash
sudo chown -R 10001:10001 deploiement/volumes
```

```bash
cp deploiement/reglage_du_modele.exemple deploiement/volumes/parametres/modele_local.cfg
```

Construire l'image, indiquer une fois où sont les données, lancer :

```bash
docker compose -f deploiement/compose.yaml build erc
```

```bash
docker compose -f deploiement/compose.yaml run --rm --entrypoint python erc -c "import erc; erc.memoriser_chemins('/donnees')"
```

```bash
docker compose -f deploiement/compose.yaml run --rm erc
```

La dernière commande enchaîne tout et écrit la note dans `deploiement/volumes/artefacts/agent/`. Toute autre commande
du dossier se lance de la même façon, par exemple `... run --rm erc erc.diagnostic` ou `... run --rm erc erc.papier`.

**Le modèle.** Les poids du modèle doivent être déposés une fois dans le volume `modeles`, depuis un réseau qui peut
les télécharger : c'est la seule étape qui demande internet, et elle dépend du serveur choisi (suivre sa
documentation). Écrire ensuite le nom du modèle à la ligne `nom =` du réglage. Sans modèle, le dossier tourne quand
même : plan fixe et note type.

## Ce qui a été essayé, et ce qui ne l'a pas été

Essayé ici, sous Linux, le 27 novembre 2026 :

- l'image se construit, et ne contient ni données, ni paramètres, ni cortex ;
- le conteneur enchaîne tout le dossier en démonstration **sans aucun réseau**, sous un compte sans privilège ;
- la topologie de `compose.yaml` : le dossier joint le serveur de modèle par son nom sur le réseau interne, le
  serveur est accepté parce qu'il est déclaré, les agents tournent dessus, un nombre inventé par le modèle est
  signalé en tête de note, un outil hors liste demandé par le modèle n'est pas exécuté, les données montées sont en
  lecture seule, et le conteneur ne peut joindre aucune adresse extérieure. Le serveur de modèle était une
  **doublure** (un petit programme qui répond à sa place).

Pas essayé :

- **le vrai serveur de modèle** du fichier `compose.yaml` (image `ollama/ollama`, variables `OLLAMA_NO_CLOUD` et
  `OLLAMA_CONTEXT_LENGTH`) : nom d'image et variables relevés dans la documentation du serveur, jamais lancés ici ;
- **la carte graphique dans le conteneur** (bloc commenté de `compose.yaml`) ;
- **Windows** : ni `Lancer.bat`, ni Docker Desktop. Sous Docker Desktop, l'étape `chown` est en général inutile ;
- **un vrai modèle**, à toutes les étapes : agents, lecture des descriptions et amélioration des conseils n'ont
  tourné qu'avec des doublures. Les noms de modèles proposés par le diagnostic viennent de sources secondaires et
  sont à vérifier dans le catalogue du serveur ;
- **vos données réelles**.
