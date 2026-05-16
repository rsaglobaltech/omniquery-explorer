#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.local-db.yml"

MYSQL_CONTAINER="${MYSQL_CONTAINER:-omniquery-mysql-local}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-omniquery-postgres-local}"

export AWS_MYSQL_HOST="${AWS_MYSQL_HOST:-127.0.0.1}"
export AWS_MYSQL_PORT="${AWS_MYSQL_PORT:-3307}"
export AWS_MYSQL_USER="${AWS_MYSQL_USER:-admin}"
export AWS_MYSQL_PASSWORD="${AWS_MYSQL_PASSWORD:-Server2026}"

export AWS_PG_HOST="${AWS_PG_HOST:-127.0.0.1}"
export AWS_PG_PORT="${AWS_PG_PORT:-5433}"
export AWS_PG_USER="${AWS_PG_USER:-admin}"
export AWS_PG_PASSWORD="${AWS_PG_PASSWORD:-Server2026}"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

wait_for_mysql() {
  local retries=60
  while ((retries > 0)); do
    if docker exec "$MYSQL_CONTAINER" mysqladmin ping -h 127.0.0.1 -uroot -proot >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
    retries=$((retries - 1))
  done
  echo "MySQL no quedo listo a tiempo." >&2
  return 1
}

wait_for_postgres() {
  local retries=60
  while ((retries > 0)); do
    if docker exec "$POSTGRES_CONTAINER" pg_isready -U "$AWS_PG_USER" -d postgres >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
    retries=$((retries - 1))
  done
  echo "PostgreSQL no quedo listo a tiempo." >&2
  return 1
}

setup_psql_wrapper() {
  local wrapper_dir="${PROJECT_ROOT}/.tmp/local_import/bin"
  mkdir -p "$wrapper_dir"

  cat >"${wrapper_dir}/psql" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-omniquery-postgres-local}"
user=""
db=""
file=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --username)
      user="$2"
      shift 2
      ;;
    --dbname)
      db="$2"
      shift 2
      ;;
    --file)
      file="$2"
      shift 2
      ;;
    --host|--port)
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

if [[ -z "$user" || -z "$db" || -z "$file" ]]; then
  echo "psql wrapper: argumentos insuficientes" >&2
  exit 1
fi

while IFS= read -r csv_path; do
  [[ -z "$csv_path" ]] && continue
  if [[ ! -f "$csv_path" ]]; then
    echo "psql wrapper: no existe CSV local: $csv_path" >&2
    exit 1
  fi
  docker exec "$POSTGRES_CONTAINER" mkdir -p "$(dirname "$csv_path")"
  docker cp "$csv_path" "${POSTGRES_CONTAINER}:${csv_path}"
done < <(python3 - "$file" <<'PY'
import re
import sys

content = open(sys.argv[1], encoding="utf-8").read()
for path in sorted(set(re.findall(r"FROM '([^']+)'", content))):
    print(path)
PY
)

cat "$file" | docker exec -i "$POSTGRES_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$user" -d "$db"
EOF

  chmod +x "${wrapper_dir}/psql"
  export PATH="${wrapper_dir}:${PATH}"
}

create_mysql_db() {
  local db="$1"
  MYSQL_PWD="root" mysql \
    --host "$AWS_MYSQL_HOST" \
    --port "$AWS_MYSQL_PORT" \
    --user "root" \
    -e "DROP DATABASE IF EXISTS \`${db}\`; CREATE DATABASE \`${db}\`; GRANT ALL PRIVILEGES ON \`${db}\`.* TO '${AWS_MYSQL_USER}'@'%'; FLUSH PRIVILEGES;"
}

create_postgres_db() {
  local db="$1"
  docker exec -i "$POSTGRES_CONTAINER" psql -U "$AWS_PG_USER" -d postgres -v ON_ERROR_STOP=1 -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${db}' AND pid <> pg_backend_pid();"
  docker exec -i "$POSTGRES_CONTAINER" psql -U "$AWS_PG_USER" -d postgres -v ON_ERROR_STOP=1 -c \
    "DROP DATABASE IF EXISTS \"${db}\";"
  docker exec -i "$POSTGRES_CONTAINER" psql -U "$AWS_PG_USER" -d postgres -v ON_ERROR_STOP=1 -c \
    "CREATE DATABASE \"${db}\";"
}

run_mysql_dataset() {
  local db="$1"
  local script="$2"
  create_mysql_db "$db"
  AWS_MYSQL_DB="$db" "$script"
}

run_postgres_dataset() {
  local db="$1"
  local script="$2"
  create_postgres_db "$db"
  AWS_PG_DB="$db" "$script"
}

import_mysql() {
  log "Importando datasets MySQL..."
  run_mysql_dataset "airline_passenger_satisfaction_db" "${PROJECT_ROOT}/scripts/aws_import/import_airline_passenger_satisfaction_mysql.sh"
  run_mysql_dataset "maven_fuzzy_factory_db" "${PROJECT_ROOT}/scripts/aws_import/import_maven_fuzzy_factory_mysql.sh"
  run_mysql_dataset "videos_subcriptions_db" "${PROJECT_ROOT}/scripts/aws_import/import_streaming_video_subscriptions_mysql.sh"
  run_mysql_dataset "uk_train_rides_db" "${PROJECT_ROOT}/scripts/aws_import/import_uk_train_rides_mysql.sh"
}

import_postgres() {
  log "Importando datasets PostgreSQL..."
  run_postgres_dataset "airline_loyalty_program_db" "${PROJECT_ROOT}/scripts/aws_import/import_airline_loyalty_program_postgres.sh"
  run_postgres_dataset "bank_customer_churn_db" "${PROJECT_ROOT}/scripts/aws_import/import_bank_customer_churn_postgres.sh"
  run_postgres_dataset "hospital_patient_records_db" "${PROJECT_ROOT}/scripts/aws_import/import_hospital_patient_records_postgres.sh"
  run_postgres_dataset "restaurant_orders_db" "${PROJECT_ROOT}/scripts/aws_import/import_restaurant_orders_postgres.sh"
}

show_summary() {
  log "Resumen MySQL (todas las DBs importadas)"
  MYSQL_PWD="$AWS_MYSQL_PASSWORD" mysql \
    --host "$AWS_MYSQL_HOST" \
    --port "$AWS_MYSQL_PORT" \
    --user "$AWS_MYSQL_USER" \
    -e "SELECT table_schema, table_name, table_rows FROM information_schema.tables WHERE table_schema IN ('airline_passenger_satisfaction_db','maven_fuzzy_factory_db','videos_subcriptions_db','uk_train_rides_db') ORDER BY table_schema, table_name;"

  log "Resumen PostgreSQL (tablas por DB)"
  for db in airline_loyalty_program_db bank_customer_churn_db hospital_patient_records_db restaurant_orders_db; do
    echo "DB: ${db}"
    docker exec -i "$POSTGRES_CONTAINER" psql -U "$AWS_PG_USER" -d "$db" -c \
      "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;"
  done
}

main() {
  log "Levantando contenedores locales..."
  docker compose -f "$COMPOSE_FILE" up -d
  wait_for_mysql
  wait_for_postgres
  setup_psql_wrapper
  import_mysql
  import_postgres
  show_summary
  log "Importacion local completa."
}

main "$@"
