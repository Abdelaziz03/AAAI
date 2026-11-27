# Installer le dossier sur un poste verrouillé

Cette archive contient tout le dossier. Une fois déposée, elle ne demande aucun échange avec l'extérieur : elle se diagnostique elle-même et dit quoi faire. Rien n'est envoyé hors du poste.

## En un geste

Décompresser l'archive dans un dossier où vous avez le droit d'écrire, puis **double-cliquer sur `Lancer.bat`** (Windows) ou lancer `./lancer.sh`. Le poste est diagnostiqué, les calculs sont faits, la composition des pièces est lancée et une note de décision est écrite dans `artefacts/agent/`. Avec un modèle de langage hébergé sur le poste, ce sont des agents qui pilotent et rédigent ; sans modèle, un plan fixe fait le même enchaînement.

## Ou pas à pas, en trois gestes

1. **Décompresser** l'archive dans un dossier où vous avez le droit d'écrire (Documents, par exemple). Aucun droit d'administrateur n'est nécessaire.
2. Ouvrir une invite de commandes **dans le dossier `erc_circularite`** et lancer :

```bash
python -m erc.diagnostic
```

3. **Suivre la liste « À faire »** qu'elle affiche. Le même rapport est écrit dans `artefacts/Diagnostic.txt` (en démonstration : `demo/artefacts/Diagnostic.txt`).

La commande vérifie Python et les paquets, compare les fichiers à la liste d'empreintes de l'archive, regarde la carte graphique, cherche un serveur de modèle sur ce poste, et dit quel modèle tient dans la carte. Elle ne contacte que ce poste, n'installe rien et ne modifie rien.

## Ensuite

| Pour | Commande |
|---|---|
| tout enchaîner et écrire la note de décision (agents, ou plan fixe sans modèle) | `python -m erc.agent` |
| lancer tout le dossier | `python -m erc` |
| la composition des pièces | `python -m erc.composition` |
| écrire le réglage du modèle d'après ce qui tourne sur le poste | `python -m erc.diagnostic --regler` |
| vérifier le modèle | `python -m erc.modele --verifier` |
| améliorer les conseils du modèle avec vos validations | `python -m erc.modele --optimiser` |
| mettre vos chiffres dans le manuscrit (PDF à part, qui ne quitte pas le poste) | `python -m erc.papier --compiler` |

Les résultats sont dans `artefacts/` (en démonstration : `demo/artefacts/`) : tables, classeurs Excel, et deux pages qui s'ouvrent dans un navigateur sans connexion (`outil/ERC_Outil_Decision.html`, `composition/ERC_Composition_Revue.html`).

Sans les extractions réelles, le dossier tourne en démonstration, sur des données fictives. Pour les données réelles, indiquer leur dossier une fois :

```bash
python -c "import erc; erc.memoriser_chemins(r'CHEMIN_DES_EXTRACTIONS')"
```

## Ce dont le dossier a besoin

- **Python 3.9 ou plus récent**, et quatre paquets : `numpy`, `pandas`, `openpyxl`, `matplotlib`.
- **Jupyter est facultatif** : sans lui, tout passe par les commandes ci-dessus et les pages HTML.
- **Le modèle de langage est facultatif** : sans lui, la composition des pièces s'arrête aux sources gratuites (règles, pièces voisines déjà validées, classement existant) et le reste du dossier n'est pas touché.

## Installer les paquets hors ligne

Si le poste n'a pas accès à internet, préparer les paquets sur un autre poste du même système et de la même version de Python :

```bash
pip download -r requirements.txt -d paquets
```

Copier le dossier `paquets` sur le poste verrouillé, puis :

```bash
pip install --no-index --find-links paquets -r requirements.txt
```

## Si la sécurité du poste bloque quelque chose

- **`python` introuvable** : essayer `py -m erc.diagnostic`. Si Python n'est pas installé, c'est la seule demande à faire au service informatique.
- **Écriture refusée** : déplacer le dossier dans un répertoire personnel.
- **Serveur de modèle bloqué ou impossible à installer** : le dossier fonctionne sans. Le modèle n'écoute que ce poste (`localhost`) ; c'est ce qu'il faut dire au service informatique s'il pose la question.
- **`nvidia-smi` bloqué** : le diagnostic le signale et propose le plus petit modèle.

## Si vous restez bloqué

Un seul fichier suffit pour demander de l'aide : le rapport `Diagnostic.txt`. Il ne contient ni données du dossier, ni nom de machine, ni chemin complet.

Guide du modèle hébergé chez vous : `docs/Modele_local.md`. Du poste de travail au poste puissant puis à la machine virtuelle : `deploiement/LISEZ-MOI.md`. Le manuscrit : `papier/LISEZ-MOI.md`.
