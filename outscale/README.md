# Outscale CLI (dossierfacile-infra)

Outil CLI minimal pour:
- Déployer des buckets S3-compatibles sur Outscale (idempotent)
- Lister les AccessKeys via l’outil externe oapi-cli

## Installation des dépendances Python

- Assurez-vous d’utiliser un environnement virtuel Python
- Installez les dépendances: `pip install -r requirements.txt`

Variables d’environnement utiles:
- AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (auth S3/OSC)
- AWS_REGION (ex: eu-west-2)
- OUTSCALE_S3_ENDPOINT (ex: https://s3.eu-west-2.outscale.com)
- OSC_ENDPOINT_API (ex: https://api.eu-west-2.outscale.com)

Support du fichier .env (automatique):
- Ce CLI charge automatiquement un fichier `.env` à la racine du projet (python-dotenv).
- Pour oapi-cli, vous pouvez définir dans `.env`:
  - `OUTSCALE_ACCESSS_KEY` (note: triple "s" tel que fourni)
  - `OUTSCALE_SECRET_KEY`
  - `OUTSCALE_REGION`
- Ordre de priorité des identifiants/region pour oapi-cli:
  1) Options CLI `--access-key`, `--secret-key`, `--region`
  2) `.env` variables `OUTSCALE_ACCESSS_KEY`, `OUTSCALE_SECRET_KEY`, `OUTSCALE_REGION` (puis fallback `OUTSCALE_ACCESS_KEY` si présent)
  3) Variables d’environnement `OSC_ACCESS_KEY`/`OSC_SECRET_KEY`/`OSC_REGION`, puis `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_REGION`

## Utilisation

Afficher l’aide générale (le CLI affiche la doc par défaut):
- `python -m outscale`

Aide détaillée:
- `python -m outscale --help`
- `python -m outscale bucket --help`
- `python -m outscale bucket deploy --help`
- `python -m outscale access-key --help`
- `python -m outscale access-key list --help`

### Déployer un bucket
- `python -m outscale bucket deploy --name mon-bucket --region eu-west-2 --endpoint-url https://s3.eu-west-2.outscale.com`
- Tags optionnels: `--tag env=dev --tag owner=infra`
- Auth: via profil (`--profile`), ou variables d’env (AWS_ACCESS_KEY_ID/SECRET)

Comportement:
- Si le bucket existe déjà, aucune erreur n’est levée (idempotent)
- Si le bucket doit être créé hors de `us-east-1`, la contrainte de région est renseignée
- Tags appliqués via PutBucketTagging

### Lister les AccessKeys (oapi-cli)
Pré-requis: installer oapi-cli (npm)
- `npm i -g @outscale/oapi-cli`

Commande:
- `python -m outscale access-key list`

Options:
- `--oapi-bin` pour spécifier le chemin d’oapi-cli
- `--api-endpoint` ou `OSC_ENDPOINT_API` pour définir l’endpoint API
- `--raw` pour afficher la réponse JSON brute
- `--dry-run` pour afficher la commande et l’environnement utilisés (y compris variables `OSC_*` et `OUTSCALE_*` détectées)

Comportement spécial si `~/.osc/config.json` est absent:
- Le CLI génère automatiquement un fichier de configuration temporaire (dans un HOME temporaire) avec les
  identifiants/res région/endpoint issus du `.env`/des options, afin d’éviter l’erreur "can't open/read ~/.osc/config.json".
- Aucun fichier n’est écrit dans votre HOME réel sauf si vous en avez déjà un; dans ce cas, il est utilisé tel quel.
- Pensez à définir `OSC_ENDPOINT_API` (ou `--api-endpoint`) pour l’URL API si elle n’est pas présente dans votre environnement.

Affichage:
- Par défaut, la table affiche tous les champs présents dans la réponse (ex: `AccessKeyId`, `State`, `CreationDate`, `ExpirationDate`, `LastModificationDate`, `Tag`, etc.).
- Utilisez `--raw` si vous souhaitez voir exactement le JSON renvoyé par l’API sans formatage tabulaire.

Exemples:
- `.env` minimal pour oapi-cli:
  - `OUTSCALE_ACCESSS_KEY=AKIA...`
  - `OUTSCALE_SECRET_KEY=xxxxxxxx`
  - `OUTSCALE_REGION=eu-west-2`
- Vérifier la prise en compte (dry-run): `python -m outscale access-key list --dry-run`

### Créer une AccessKey avec un tag et sauvegarder le résultat
Commande:
- `python -m outscale access-key create --tag "Mon tag"`

Comportement:
- Crée une clé d’accès via l’API et enregistre un enregistrement dans `result.json` SANS écraser le fichier existant.
- Le fichier est géré en mode append:
  - Si le fichier n’existe pas: il est créé au format JSON Lines (un objet par ligne).
  - S’il contient un tableau JSON (commence par `[`): le tableau est chargé, l’objet est ajouté, puis réécrit.
  - Sinon: append en JSON Lines (une ligne par objet) est utilisé.

Format de l’objet enregistré:
```
{ "tag": "Mon tag",
  "access_key_id": "<AccessKeyId>",
  "access_key_scret": "<SecretKey>",
  "creation_date": "<CreationDate>" }
```
Note: la clé `access_key_scret` est volontairement orthographiée ainsi, pour respecter le format demandé.

Options:
- `--result-file` pour choisir un autre chemin que `result.json` (ex: `--result-file out/keys.json`).
- `--raw` pour afficher aussi la réponse brute de l’API lors de la création.

Exemples:
- `python -m outscale access-key create --tag "Nico test"`
- `python -m outscale access-key create --tag "Batch 2025-10" --result-file out/result.json`

### Lister les buckets (boto3)
Commande:
- `python -m outscale bucket list`

Comportement:
- Utilise boto3 avec les identifiants et la région résolus depuis le CLI et/ou `.env` (priorité `OUTSCALE_ACCESSS_KEY`/`OUTSCALE_SECRET_ACCESS_KEY`/`OUTSCALE_REGION`, puis `AWS_*`).
- L’endpoint S3 est lu via l’option globale `--endpoint-url` ou la variable `OUTSCALE_S3_ENDPOINT`.
- Affiche un tableau `Name` / `CreationDate`. Utilisez `--raw` pour voir la réponse brute JSON.

## Notes
- Le CLI utilise `boto3` pour les opérations S3 et `oapi-cli` (externe) pour les AccessKeys.
- En cas d’erreur, utilisez `--debug` pour afficher les détails.
