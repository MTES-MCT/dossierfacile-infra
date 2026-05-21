import argparse
import shlex
import subprocess
import sys

import boto3
from botocore.config import Config


def generate_presigned_get_url(
        endpoint_url,
        region,
        access_key,
        secret_key,
        bucket,
        object_key,
        expires_in,
):
    """Genere une URL presignee GET pour un objet S3."""
    client = boto3.client(
        "s3",
        region_name=region,
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
    )

    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": object_key},
        ExpiresIn=expires_in,
        HttpMethod="GET",
    )


def run_scalingo_command(app_name, region, size, script):
    """Execute un script shell dans un conteneur one-off Scalingo via stdin."""
    full_cmd = [
        "scalingo",
        "--app",
        app_name,
        "--region",
        region,
        "run",
        "--size",
        size,
        "--",
        "/bin/sh",
        "-s",
    ]

    try:
        process = subprocess.Popen(
            full_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        if process.stdin is not None:
            process.stdin.write(script)
            process.stdin.close()

        if process.stdout is not None:
            for line in process.stdout:
                print(f"[Scalingo] {line}", end="")

        return process.wait()
    except Exception as exc:
        print(f"Erreur systeme: {exc}")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Import Keycloak depuis une archive S3 via URL presignee"
    )

    parser.add_argument("--app", required=True, help="Nom de l'app Scalingo Keycloak")
    parser.add_argument("--region", required=True, help="Region de l'app scalingo")
    parser.add_argument(
        "--size",
        required=True,
        choices=["S", "M", "L", "XL", "2XL"],
        help="Taille du conteneur one-off Scalingo",
    )
    parser.add_argument(
        "--s3-object-key",
        required=True,
        help="Cle objet S3 a importer.",
    )

    parser.add_argument("--s3-url", required=True, help="Endpoint S3 (ex: https://s3.eu-west-par.io.cloud.ovh.net)")
    parser.add_argument("--s3-region", required=True, help="Region S3 (ex: eu-west-par, sbg)")
    parser.add_argument("--s3-bucket", required=True, help="Nom du bucket source")
    parser.add_argument("--s3-access-key", required=True, help="S3 access key")
    parser.add_argument("--s3-secret-key", required=True, help="S3 secret key")
    parser.add_argument("--expires-in", type=int, default=3600, help="Duree de validite de l'URL presignee (sec)")
    parser.add_argument(
        "--override",
        choices=["true", "false"],
        default="true",
        help="Valeur de --override pour kc.sh import (defaut: true)",
    )

    args = parser.parse_args()

    if args.expires_in < 60:
        print("ERROR: --expires-in doit etre >= 60 secondes.")
        sys.exit(1)

    object_key = args.s3_object_key.strip()
    if not object_key:
        print("ERROR: --s3-object-key ne doit pas etre vide.")
        sys.exit(1)

    print("[1/3] Generation de l'URL presignee GET...")
    try:
        presigned_url = generate_presigned_get_url(
            endpoint_url=args.s3_url,
            region=args.s3_region,
            access_key=args.s3_access_key,
            secret_key=args.s3_secret_key,
            bucket=args.s3_bucket,
            object_key=object_key,
            expires_in=args.expires_in,
        )
    except Exception as exc:
        print(f"ERROR: Impossible de generer l'URL presignee: {exc}")
        sys.exit(1)

    print("OK: URL presignee generee.")
    print("[2/3] Lancement du one-off Scalingo (import Keycloak)...")

    setup_script = f"""
set -Eeuo pipefail
PRESIGNED_URL={shlex.quote(presigned_url)}
EXTRACT_ROOT=/tmp
IMPORT_DIR=/tmp/kc-export
OVERRIDE={shlex.quote(args.override)}

while true; do echo -n "." >&2; sleep 20; done &
KPID=$!
trap 'kill $KPID 2>/dev/null || true' EXIT

echo '[1/3] Download + extraction en streaming depuis S3...'
DOWNLOAD_RESP_FILE=/tmp/s3-download-response.txt
rm -rf "$IMPORT_DIR"
if ! curl -f -sS -L "$PRESIGNED_URL" | tar -xzf - -C "$EXTRACT_ROOT"; then
  HTTP_CODE=$(curl -sS -o "$DOWNLOAD_RESP_FILE" -w '%{{http_code}}' -L "$PRESIGNED_URL" || true)
  echo "ERROR: Download/Extraction S3 echoue (HTTP $HTTP_CODE)" >&2
  echo '--- S3 response body ---' >&2
  cat "$DOWNLOAD_RESP_FILE" >&2 || true
  echo '--- end S3 response body ---' >&2
  exit 1
fi

echo '[2/3] Verification de l extraction...'
[ -d "$IMPORT_DIR" ] || {{ echo 'ERROR: dossier /tmp/kc-export introuvable apres extraction' >&2; exit 1; }}

echo '[3/3] Import Keycloak...'
# Augmente le timeout de transaction pour les imports volumineux.
export JAVA_OPTS_APPEND="${{JAVA_OPTS_APPEND:-}} -Dquarkus.transaction-manager.default-transaction-timeout=900"
/app/keycloak/bin/kc.sh import --dir "$IMPORT_DIR" --override "$OVERRIDE"

echo '[OK] Import Keycloak termine.'
"""

    exit_code = run_scalingo_command(args.app, args.region, args.size, setup_script)

    if exit_code == 0:
        print("\nOK: Import Keycloak reussi.")
        print(f"Objet source: s3://{args.s3_bucket}/{object_key}")
    else:
        print("\nERROR: Echec de l'import. Verifie les logs ci-dessus.")
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
