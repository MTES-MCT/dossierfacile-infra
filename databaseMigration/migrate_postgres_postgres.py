import subprocess
import sys
import argparse
import shlex

def run_scalingo_command(app_name, size, command):
    """Exécute une commande sur un conteneur one-off Scalingo."""
    full_cmd = ["scalingo", "--app", app_name, "run", '--size', size, command]
    try:
        process = subprocess.Popen(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        if process.stdout is not None:
            for line in process.stdout:
                print(f"[Scalingo] {line}", end="")
        process.wait()
        return process.returncode
    except Exception as e:
        print(f"Erreur système : {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Migration Tool Dossier Facile")
    parser.add_argument("--app", required=True, help="Nom de l'app Scalingo cible")
    parser.add_argument("--size", required=True, choices=['S', 'M', 'L', 'XL', '2XL'], help="Taille du container one-off sur Scalingo")
    parser.add_argument("--source-url", required=True, help="URL PostgreSQL source (ex: postgresql://user:pass@host/db)")
    parser.add_argument("--target-url", required=False, help="URL PostgreSQL cible (base vide)")
    parser.add_argument("--jobs", type=int, default=4, help="Nombre de workers pg_restore (défaut: 4)")

    args = parser.parse_args()

    if not args.target_url:
        print("❌ --target-url est obligatoire pour une migration postgres -> postgres.")
        sys.exit(1)

    if args.jobs < 1:
        print("❌ --jobs doit être >= 1.")
        sys.exit(1)

    print("🛠  Migration PostgreSQL -> PostgreSQL (schéma + données + index + contraintes)...")
    setup_script = f"""
set -Eeuo pipefail;
SOURCE_URL={shlex.quote(args.source_url)};
TARGET_URL={shlex.quote(args.target_url)};
RESTORE_JOBS={args.jobs};
DUMP_FILE=/tmp/source_pg_dump.dump;

echo '[Setup] Vérification des outils PostgreSQL de base...';
command -v psql >/dev/null 2>&1;

SOURCE_MAJOR=$(psql "$SOURCE_URL" -v ON_ERROR_STOP=1 -Atc "SELECT current_setting('server_version_num')::int / 10000;");
if [ -z "$SOURCE_MAJOR" ]; then
  echo '[Erreur] Impossible de détecter la version PostgreSQL source.' >&2;
  exit 1;
fi;

echo "[Setup] Version majeure source détectée: $SOURCE_MAJOR";

if command -v "pg_dump-$SOURCE_MAJOR" >/dev/null 2>&1; then
  PG_DUMP_BIN="pg_dump-$SOURCE_MAJOR";
  PG_RESTORE_BIN="pg_restore-$SOURCE_MAJOR";
  if command -v "psql-$SOURCE_MAJOR" >/dev/null 2>&1; then
    PSQL_BIN="psql-$SOURCE_MAJOR";
  else
    PSQL_BIN="psql";
  fi;
elif [ -x "/app/.apt/usr/lib/postgresql/$SOURCE_MAJOR/bin/pg_dump" ]; then
  PG_DUMP_BIN="/app/.apt/usr/lib/postgresql/$SOURCE_MAJOR/bin/pg_dump";
  PG_RESTORE_BIN="/app/.apt/usr/lib/postgresql/$SOURCE_MAJOR/bin/pg_restore";
  PSQL_BIN="/app/.apt/usr/lib/postgresql/$SOURCE_MAJOR/bin/psql";
else
  echo "[Erreur] Aucun client PostgreSQL versionne pour la majeure $SOURCE_MAJOR. Installe postgresql-client-$SOURCE_MAJOR dans l'image." >&2;
  exit 1;
fi;

DUMP_MAJOR=$($PG_DUMP_BIN --version | sed -E 's/.* ([0-9]+)\\..*/\\1/');
if [ -z "$DUMP_MAJOR" ] || [ "$DUMP_MAJOR" -lt "$SOURCE_MAJOR" ]; then
  echo "[Erreur] pg_dump incompatible (version $DUMP_MAJOR) pour serveur source majeur $SOURCE_MAJOR." >&2;
  exit 1;
fi;

echo "[Setup] pg_dump utilisé: $($PG_DUMP_BIN --version)";

echo '[Setup] Contrôle que la base cible est vide...';
TARGET_EMPTY=$($PSQL_BIN "$TARGET_URL" -v ON_ERROR_STOP=1 -Atc "SELECT NOT EXISTS (SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg_toast%');");
if [ "$TARGET_EMPTY" != "t" ]; then
  echo "[Erreur] La base cible n'est pas vide. Abandon pour éviter un restore non déterministe." >&2;
  exit 1;
fi;

echo '[Dump] Export complet de la base source (non destructif)...';
$PG_DUMP_BIN --dbname "$SOURCE_URL" --format=custom --no-owner --no-privileges --verbose --file "$DUMP_FILE";

echo '[Restore] Import complet dans la base cible...';
$PG_RESTORE_BIN --dbname "$TARGET_URL" --jobs "$RESTORE_JOBS" --no-owner --no-privileges --verbose "$DUMP_FILE";

echo '[Post] Mise à jour des statistiques (ANALYZE)...';
$PSQL_BIN "$TARGET_URL" -v ON_ERROR_STOP=1 -Atc "SELECT format('ANALYZE %I.%I;', schemaname, tablename) FROM pg_catalog.pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema') AND schemaname NOT LIKE 'pg_toast%';" | $PSQL_BIN "$TARGET_URL" -v ON_ERROR_STOP=1;

echo '[OK] Migration PostgreSQL terminée.';
"""

    full_script = f"bash -lc {shlex.quote(setup_script)}"

    exit_code = run_scalingo_command(args.app, args.size, full_script)

    if exit_code == 0:
        print("\n✅ Migration terminée avec succès.")
    else:
        print("\n❌ Échec de la migration. Vérifiez les logs Scalingo.")


if __name__ == "__main__":
    main()