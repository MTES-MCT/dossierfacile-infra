import argparse
import subprocess
import sys
import shlex
from datetime import datetime

import boto3
from botocore.config import Config


def generate_presigned_put_url(
    endpoint_url,
    region,
    access_key,
    secret_key,
    bucket,
    object_key,
    expires_in,
):
    """Genere une URL presignee PUT pour un objet S3."""
    client = boto3.client(
        "s3",
        region_name=region,
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
    )

    return client.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": object_key},
        ExpiresIn=expires_in,
        HttpMethod="PUT",
    )


def run_scalingo_command(app_name,region, size, script):
    """Execute un script shell dans un conteneur one-off Scalingo via stdin."""
    full_cmd = [
        "scalingo",
        "--region" ,
        region,
        "--app",
        app_name,
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
        description="Export Keycloak + upload de l'archive vers S3 via URL presignee"
    )

    parser.add_argument("--app", required=True, help="Nom de l'app Scalingo Keycloak")
    parser.add_argument("--region", required=True, help="Region de l'app scalingo")
    parser.add_argument("--env", required=True, help="Environnement cible (ex: dev, preprod, prod)")
    parser.add_argument(
        "--size",
        required=True,
        choices=["S", "M", "L", "XL", "2XL"],
        help="Taille du conteneur one-off Scalingo",
    )
    parser.add_argument(
        "--users-mode",
        default="different_files",
        help="Valeur passee a '--users' pour 'kc.sh export' (ex: different_files)",
    )

    parser.add_argument("--s3-url", required=True, help="Endpoint S3 (ex: https://s3.sbg.perf.cloud.ovh.net)")
    parser.add_argument("--s3-region", required=True, help="Region S3 (ex: sbg)")
    parser.add_argument("--s3-bucket", required=True, help="Nom du bucket cible")
    parser.add_argument("--s3-access-key", required=True, help="S3 access key")
    parser.add_argument("--s3-secret-key", required=True, help="S3 secret key")
    parser.add_argument("--expires-in", type=int, default=3600, help="Duree de validite de l'URL presignee (sec)")

    args = parser.parse_args()

    if args.expires_in < 60:
        print("ERROR: --expires-in doit etre >= 60 secondes.")
        sys.exit(1)

    sanitized_env = args.env.strip().lower()
    if not sanitized_env:
        print("ERROR: --env ne doit pas etre vide.")
        sys.exit(1)

    object_key = f"export-keycloak-{sanitized_env}-{datetime.now().strftime('%m_%d_%Y')}.tar.gz"

    print("[1/3] Generation de l'URL presignee PUT...")
    try:
        presigned_url = generate_presigned_put_url(
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
    print("[2/3] Lancement du one-off Scalingo (export Keycloak)...")

    setup_script = f"""
set -Eeuo pipefail
PRESIGNED_URL={shlex.quote(presigned_url)}
USERS_MODE={shlex.quote(args.users_mode)}
EXPORT_DIR=/tmp/kc-export

# Keep-alive leger pour eviter les timeouts de logs pendant l'export
while true; do echo -n "." >&2; sleep 20; done &
KPID=$!
trap 'kill $KPID 2>/dev/null || true' EXIT

echo '[1/3] Export Keycloak...'
mkdir -p "$EXPORT_DIR"
export JAVA_OPTS_APPEND="-Xmx4G"
/app/keycloak/bin/kc.sh export --dir "$EXPORT_DIR" --users "$USERS_MODE" --users-per-file 500 --optimized

echo '[2/3] Archivage + upload en streaming vers S3...'
UPLOAD_RESP_FILE=/tmp/s3-upload-response.txt
HTTP_CODE=$(tar -czf - -C /tmp kc-export | curl -sS -o "$UPLOAD_RESP_FILE" -w '%{{http_code}}' -X PUT -T - "$PRESIGNED_URL")
if [ "$HTTP_CODE" != "200" ]; then
  echo "ERROR: Upload S3 echoue (HTTP $HTTP_CODE)" >&2
  echo '--- S3 response body ---' >&2
  cat "$UPLOAD_RESP_FILE" >&2 || true
  echo '--- end S3 response body ---' >&2
  exit 1
fi

echo '[OK] Export + upload termines.'
"""

    exit_code = run_scalingo_command(args.app, args.region, args.size, setup_script)

    if exit_code == 0:
        print("\nOK: Export Keycloak + upload S3 reussis.")
        print(f"Objet cible: s3://{args.s3_bucket}/{object_key}")
    else:
        print("\nERROR: Echec de l'export/upload. Verifie les logs ci-dessus.")
        sys.exit(exit_code)


if __name__ == "__main__":
    main()

