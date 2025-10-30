"""
Service S3 (Outscale S3-compatible) : helpers pour créer le client, gérer les buckets,
valider l'endpoint et appliquer des règles CORS.
"""
from __future__ import annotations

import base64
import hashlib
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional, Tuple, List
from urllib.parse import urlparse

import boto3
import click
import requests
from botocore.auth import S3SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config as BotoConfig
from botocore.credentials import Credentials
from botocore.exceptions import ClientError


def validate_s3_endpoint(endpoint: str) -> None:
    """Valide sommairement l'endpoint S3 (URL valide et non FCU/API)."""
    try:
        p = urlparse(endpoint)
    except Exception:
        raise click.ClickException(
            f"Endpoint S3 invalide: '{endpoint}'. Attendu: URL complète ex: https://s3.cloudgouv-eu-west-1.outscale.com"
        )
    if not p.scheme or not p.netloc:
        raise click.ClickException(
            f"Endpoint S3 invalide: '{endpoint}'. Attendu: URL complète ex: https://s3.cloudgouv-eu-west-1.outscale.com"
        )
    host = p.hostname or ""
    if host.startswith("fcu.") or host.startswith("api."):
        hint = (
            "L'endpoint fourni pointe vers FCU/API et non vers OSU/S3. "
            "Utilisez un endpoint OSU/S3, par ex. pour cloudgouv-eu-west-1:\n"
            "  - https://s3.cloudgouv-eu-west-1.outscale.com\n"
            "  - https://osu.cloudgouv-eu-west-1.outscale.com"
        )
        raise click.ClickException(hint)


def build_session(
        profile: Optional[str], access_key: Optional[str], secret_key: Optional[str], region: Optional[str]
) -> "boto3.session.Session":
    if profile:
        return boto3.session.Session(profile_name=profile, region_name=region)
    if access_key and secret_key:
        return boto3.session.Session(
            aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=region
        )
    return boto3.session.Session(region_name=region)


def resolve_s3_credentials(
        cli_access_key: Optional[str], cli_secret_key: Optional[str], cli_region: Optional[str]
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Priorité: CLI puis OUTSCALE_* uniquement (évite ~/.aws)."""
    ak = cli_access_key or os.environ.get("OUTSCALE_ACCESSS_KEY") or os.environ.get("OUTSCALE_ACCESS_KEY")
    sk = cli_secret_key or os.environ.get("OUTSCALE_SECRET_KEY")
    rg = cli_region or os.environ.get("OUTSCALE_REGION")
    return ak, sk, rg


def build_s3_client(
        endpoint_url: Optional[str], access_key: Optional[str], secret_key: Optional[str], region: Optional[str], *,
        debug: bool = False
) -> Tuple[Any, Optional[str]]:
    """Construit un client S3 boto3 configuré pour Outscale.
    - Endpoint obligatoire via argument ou OUTSCALE_S3_ENDPOINT
    - Signature s3v4 et addressing path
    """
    endpoint = endpoint_url or os.environ.get("OUTSCALE_S3_ENDPOINT")
    if not endpoint:
        raise click.ClickException(
            "Aucun endpoint S3 Outscale détecté. Définissez --endpoint-url ou OUTSCALE_S3_ENDPOINT."
        )
    validate_s3_endpoint(endpoint)

    if debug:
        source = "CLI" if endpoint_url else "ENV"
        click.secho(f"Endpoint S3 résolu depuis {source}: {endpoint}", fg="blue")

    if not access_key or not secret_key:
        raise click.ClickException(
            "Identifiants Outscale manquants. Définissez --access-key/--secret-key ou OUTSCALE_ACCESSS_KEY/OUTSCALE_SECRET_KEY."
        )

    session = build_session(profile=None, access_key=access_key, secret_key=secret_key, region=region)
    config = BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"})
    s3_client = session.client("s3", endpoint_url=endpoint, config=config)
    return s3_client, region


def ensure_bucket(
        s3_client, bucket_name: str, region: Optional[str] = None, tags: Optional[Dict[str, str]] = None
) -> None:
    """Idempotent: crée le bucket s'il n'existe pas; ne fait rien s'il existe déjà."""
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        click.secho(f"Bucket déjà présent: {bucket_name}", fg="yellow")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in {"404", "NoSuchBucket", "NotFound"}:
            params: Dict[str, Any] = {"Bucket": bucket_name}
            if region and region != "us-east-1":
                params["CreateBucketConfiguration"] = {"LocationConstraint": region}
            click.secho(f"Création du bucket: {bucket_name}", fg="green")
            s3_client.create_bucket(**params)
        elif code in {"301", "PermanentRedirect"}:
            raise click.ClickException(
                f"Le bucket {bucket_name} existe dans une autre région. Vérifiez --region."
            ) from e
        else:
            raise

    if tags:
        tag_set = [{"Key": k, "Value": v} for k, v in tags.items()]
        s3_client.put_bucket_tagging(Bucket=bucket_name, Tagging={"TagSet": tag_set})
        click.secho(f"Tags appliqués sur {bucket_name}: {tags}", fg="blue")


def apply_default_bucket_cors(s3_client, bucket_name: str, region: Optional[str] = None) -> None:
    """Applique une configuration CORS via requête HTTP signée (SigV4)."""
    endpoint = getattr(getattr(s3_client, "meta", None), "endpoint_url", None)
    if not endpoint:
        raise click.ClickException("Impossible de déterminer l'endpoint du client S3.")
    endpoint = str(endpoint).rstrip("/")

    sign_region = (
            region
            or getattr(getattr(s3_client, "meta", None), "region_name", None)
            or os.environ.get("OUTSCALE_REGION")
            or os.environ.get("OSC_REGION")
            or os.environ.get("AWS_REGION")
            or "us-east-1"
    )

    ns = "http://s3.amazonaws.com/doc/2006-03-01/"
    root = ET.Element("CORSConfiguration", xmlns=ns)
    rule = ET.SubElement(root, "CORSRule")
    for origin in [
        "http://localhost:8081",
        "http://0.0.0.0:8081",
        "https://labeling.document-ia.beta.gouv.fr",
    ]:
        ET.SubElement(rule, "AllowedOrigin").text = origin
    for method in ["GET", "PUT", "POST", "DELETE", "HEAD"]:
        ET.SubElement(rule, "AllowedMethod").text = method
    ET.SubElement(rule, "AllowedHeader").text = "*"
    ET.SubElement(rule, "MaxAgeSeconds").text = "3000"
    xml_body = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    creds_obj = getattr(getattr(s3_client, "_request_signer", None), "_credentials", None)
    if not creds_obj or not getattr(creds_obj, "access_key", None) or not getattr(creds_obj, "secret_key", None):
        raise click.ClickException(
            "Identifiants introuvables depuis le client S3. Fournissez --access-key/--secret-key ou variables OUTSCALE_*."
        )
    access_key = creds_obj.access_key
    secret_key = creds_obj.secret_key
    token = getattr(creds_obj, "token", None)

    url = f"{endpoint}/{bucket_name}?cors"
    content_md5_b64 = base64.b64encode(hashlib.md5(xml_body).digest()).decode("ascii")
    payload_sha256_hex = hashlib.sha256(xml_body).hexdigest()
    headers = {
        "Content-Type": "application/xml",
        "Content-MD5": content_md5_b64,
        "x-amz-content-sha256": payload_sha256_hex,
    }
    if token:
        headers["X-Amz-Security-Token"] = token

    aws_req = AWSRequest(method="PUT", url=url, data=xml_body, headers=headers)
    S3SigV4Auth(Credentials(access_key, secret_key, token), "s3", sign_region).add_auth(aws_req)

    resp = requests.put(url, headers=dict(aws_req.headers.items()), data=xml_body)
    if resp.status_code >= 400:
        raise click.ClickException(
            f"Erreur lors de la mise à jour du CORS (HTTP {resp.status_code}): {resp.text[:500]}"
        )
    click.secho(f"CORS par défaut appliqué sur {bucket_name}", fg="green")


def _chunk(seq: List[Dict[str, str]], size: int = 1000):
    for i in range(0, len(seq), size):
        yield seq[i: i + size]


def empty_bucket(s3_client, bucket_name: str) -> int:
    """Supprime tous les objets et versions d'un bucket.
    Retourne le nombre d'éléments demandés en suppression (approx.).
    """
    deleted_count = 0

    # 1) Supprime toutes les versions et delete-markers (si versioning actif)
    try:
        paginator = s3_client.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bucket_name):
            objs: List[Dict[str, str]] = []
            for v in page.get("Versions", []) or []:
                key = v.get("Key")
                vid = v.get("VersionId")
                if key and vid:
                    objs.append({"Key": key, "VersionId": vid})
            for m in page.get("DeleteMarkers", []) or []:
                key = m.get("Key")
                vid = m.get("VersionId")
                if key and vid:
                    objs.append({"Key": key, "VersionId": vid})
            for batch in _chunk(objs, 1000):
                if not batch:
                    continue
                s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": batch, "Quiet": True})
                deleted_count += len(batch)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code not in {"NoSuchBucket", "404"}:
            raise
        # si NoSuchBucket: rien à vider
        return 0

    # 2) Sécurité: supprime tous les objets courants (si pas de versioning)
    paginator2 = s3_client.get_paginator("list_objects_v2")
    for page in paginator2.paginate(Bucket=bucket_name):
        objs2 = page.get("Contents", []) or []
        to_delete = [{"Key": it.get("Key")} for it in objs2 if it.get("Key")]
        for batch in _chunk(to_delete, 1000):
            if not batch:
                continue
            s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": batch, "Quiet": True})
            deleted_count += len(batch)

    return deleted_count


def apply_bucket_policy(s3_client, bucket_name: str, policy: Dict[str, Any] | str, *, validate: bool = True) -> None:
    """Applique une bucket policy (écrase l'existante si présente).
    - Si validate=True (par défaut): parse le JSON pour émettre des messages d'aide et alertes utiles.
    - Si validate=False: envoie la policy telle quelle (pas de parse côté Python).
    """
    import json as _json

    policy_str: str
    obj: Optional[Dict[str, Any]] = None

    if isinstance(policy, dict):
        policy_str = _json.dumps(policy)
        if validate:
            obj = policy  # déjà un dict
    else:
        policy_str = policy
        if validate:
            try:
                parsed = _json.loads(policy_str)
                if isinstance(parsed, dict):
                    obj = parsed
                else:
                    # S3 acceptera peut-être, mais c'est atypique
                    obj = None
            except Exception as e:
                raise click.ClickException("La policy fournie n'est pas un JSON valide (parse).") from e

    # Validations et alertes uniquement si on a un objet JSON
    if validate and obj is not None:
        if not isinstance(obj, dict) or "Statement" not in obj:
            raise click.ClickException("Policy invalide: champ 'Statement' manquant.")
        stmts = obj.get("Statement")
        if not isinstance(stmts, list):
            stmts = [stmts]

        def _iter_aws_principals(principal_val):
            if principal_val is None:
                return
            if isinstance(principal_val, str):
                yield principal_val
            elif isinstance(principal_val, list):
                for it in principal_val:
                    if isinstance(it, str):
                        yield it
            elif isinstance(principal_val, dict):
                for v in principal_val.values():
                    if isinstance(v, str):
                        yield v
                    elif isinstance(v, list):
                        for it in v:
                            if isinstance(it, str):
                                yield it

        for st in stmts:
            if not isinstance(st, dict):
                continue
            principal = st.get("Principal")
            for p in _iter_aws_principals(principal):
                if p == "*":
                    continue
                if not (isinstance(p, str) and p.startswith("arn:")):
                    raise click.ClickException(
                        f"Principal AWS invalide dans la policy: '{p}'. Attendu un ARN ou '*', ex: arn:aws:iam::123456789012:root"
                    )

        def _extract_bucket_from_arn(arn: str) -> Optional[str]:
            if not isinstance(arn, str) or not arn.startswith("arn:aws:s3:::"):
                return None
            rest = arn[len("arn:aws:s3:::"):]
            return rest.split("/", 1)[0]

        resources: List[str] = []
        for st in stmts:
            if isinstance(st, dict) and "Resource" in st:
                r = st["Resource"]
                if isinstance(r, str):
                    resources.append(r)
                elif isinstance(r, list):
                    resources.extend([x for x in r if isinstance(x, str)])
        wrong = [
            r for r in resources if (_extract_bucket_from_arn(r) or bucket_name) and _extract_bucket_from_arn(r) not in {None, bucket_name}
        ]
        if wrong:
            click.secho(
                "Attention: certaines Resource ne pointent pas sur le bucket cible: " + ", ".join(wrong), fg="yellow"
            )

    try:
        s3_client.put_bucket_policy(Bucket=bucket_name, Policy=policy_str)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in {"NoSuchBucket", "404"}:
            raise click.ClickException(f"Bucket introuvable: {bucket_name}") from e
        if code in {"MalformedPolicy"}:
            raise click.ClickException(
                "La policy est rejetée par S3 (MalformedPolicy). Vérifiez la structure JSON et surtout 'Principal' (ARN ou '*')."
            ) from e
        raise
    click.secho(f"Policy appliquée sur {bucket_name}", fg="green")


def delete_bucket(s3_client, bucket_name: str, force_delete: bool = False) -> None:
    """Supprime un bucket, en le vidant si --force est demandé.
    - Sans --force: tente une suppression directe; si BucketNotEmpty, suggère --force.
    - Avec --force: vide objets et versions puis supprime.
    """
    # Vérifie l'existence rapidement
    try:
        s3_client.head_bucket(Bucket=bucket_name)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in {"404", "NoSuchBucket", "NotFound"}:
            raise click.ClickException(f"Bucket introuvable: {bucket_name}") from e
        # d'autres erreurs, on remonte
        raise

    if force_delete:
        print(f"Emptying bucket {bucket_name}")
        # Vide le bucket (objets et versions)
        empty_bucket(s3_client, bucket_name)

    # Supprime le bucket
    s3_client.delete_bucket(Bucket=bucket_name)
    click.secho(f"Bucket supprimé: {bucket_name}", fg="green")


def get_bucket_policy(s3_client, bucket_name: str) -> Optional[str]:
    """Récupère la bucket policy.
    Retourne la chaîne JSON si présente, sinon None (si pas de policy).
    """
    try:
        resp = s3_client.get_bucket_policy(Bucket=bucket_name)
        # AWS renvoie {'Policy': '<json string>'}
        policy_str = resp.get("Policy")
        if isinstance(policy_str, str) and policy_str.strip():
            return policy_str
        return None
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in {"NoSuchBucketPolicy"}:
            return None
        if code in {"NoSuchBucket", "404", "NotFound"}:
            raise click.ClickException(f"Bucket introuvable: {bucket_name}") from e
        raise


def get_bucket_lifecycle(s3_client, bucket_name: str) -> Optional[Dict[str, Any]]:
    """Récupère la configuration de lifecycle du bucket.
    Retourne un dict (ex: {"Rules": [...]}) si présent, sinon None.
    """
    try:
        resp = s3_client.get_bucket_lifecycle_configuration(Bucket=bucket_name)
        # Boto3 renvoie un dict contenant au moins 'Rules'
        if isinstance(resp, dict) and resp.get("Rules"):
            return resp
        return None
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        # Codes possibles si pas de lifecycle
        if code in {"NoSuchLifecycleConfiguration", "NoSuchBucketLifecycle", "NoSuchConfiguration"}:
            return None
        if code in {"NoSuchBucket", "404", "NotFound"}:
            raise click.ClickException(f"Bucket introuvable: {bucket_name}") from e
        raise


def apply_bucket_lifecycle(
    s3_client,
    bucket_name: str,
    lifecycle: Dict[str, Any] | str,
    *,
    validate: bool = True,
) -> None:
    """Applique une Lifecycle Configuration sur un bucket S3.
    Accepte un JSON inline (str) ou un dict Python. Exemple attendu:
      {"Rules": [{"ID": "expire-raw", "Status": "Enabled", "Filter": {"Prefix": "raw/"}, "Expiration": {"Days": 30}}]}
    """
    import json as _json

    # Parse en dict si fourni en texte
    if isinstance(lifecycle, str):
        try:
            obj = _json.loads(lifecycle)
        except Exception as e:
            raise click.ClickException("La lifecycle fournie n'est pas un JSON valide.") from e
    else:
        obj = lifecycle

    if not isinstance(obj, dict):
        raise click.ClickException("Lifecycle invalide: un objet JSON est attendu.")

    # Supporte les deux formes: {"Rules": [...]} ou {"LifecycleConfiguration": {"Rules": [...]}}
    if "LifecycleConfiguration" in obj and isinstance(obj["LifecycleConfiguration"], dict):
        config = obj["LifecycleConfiguration"]
    else:
        config = obj

    # Validation minimale
    rules = config.get("Rules")
    if validate:
        if not isinstance(rules, list) or not rules:
            raise click.ClickException("Lifecycle invalide: 'Rules' (liste) est requis et ne peut pas être vide.")
        # Test basique des règles
        for idx, rule in enumerate(rules):
            if not isinstance(rule, dict):
                raise click.ClickException(f"Règle #{idx} invalide: un objet est attendu.")
            status = rule.get("Status")
            if status not in {"Enabled", "Disabled"}:
                raise click.ClickException(
                    f"Règle #{idx} invalide: 'Status' doit être 'Enabled' ou 'Disabled'."
                )
            # Doit avoir un Filter ou un Prefix (legacy)
            if "Filter" not in rule and "Prefix" not in rule:
                raise click.ClickException(
                    f"Règle #{idx} invalide: 'Filter' ou 'Prefix' est requis."
                )

    # Appel S3
    try:
        s3_client.put_bucket_lifecycle_configuration(
            Bucket=bucket_name,
            LifecycleConfiguration=config,
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in {"NoSuchBucket", "404", "NotFound"}:
            raise click.ClickException(f"Bucket introuvable: {bucket_name}") from e
        if code in {"MalformedXML", "InvalidRequest"}:
            raise click.ClickException(
                "Lifecycle rejetée par S3 (MalformedXML/InvalidRequest). Vérifiez la structure des Rules."
            ) from e
        raise
    click.secho(f"Lifecycle appliquée sur {bucket_name}", fg="green")


def apply_bucket_encryption(
    s3_client,
    bucket_name: str,
    encryption: Dict[str, Any] | str,
    *,
    validate: bool = True,
) -> None:
    """Applique une configuration d'encryptage (SSE) sur un bucket.
    Accepte les deux formes:
      - {"ServerSideEncryptionConfiguration": {"Rules": [...]}}
      - {"Rules": [...]} (forme raccourcie)
    Exemple minimal (AES256):
      {"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}
    Exemple KMS:
      {"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms","KMSMasterKeyID":"<arn-ou-id>"},"BucketKeyEnabled":true}]}
    """
    import json as _json

    # Parse si inline string
    if isinstance(encryption, str):
        try:
            obj = _json.loads(encryption)
        except Exception as e:
            raise click.ClickException("La configuration d'encryptage fournie n'est pas un JSON valide.") from e
    else:
        obj = encryption

    if not isinstance(obj, dict):
        raise click.ClickException("Configuration d'encryptage invalide: un objet JSON est attendu.")

    # Détecte la configuration
    if "ServerSideEncryptionConfiguration" in obj and isinstance(obj["ServerSideEncryptionConfiguration"], dict):
        config = obj["ServerSideEncryptionConfiguration"]
    else:
        config = obj

    rules = config.get("Rules")

    if validate:
        if not isinstance(rules, list) or not rules:
            raise click.ClickException("Encryptage invalide: 'Rules' (liste) est requis et ne peut pas être vide.")
        for idx, rule in enumerate(rules):
            if not isinstance(rule, dict):
                raise click.ClickException(f"Règle #{idx} invalide: un objet est attendu.")
            default = rule.get("ApplyServerSideEncryptionByDefault")
            if not isinstance(default, dict):
                raise click.ClickException(
                    f"Règle #{idx} invalide: 'ApplyServerSideEncryptionByDefault' est requis et doit être un objet."
                )
            algo = default.get("SSEAlgorithm")
            if algo not in {"AES256", "aws:kms"}:
                raise click.ClickException(
                    f"Règle #{idx} invalide: 'SSEAlgorithm' doit être 'AES256' ou 'aws:kms'."
                )
            if algo == "aws:kms" and not default.get("KMSMasterKeyID"):
                # facultatif côté AWS si une clé par défaut est configurée; on conseille fortement de le fournir
                click.secho(
                    f"Avertissement: règle #{idx} avec 'aws:kms' sans 'KMSMasterKeyID'. Assurez-vous d'avoir une clé KMS par défaut.",
                    fg="yellow",
                )
            bke = rule.get("BucketKeyEnabled")
            if bke is not None and not isinstance(bke, bool):
                raise click.ClickException(f"Règle #{idx} invalide: 'BucketKeyEnabled' doit être booléen si présent.")

    try:
        s3_client.put_bucket_encryption(
            Bucket=bucket_name,
            ServerSideEncryptionConfiguration={"Rules": rules} if rules is not None else config,
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in {"NoSuchBucket", "404", "NotFound"}:
            raise click.ClickException(f"Bucket introuvable: {bucket_name}") from e
        if code in {"MalformedXML", "InvalidRequest"}:
            raise click.ClickException(
                "Configuration d'encryptage rejetée par S3 (MalformedXML/InvalidRequest). Vérifiez 'Rules' et 'SSEAlgorithm'."
            ) from e
        raise
    click.secho(f"Encryption (SSE) appliquée sur {bucket_name}", fg="green")

