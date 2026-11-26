# Héberger le modèle de langage chez vous

Les données du dossier sont privées. Le modèle de langage tourne donc sur une machine qui vous appartient, de préférence celle qui détient les données. Ce guide dit comment le brancher, ce qui circule, et comment choisir le modèle.

État de ce guide : les réglages des serveurs viennent de leur documentation, lue le 26 novembre 2026 dans leurs dépôts officiels. Aucune commande n'a été exécutée contre un vrai serveur pour ce dossier, et les noms de modèles viennent d'extraits de recherche, pas des pages officielles : tout est à confirmer sur votre machine, ce que `python -m erc.modele --verifier` fait en une commande.

## 1. Trois montages

| Montage | Adresse à régler | Ce qu'il faut de plus |
|---|---|---|
| **A. Tout sur la machine puissante** : le dossier, les données et le modèle | `http://localhost:PORT/v1` | rien : rien ne quitte la machine |
| **B. Le dossier sur un autre poste, par un tunnel SSH** | `http://localhost:PORT/v1` | `ssh -N -L PORT:127.0.0.1:PORT utilisateur@machine-puissante`, laissé ouvert |
| **C. Le dossier sur un autre poste, par le réseau** | `http://machine-puissante:PORT/v1` | déclarer la machine, une clé, et de préférence https |

Le montage A est le plus simple et le plus sûr. Le montage B garde le serveur fermé sur lui-même (il n'écoute que sa propre machine) et chiffre la liaison. Le montage C demande que le serveur sache exiger une clé.

## 2. Ce qui circule

| Donnée | Qui la reçoit |
|---|---|
| Description interne d'une pièce | le modèle **privé** seulement (ce poste, ou une machine que vous avez déclarée) |
| Texte d'un document public retrouvé | le modèle, privé ou non |
| Fabricant, référence du fabricant, type générique | le service de collecte de documents, si vous en branchez un |
| Code article interne, volumes, coûts, validations | personne : ils restent dans le dossier |

Le modèle ne construit jamais une requête vers l'extérieur : les requêtes de collecte sont faites des seuls champs de la nomenclature, avant tout appel au modèle. Un document piégé peut au pire lui faire proposer une mauvaise classe, traitée comme n'importe quelle erreur de source. Des tests le vérifient (`tests/test_modele.py`).

Un serveur qui n'est ni ce poste ni dans votre liste de machines est refusé. On peut l'accepter explicitement (`distant=True` en Python, `--distant` en ligne de commande) : il ne reçoit alors que des documents publics, jamais une description.

## 3. Mise en route

```bash
python -m erc.modele --preparer
```

crée `parametres/modele_local.cfg`. Ce fichier n'est jamais réécrit par le dossier et ne va pas dans le dépôt. Y renseigner :

```ini
[modele]
url = http://localhost:11434/v1
nom = nom-du-modele-sur-le-serveur
serveurs_de_confiance =            ; montage C : nom ou adresse de votre machine
cle_env = ERC_MODELE_CLE           ; la clé se met dans cette variable d'environnement, pas dans le fichier
lire_les_descriptions = oui
```

Puis :

```bash
python -m erc.modele --verifier
```

La commande liste les modèles du serveur, pose trois questions d'essai sur un texte fictif, mesure le délai, et dit ce qui ne va pas. Si le modèle écrit un raisonnement avant de répondre, elle essaie les réglages connus qui le coupent et donne la ligne `corps_supplementaire = …` à recopier dans le fichier.

Ensuite la chaîne de composition utilise ce modèle d'elle-même :

```bash
python -m erc.composition
```

## 4. Serveurs

| | Adresse par défaut | Clé | Chiffrement | Sorties vers internet à connaître |
|---|---|---|---|---|
| **llama-server** (llama.cpp) | `http://127.0.0.1:PORT/v1`, toujours donner `--port` | `--api-key` | `--ssl-key-file`, `--ssl-cert-file`, si compilé avec OpenSSL | `--offline` les interdit |
| **vLLM** | `http://HÔTE:8000/v1` | `--api-key`, qui ne protège que les chemins sous `/v1` | `--ssl-keyfile`, `--ssl-certfile` | envoie des statistiques d'usage par défaut : `VLLM_NO_USAGE_STATS=1` |
| **Ollama** | `http://127.0.0.1:11434/v1` | aucune | aucun | `OLLAMA_NO_CLOUD=1` ; mises à jour automatiques sous macOS et Windows |
| **LM Studio** | `http://127.0.0.1:1234/v1` | jeton, activé dans l'interface (version 0.4.0 ou plus) | aucun | vérifie les mises à jour à l'ouverture |

Trois pièges :

- **vLLM écoute sur toutes les interfaces si `--host` est omis.** Toujours donner `--host`, et fermer le port par le pare-feu : sa clé laisse d'autres chemins ouverts.
- **Ollama n'a ni clé ni chiffrement.** Le garder sur `127.0.0.1` (montages A ou B).
- **Le contexte par défaut d'Ollama peut être de 4 096 jetons**, trop court pour une longue fiche : le fixer (`OLLAMA_CONTEXT_LENGTH=8192`).

Lancement une fois les poids téléchargés (modèles à adapter) :

```bash
# llama-server : clé, hors ligne, raisonnement coupé
llama-server -m /modeles/fichier.gguf --offline --host 127.0.0.1 --port 8080 --api-key "$ERC_MODELE_CLE" --alias modele-local -c 32768 -np 4 --reasoning off --no-webui

# vLLM : hors ligne, sans statistiques ; les deux derniers réglages pour un modèle Qwen qui « réfléchit »
HF_HUB_OFFLINE=1 VLLM_NO_USAGE_STATS=1 vllm serve ORGANISATION/MODELE --host 127.0.0.1 --port 8000 --api-key "$ERC_MODELE_CLE" --served-model-name modele-local --max-model-len 8192 --reasoning-parser qwen3 --default-chat-template-kwargs '{"enable_thinking": false}'

# Ollama : local seulement
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NO_CLOUD=1 OLLAMA_KEEP_ALIVE=-1 OLLAMA_NUM_PARALLEL=4 OLLAMA_CONTEXT_LENGTH=8192 ollama serve
```

Pour le montage C, remplacer `127.0.0.1` par l'adresse privée de la machine.

## 5. Couper le raisonnement

Les modèles ouverts récents écrivent un raisonnement avant de répondre. Pour des réponses courtes et contraintes comme celles du dossier, cela ralentit sans rien apporter. Le réglage dépend du serveur, d'où le champ `corps_supplementaire` du fichier de réglage :

| Serveur | À écrire |
|---|---|
| Ollama | `corps_supplementaire = {"reasoning_effort": "none"}` |
| vLLM, llama-server | `corps_supplementaire = {"chat_template_kwargs": {"enable_thinking": false}}`, ou le couper au lancement du serveur |
| LM Studio | aucun réglage par requête documenté : le couper dans l'application |

Le dossier tolère un raisonnement resté allumé : il retrouve la réponse, et le signale dans `--verifier`.

## 6. Quel modèle

Aucune évaluation publique ne porte sur la lecture de fiches techniques en français et en anglais avec citation mot pour mot : seul un essai sur vos propres pièces peut trancher. C'est ce que fait :

```bash
python -m erc.modele --comparer modele-a modele-b modele-c
```

Chaque modèle classe vos pièces **validées** d'après leur description ; la réponse est comparée à la classe validée par une personne. La table donne le taux de justes avec son intervalle, la durée moyenne, et dit si l'écart au meilleur peut être dû au hasard. Deux repères y figurent sans aucun modèle : toujours répondre la classe la plus fréquente, et reprendre la classe de la pièce validée la plus proche. Un modèle qui ne bat pas ces repères n'apporte rien. Rien n'est écrit dans le cortex, et rien ne sort : tous les modèles comparés doivent être privés.

Candidats à essayer, relevés le 26 novembre 2026 dans des extraits de recherche et **non vérifiés sur les pages officielles** (confirmer chaque nom sur la page du modèle, ou par `ollama show`) :

| Mémoire de la carte graphique | À essayer | Licence annoncée |
|---|---|---|
| 12 à 16 Go | `qwen3.5:9b`, `gemma4:12b` | Apache 2.0 |
| 24 Go | `qwen3.8:27b-q4_K_M`, `gemma4:31b` | Apache 2.0 |
| 48 Go | les mêmes en 8 bits (`qwen3.8:27b-q8_0`) | Apache 2.0 |
| 80 Go ou plus | `qwen3.8:27b` non quantifié, pour servir plusieurs requêtes à la fois | Apache 2.0 |

Un modèle plus gros n'est pas forcément meilleur ici : mieux vaut comparer deux familles différentes (Qwen et Gemma) que deux tailles de la même.

## 7. Débit

La chaîne envoie les lectures de descriptions plusieurs à la fois (`appels_paralleles`, 4 par défaut dans `composition.Reglages`). Régler le serveur pour autant de requêtes simultanées (`-np 4` pour llama-server, `OLLAMA_NUM_PARALLEL=4` pour Ollama) et garder le modèle chargé. Une lecture déjà faite n'est jamais refaite, sauf si la description ou le modèle change.

## 8. Avant de s'y fier

- [ ] `python -m erc.modele --verifier` répond « Prêt : True ».
- [ ] Le serveur n'écoute que sa machine, ou que l'adresse privée voulue, et le pare-feu ferme son port au reste du réseau.
- [ ] Les réglages hors ligne et sans statistiques du serveur sont posés ; machine débranchée d'internet, tout fonctionne encore.
- [ ] Le serveur ne garde pas les requêtes dans ses journaux (pour Ollama, laisser `OLLAMA_DEBUG_LOG_REQUESTS` non défini).
- [ ] La colonne « référence fabricant » de la nomenclature contient bien des références de fabricant, et le nom de votre entreprise est déclaré dans `fabricants_internes`.
- [ ] Après les premières validations, la page de revue montre la fiabilité mesurée du type de source « modèle : description ».

## 9. Ce qui n'est pas fait

- Aucun vrai modèle n'a été appelé pour ce dossier : les tests utilisent un serveur d'essai.
- La relecture indépendante de ce guide (sécurité, noms de modèles) n'a pas pu être menée à son terme.
- Les modèles de fondation de séries temporelles (Toto, Timestral, Chronos) se branchent par `erc.prevision.enregistrer_modele` sur la machine qui a leurs poids ; aucun adaptateur prêt à l'emploi n'est fourni, faute d'avoir pu vérifier leur interface.
