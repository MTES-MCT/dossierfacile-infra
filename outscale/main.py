"""
CLI Outscale pour déployer des buckets S3-compatibles.

Exemples:
  - Afficher l'aide générale:
      python -m outscale
  - Déployer (idempotent) un bucket:
      python -m outscale bucket deploy --name my-bucket --region eu-west-2 \
          --endpoint-url https://s3.eu-west-2.outscale.com
  - Ajouter des tags:
      python -m outscale bucket deploy --name my-bucket --tag env=dev --tag owner=infra
  - Utiliser un profil AWS/OSC existant:
      python -m outscale --profile myprofile bucket deploy --name my-bucket

Authentification:
  - Variables d'environnement: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
  - Option --profile (fichier de credentials), ou --access-key / --secret-key.
  - Endpoint Outscale (S3 compatible) à préciser via --endpoint-url ou OUTSCALE_S3_ENDPOINT.
"""
from __future__ import annotations

import sys
import textwrap
from typing import Any, Dict, Optional

import os
import json
import shutil
import subprocess
from pathlib import Path

import click
from botocore.exceptions import ClientError

# Helpers dédiés
from .env_utils import (
    load_dotenv_if_present,
    resolve_oapi_credentials,
    build_oapi_env,
    maybe_prepare_oapi_config,
)
from .s3_service import (
    resolve_s3_credentials,
    build_s3_client,
    ensure_bucket,
    apply_default_bucket_cors,
    delete_bucket,
    apply_bucket_policy,
    get_bucket_policy,
    apply_bucket_lifecycle,
    get_bucket_lifecycle,
    apply_bucket_encryption,  # ajout
)
from .oapi_service import (
    run_oapi_cli,
    append_result_json,
)

# Chargement automatique du fichier .env si présent
load_dotenv_if_present()


@click.group(invoke_without_command=True)
@click.option("--endpoint-url", envvar="OUTSCALE_S3_ENDPOINT", default=None, help="Endpoint S3 Outscale.")
@click.option("--region", envvar="AWS_REGION", default=None, help="Région (ex: eu-west-2).")
@click.option("--profile", default=None, help="Profil AWS/OSC à utiliser.")
@click.option("--access-key", envvar="AWS_ACCESS_KEY_ID", default=None, help="Access key.")
@click.option("--secret-key", envvar="AWS_SECRET_ACCESS_KEY", default=None, help="Secret key.")
@click.option("--debug/--no-debug", default=False, help="Active l'affichage d'erreurs détaillées.")
@click.pass_context
def cli(ctx: click.Context, endpoint_url, region, profile, access_key, secret_key, debug):
    """Outil CLI pour gérer des ressources Outscale.

    Lancez sans arguments pour afficher cette aide.
    """
    ctx.ensure_object(dict)
    ctx.obj.update(
        {
            "endpoint_url": endpoint_url,
            "region": region,
            "profile": profile,
            "access_key": access_key,
            "secret_key": secret_key,
            "debug": debug,
        }
    )

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        # Fournit aussi quelques astuces
        extra = textwrap.dedent(
            """
            Astuces:
              - Définissez OUTSCALE_S3_ENDPOINT (S3), OSC_ENDPOINT_API (API), AWS_ACCESS_KEY_ID/SECRET
                pour éviter de passer les options à chaque fois.
              - Le déploiement de bucket est idempotent: relancer la commande ne casse rien.
            """
        ).strip()
        click.echo("")
        click.echo(extra)


# -------- Buckets (S3) --------
@cli.group()  # type: ignore[attr-defined]
def bucket():
    """Commandes relatives aux buckets S3-compatibles."""
    pass


@bucket.command("cors")
@click.option("--name", required=True, help="Nom du bucket à mettre a jour.")
@click.pass_context
def bucket_cors(ctx: click.Context, name: str):
    try:
        # Résoud les identifiants S3 (CLI puis OUTSCALE_*)
        ak, sk, rg = resolve_s3_credentials(
            ctx.obj.get("access_key"), ctx.obj.get("secret_key"), ctx.obj.get("region")
        )
        s3_client, resolved_region = build_s3_client(
            ctx.obj.get("endpoint_url"), ak, sk, rg, debug=ctx.obj.get("debug")
        )
        apply_default_bucket_cors(s3_client, bucket_name=name, region=resolved_region)
        click.secho("✔ Cors appliqué", fg="green")
    except ClientError as e:
        if ctx.obj.get("debug"):
            raise
        err = e.response.get("Error", {})
        code = err.get("Code")
        msg = err.get("Message") or str(e)
        raise click.ClickException(f"Erreur S3 ({code}): {msg}") from e
    except Exception as e:  # erreurs inattendues
        if ctx.obj.get("debug"):
            raise
        raise click.ClickException(str(e)) from e


@bucket.command("deploy")
@click.option("--name", required=True, help="Nom du bucket à déployer.")
@click.option(
    "--tag",
    multiple=True,
    help="Tag au format key=value. Option répétable.",
)
@click.pass_context
def bucket_deploy(ctx: click.Context, name: str, tag: tuple[str, ...]):
    """Déploie (crée si absent) un bucket sur Outscale et applique les tags."""
    tags: Dict[str, str] = {}
    for t in tag:
        if "=" not in t:
            raise click.ClickException(f"Tag invalide: '{t}'. Utilisez key=value.")
        k, v = t.split("=", 1)
        tags[k] = v

    try:
        ak, sk, rg = resolve_s3_credentials(
            ctx.obj.get("access_key"), ctx.obj.get("secret_key"), ctx.obj.get("region")
        )
        s3_client, resolved_region = build_s3_client(
            ctx.obj.get("endpoint_url"), ak, sk, rg, debug=ctx.obj.get("debug")
        )
        ensure_bucket(s3_client, bucket_name=name, region=resolved_region, tags=tags or None)
        click.secho("✔ Déploiement terminé", fg="green")
    except ClientError as e:
        if ctx.obj.get("debug"):
            raise
        err = e.response.get("Error", {})
        code = err.get("Code")
        msg = err.get("Message") or str(e)
        raise click.ClickException(f"Erreur S3 ({code}): {msg}") from e
    except Exception as e:  # erreurs inattendues
        if ctx.obj.get("debug"):
            raise
        raise click.ClickException(str(e)) from e


@bucket.command("delete")
@click.option("--name", required=True, help="Nom du bucket à supprimer.")
@click.option("--force", required=False, is_flag=True, help="Force la suppression en vidant le bucket avant.")
@click.pass_context
def bucket_delete(ctx: click.Context, name: str, force: bool):
    """Vide le bucket puis le supprime."""
    try:
        ak, sk, rg = resolve_s3_credentials(
            ctx.obj.get("access_key"), ctx.obj.get("secret_key"), ctx.obj.get("region")
        )
        s3_client, _ = build_s3_client(ctx.obj.get("endpoint_url"), ak, sk, rg, debug=ctx.obj.get("debug"))
        delete_bucket(s3_client, bucket_name=name, force_delete=force)
        click.secho("✔ Suppression terminée", fg="green")
    except ClientError as e:
        if ctx.obj.get("debug"):
            raise
        err = e.response.get("Error", {})
        code = err.get("Code")
        msg = err.get("Message") or str(e)
        raise click.ClickException(f"Erreur S3 ({code}): {msg}") from e
    except Exception as e:
        if ctx.obj.get("debug"):
            raise
        raise click.ClickException(str(e)) from e


@bucket.command("list")
@click.option("--raw/--no-raw", default=False, help="Affiche la réponse JSON brute.")
@click.pass_context
def bucket_list(ctx: click.Context, raw: bool):
    """Liste les buckets S3 existants sur Outscale (via boto3)."""
    try:
        ak, sk, rg = resolve_s3_credentials(
            ctx.obj.get("access_key"), ctx.obj.get("secret_key"), ctx.obj.get("region")
        )
        s3_client, _ = build_s3_client(ctx.obj.get("endpoint_url"), ak, sk, rg, debug=ctx.obj.get("debug"))
        resp = s3_client.list_buckets()
        if raw:
            click.echo(json.dumps(resp, ensure_ascii=False, indent=2))
            return
        buckets = resp.get("Buckets", [])
        if not buckets:
            click.echo("Aucun bucket trouvé.")
            return
        header = f"{'Name':<40} {'CreationDate':<30}"
        click.echo(header)
        click.echo("-" * len(header))
        for b in buckets:
            name = str(b.get("Name", ""))
            created = str(b.get("CreationDate", ""))
            click.echo(f"{name:<40} {created:<30}")
    except TypeError as e:
        endpoint = ctx.obj.get("endpoint_url") or os.environ.get("OUTSCALE_S3_ENDPOINT") or "(inconnu)"
        raise click.ClickException(
            "Erreur lors de list_buckets(). Votre endpoint S3 semble incorrect.\n"
            f"Endpoint actuel: {endpoint}\n"
            "Assurez-vous d'utiliser un endpoint OSU/S3 (ex: https://s3.cloudgouv-eu-west-1.outscale.com ou https://osu.cloudgouv-eu-west-1.outscale.com)."
        ) from e
    except ClientError as e:
        if ctx.obj.get("debug"):
            raise
        err = e.response.get("Error", {})
        code = err.get("Code")
        msg = err.get("Message") or str(e)
        raise click.ClickException(f"Erreur S3 ({code}): {msg}") from e
    except Exception as e:
        if ctx.obj.get("debug"):
            raise
        raise click.ClickException(str(e)) from e


@bucket.command("add-policy")
@click.option("--name", required=True, help="Nom du bucket cible.")
@click.option(
    "--file",
    "file_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=str),
    help="Chemin (relatif ou absolu) vers le fichier JSON de policy.",
)
@click.pass_context
def bucket_add_policy(ctx: click.Context, name: str, file_path: str):
    """Applique une bucket policy depuis un fichier JSON."""
    try:
        ak, sk, rg = resolve_s3_credentials(
            ctx.obj.get("access_key"), ctx.obj.get("secret_key"), ctx.obj.get("region")
        )
        s3_client, _ = build_s3_client(ctx.obj.get("endpoint_url"), ak, sk, rg, debug=ctx.obj.get("debug"))

        policy_text = Path(file_path).read_text(encoding="utf-8")
        apply_bucket_policy(s3_client, bucket_name=name, policy=policy_text)
        click.secho("✔ Policy appliquée", fg="green")
    except ClientError as e:
        if ctx.obj.get("debug"):
            raise
        err = e.response.get("Error", {})
        code = err.get("Code")
        msg = err.get("Message") or str(e)
        raise click.ClickException(f"Erreur S3 ({code}): {msg}") from e
    except FileNotFoundError:
        raise click.ClickException(f"Fichier introuvable: {file_path}")
    except Exception as e:
        if ctx.obj.get("debug"):
            raise
        raise click.ClickException(str(e)) from e


@bucket.command("read-policy")
@click.option("--name", required=True, help="Nom du bucket cible.")
@click.option("--raw/--no-raw", default=False, help="Affiche le JSON brut renvoyé par l'API.")
@click.pass_context
def bucket_read_policy(ctx: click.Context, name: str, raw: bool):
    """Affiche la bucket policy si elle existe."""
    try:
        ak, sk, rg = resolve_s3_credentials(
            ctx.obj.get("access_key"), ctx.obj.get("secret_key"), ctx.obj.get("region")
        )
        s3_client, _ = build_s3_client(ctx.obj.get("endpoint_url"), ak, sk, rg, debug=ctx.obj.get("debug"))

        policy_str = get_bucket_policy(s3_client, bucket_name=name)
        if not policy_str:
            click.echo("Aucune policy définie sur ce bucket.")
            return
        if raw:
            click.echo(policy_str)
            return
        # Affichage formaté si possible
        try:
            data = json.loads(policy_str)
            click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception:
            click.echo(policy_str)
    except ClientError as e:
        if ctx.obj.get("debug"):
            raise
        err = e.response.get("Error", {})
        code = err.get("Code")
        msg = err.get("Message") or str(e)
        raise click.ClickException(f"Erreur S3 ({code}): {msg}") from e
    except Exception as e:
        if ctx.obj.get("debug"):
            raise
        raise click.ClickException(str(e)) from e


@bucket.command("add-lifecycle")
@click.option("--name", required=True, help="Nom du bucket cible.")
@click.option(
    "--policy",
    "policy_json",
    required=True,
    help="JSON inline de la lifecycle (string). Exemple: '{\"Rules\":[{\"ID\":\"expire\",\"Status\":\"Enabled\",\"Filter\":{\"Prefix\":\"raw/\"},\"Expiration\":{\"Days\":30}}]}'",
)
@click.option(
    "--no-validate",
    is_flag=True,
    help="N'effectue pas de validation locale: envoie le JSON tel quel à S3.",
)
@click.pass_context
def bucket_add_lifecycle(ctx: click.Context, name: str, policy_json: str, no_validate: bool):
    """Applique une Lifecycle Configuration via un JSON inline."""
    try:
        ak, sk, rg = resolve_s3_credentials(
            ctx.obj.get("access_key"), ctx.obj.get("secret_key"), ctx.obj.get("region")
        )
        s3_client, _ = build_s3_client(ctx.obj.get("endpoint_url"), ak, sk, rg, debug=ctx.obj.get("debug"))
        apply_bucket_lifecycle(s3_client, bucket_name=name, lifecycle=policy_json, validate=not no_validate)
        click.secho("✔ Lifecycle appliquée", fg="green")
    except ClientError as e:
        if ctx.obj.get("debug"):
            raise
        err = e.response.get("Error", {})
        code = err.get("Code")
        msg = err.get("Message") or str(e)
        raise click.ClickException(f"Erreur S3 ({code}): {msg}") from e
    except Exception as e:
        if ctx.obj.get("debug"):
            raise
        raise click.ClickException(str(e)) from e


@bucket.command("read-lifecycle")
@click.option("--name", required=True, help="Nom du bucket cible.")
@click.option("--raw/--no-raw", default=False, help="Affiche le JSON brut renvoyé par l'API.")
@click.pass_context
def bucket_read_lifecycle(ctx: click.Context, name: str, raw: bool):
    """Affiche la configuration Lifecycle du bucket si elle existe."""
    try:
        ak, sk, rg = resolve_s3_credentials(
            ctx.obj.get("access_key"), ctx.obj.get("secret_key"), ctx.obj.get("region")
        )
        s3_client, _ = build_s3_client(ctx.obj.get("endpoint_url"), ak, sk, rg, debug=ctx.obj.get("debug"))
        cfg = get_bucket_lifecycle(s3_client, bucket_name=name)
        if not cfg:
            click.echo("Aucune lifecycle définie sur ce bucket.")
            return
        if raw:
            click.echo(json.dumps(cfg))
            return
        click.echo(json.dumps(cfg, ensure_ascii=False, indent=2))
    except ClientError as e:
        if ctx.obj.get("debug"):
            raise
        err = e.response.get("Error", {})
        code = err.get("Code")
        msg = err.get("Message") or str(e)
        raise click.ClickException(f"Erreur S3 ({code}): {msg}") from e
    except Exception as e:
        if ctx.obj.get("debug"):
            raise
        raise click.ClickException(str(e)) from e


@bucket.command("add-encryption")
@click.option("--name", required=True, help="Nom du bucket cible.")
@click.option(
    "--config",
    "encryption_json",
    required=True,
    help=(
        "JSON inline de la configuration d'encryptage (string). "
        "Exemple: '{\"Rules\":[{\"ApplyServerSideEncryptionByDefault\":{\"SSEAlgorithm\":\"AES256\"}}]}'"
    ),
)
@click.option(
    "--no-validate",
    is_flag=True,
    help="N'effectue pas de validation locale: envoie le JSON tel quel à S3.",
)
@click.pass_context
def bucket_add_encryption(ctx: click.Context, name: str, encryption_json: str, no_validate: bool):
    """Applique une configuration d'encryptage (SSE) via un JSON inline."""
    try:
        ak, sk, rg = resolve_s3_credentials(
            ctx.obj.get("access_key"), ctx.obj.get("secret_key"), ctx.obj.get("region")
        )
        s3_client, _ = build_s3_client(
            ctx.obj.get("endpoint_url"), ak, sk, rg, debug=ctx.obj.get("debug")
        )
        apply_bucket_encryption(
            s3_client,
            bucket_name=name,
            encryption=encryption_json,
            validate=not no_validate,
        )
        click.secho("✔ Encryption appliquée", fg="green")
    except ClientError as e:
        if ctx.obj.get("debug"):
            raise
        err = e.response.get("Error", {})
        code = err.get("Code")
        msg = err.get("Message") or str(e)
        raise click.ClickException(f"Erreur S3 ({code}): {msg}") from e
    except Exception as e:
        if ctx.obj.get("debug"):
            raise
        raise click.ClickException(str(e)) from e


# -------- Access Keys (oapi-cli) --------
@cli.group(name="access-key")  # type: ignore[attr-defined]
def access_key():
    """Commandes liées aux AccessKeys via oapi-cli."""
    pass


@access_key.command("list")
@click.option(
    "--oapi-bin",
    default=lambda: shutil.which("oapi-cli") or "oapi-cli",
    show_default=True,
    help="Chemin du binaire oapi-cli.",
)
@click.option("--raw/--no-raw", default=False, help="Affiche la réponse JSON brute.")
@click.option("--dry-run/--no-dry-run", default=False, help="N'exécute pas, affiche seulement la commande et l'env.")
@click.pass_context
def access_key_list(ctx: click.Context, oapi_bin: str, raw: bool, dry_run: bool):
    """Liste les AccessKeys existantes via oapi-cli (commande ReadAccessKeys)."""
    # Résout d'abord les credentials/region en incluant OUTSCALE_* depuis .env
    resolved_ak, resolved_sk, resolved_rg = resolve_oapi_credentials(
        ctx.obj.get("access_key"), ctx.obj.get("secret_key"), ctx.obj.get("region")
    )

    env = build_oapi_env(
        dict(os.environ), access_key=resolved_ak, secret_key=resolved_sk, region=resolved_rg
    )

    # Prépare un config.json temporaire si nécessaire pour éviter l'erreur de lecture ~/.osc/config.json
    env = maybe_prepare_oapi_config(env, resolved_ak, resolved_sk, resolved_rg)

    cmd = [oapi_bin, "ReadAccessKeys"]

    if dry_run:
        click.echo("Commande:")
        click.echo(" ".join(cmd))
        display_env = {k: v for k, v in env.items() if k.startswith("OSC_")}
        for k in ("OUTSCALE_ACCESSS_KEY", "OUTSCALE_ACCESS_KEY", "OUTSCALE_SECRET_KEY", "OUTSCALE_REGION"):
            if os.environ.get(k):
                display_env[k] = os.environ.get(k, "")
        if env.get("HOME") and "osc-home-" in env["HOME"]:
            display_env["HOME"] = env["HOME"]
        click.echo("Env (OSC_* et OUTSCALE_* détectées):")
        for k, v in display_env.items():
            click.echo(f"  {k}={v}")
        return

    code, out, err = run_oapi_cli(oapi_bin, ["ReadAccessKeys"], env)
    if code != 0:
        raise click.ClickException(f"oapi-cli a échoué (code {code}): {err.strip() or out.strip()}")

    if raw:
        click.echo(out)
        return

    # Tentative de parsing et rendu compact
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        click.echo(out)
        return

    keys = None
    for candidate in ("AccessKeys", "accessKeys", "AccessKey", "accessKey"):
        if isinstance(payload, dict) and candidate in payload and isinstance(payload[candidate], list):
            keys = payload[candidate]
            break
    if keys is None and isinstance(payload, list):
        keys = payload

    if not keys:
        click.echo("Aucune AccessKey trouvée.")
        return

    preferred = [
        "AccessKeyId",
        "State",
        "CreationDate",
        "ExpirationDate",
        "LastModificationDate",
        "Tag",
    ]
    cols: list[str] = []
    seen = set()
    for col in preferred:
        if any(isinstance(it, dict) and col in it for it in keys):
            cols.append(col)
            seen.add(col)
    for it in keys:
        if isinstance(it, dict):
            for k in it.keys():
                if k not in seen:
                    cols.append(k)
                    seen.add(k)

    widths: Dict[str, int] = {}
    for col in cols:
        w = len(col)
        for it in keys:
            if isinstance(it, dict):
                w = max(w, len(str(it.get(col, ""))))
        widths[col] = w

    header = " ".join(f"{col:<{widths[col]}}" for col in cols)
    click.echo(header)
    click.echo("-" * len(header))
    for it in keys:
        if not isinstance(it, dict):
            continue
        line = " ".join(f"{str(it.get(col, '')):<{widths[col]}}" for col in cols)
        click.echo(line)


@access_key.command("create")
@click.option("--tag", required=True, help="Tag à associer à la clé d'accès.")
@click.option(
    "--result-file",
    default="result.json",
    show_default=True,
    help="Chemin du fichier où enregistrer le résultat (append).",
)
@click.option("--oapi-bin", default=lambda: shutil.which("oapi-cli") or "oapi-cli", show_default=True, help="Chemin du binaire oapi-cli.")
@click.option("--raw/--no-raw", default=False, help="Affiche la réponse JSON brute de l'API.")
@click.pass_context
def access_key_create(ctx: click.Context, tag: str, result_file: str, oapi_bin: str, raw: bool):
    """Crée une AccessKey avec un tag et ajoute le résultat dans result.json (append)."""
    # Résout credentials/region et prépare env/config pour oapi-cli
    resolved_ak, resolved_sk, resolved_rg = resolve_oapi_credentials(
        ctx.obj.get("access_key"), ctx.obj.get("secret_key"), ctx.obj.get("region")
    )
    env = build_oapi_env(
        dict(os.environ), access_key=resolved_ak, secret_key=resolved_sk, region=resolved_rg
    )
    env = maybe_prepare_oapi_config(env, resolved_ak, resolved_sk, resolved_rg)

    # 1ère tentative: passer le tag en argument
    cmd_args = ["CreateAccessKey", "--Tag", tag]
    code, out, err = run_oapi_cli(oapi_bin, cmd_args, env)

    # Si échec, 2e tentative: fournir un body JSON sur stdin
    if code != 0:
        body = json.dumps({"Tag": tag})
        try:
            proc = subprocess.run(
                [oapi_bin, "CreateAccessKey"],
                env=env,
                check=False,
                capture_output=True,
                text=True,
                input=body,
            )
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except FileNotFoundError as e:
            raise click.ClickException(
                "Binaire 'oapi-cli' introuvable. Installez-le avec: npm i -g @outscale/oapi-cli"
            ) from e

    if code != 0:
        raise click.ClickException(f"oapi-cli a échoué (code {code}): {err.strip() or out.strip()}")

    if raw:
        click.echo(out)

    # Extrait les champs intéressants du payload
    try:
        payload = json.loads(out)
    except json.JSONDecodeError as e:
        raise click.ClickException(f"Réponse non JSON de oapi-cli: {out[:200]}") from e

    def _find_access_key_node(obj: Any) -> Optional[Dict[str, Any]]:
        if isinstance(obj, dict):
            keys = set(obj.keys())
            if "AccessKeyId" in keys or "SecretKey" in keys or "accessKeyId" in keys or "secretKey" in keys:
                return obj
            for v in obj.values():
                found = _find_access_key_node(v)
                if found:
                    return found
        elif isinstance(obj, list):
            for it in obj:
                found = _find_access_key_node(it)
                if found:
                    return found
        return None

    node = _find_access_key_node(payload) or {}
    access_key_id = node.get("AccessKeyId") or node.get("accessKeyId") or ""
    secret = node.get("SecretKey") or node.get("secretKey") or ""
    creation_date = node.get("CreationDate") or node.get("creationDate") or ""

    record = {
        "tag": tag,
        "access_key_id": access_key_id,
        "access_key_scret": secret,
        "creation_date": creation_date,
    }

    append_result_json(result_file, record)
    click.secho(f"✔ AccessKey créée et ajoutée à {result_file}", fg="green")


def main(argv: Optional[list[str]] = None) -> int:
    try:
        cli.main(args=argv, prog_name="outscale", standalone_mode=False)  # type: ignore[attr-defined]
        return 0
    except SystemExit as e:
        return int(e.code) if e.code is not None else 0


if __name__ == "__main__":  # exécution directe
    sys.exit(main())
