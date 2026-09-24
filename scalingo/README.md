# Scalingo

Scripts Python pour gérer les collaborateurs et les notifiers Slack des applications Scalingo sur les régions `osc-secnum-fr1` et `osc-fr1`.

## Prérequis

Depuis ce répertoire :

```bash
poetry install
cp .env.example .env
```

| Variable | Usage |
| --- | --- |
| `SCALINGO_API_TOKEN` | Obligatoire. Token d’API Scalingo. |
| `SCALINGO_DOSSIER_FACILE_USERS` | Emails autorisés, séparés par des espaces. Utilisé par l’audit. |
| `SCALINGO_SCM_LINK_ID` | `linker.id` de l’utilisateur Scalingo qui porte le lien SCM (`us-…`). |
| `SLACK_WEBHOOK_URL` | Webhook Slack / Tchap pour les notifiers. |

## Utilisateurs — `manage_users.py`

Éditer les appels dans `main()`, puis lancer :

```bash
poetry run python manage_users.py
```

| Méthode | Effet |
| --- | --- |
| `audit_users(project_name, apply=False)` | Compare les collaborateurs de chaque app du projet à `SCALINGO_DOSSIER_FACILE_USERS`. Logue les absents et les non autorisés. Avec `apply=True`, invite les absents et retire les non autorisés. |
| `add_user(project_name, email)` | Invite `email` sur toutes les apps du projet. |
| `remove_user(project_name, user_id)` | Retire le collaborateur `user_id` de toutes les apps du projet. |
| `update_scm_links(project_name, linker_id)` | Reporte le lien SCM de chaque app du projet sur `linker_id` (`SCALINGO_SCM_LINK_ID`). |

Le lien SCM rattache une application à son dépôt GitHub ou GitLab. L’auto-deploy et les review apps s’authentifient avec le compte SCM de l’utilisateur qui a créé ce lien, le linker.

`SCALINGO_SCM_LINK_ID` est son identifiant Scalingo, `linker.id` (préfixe `us-`). Pour le lire sur une application déjà liée par la personne qui doit rester propriétaire :

```bash
scalingo --app <app> --region osc-secnum-fr1 integration-link
```

La valeur est `linker.id`. Le même identifiant est `user.id` renvoyé par `GET /v1/users/self`, authentifié avec le compte de cette personne.

Scalingo refuse de retirer un collaborateur tant qu’il est le linker d’une application. L’API répond `400` avec `collaborator can't be removed because linker of SCM integration`. Avant l’audit ou `remove_user`, `update_scm_links` reporte le lien sur un utilisateur encore présent, dont l’intégration GitHub ou GitLab est active.

## Notifiers — `manage_apps.py`

Crée le notifier Slack `mattermost-default-notifier` sur toutes les applications de chaque région, avec `SLACK_WEBHOOK_URL` et une liste d’événements fixe (distincte selon la région). Une app qui a déjà ce notifier est ignorée.

Limitation : cette liste est une liste technique d’identifiants d’événements, aujourd’hui codée en dur dans `manage_apps.py`. Elle est à maintenir lorsque Scalingo ajoute ou modifie des événements.

```bash
poetry run python manage_apps.py
```
