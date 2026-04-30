#!/usr/bin/env bash
set -euo pipefail

COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${COMMON_DIR}/../../.." && pwd)"
DBS_DIR="${PROJECT_ROOT}/dbs"
WORK_ROOT="${PROJECT_ROOT}/.tmp/aws_import"

TARGET_ENGINE="${TARGET_ENGINE:-}"
DATASET_ZIP="${DATASET_ZIP:-}"
DATASET_SLUG="${DATASET_SLUG:-}"
TABLE_PREFIX="${TABLE_PREFIX:-}"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Falta comando requerido: $1" >&2
    exit 1
  fi
}

sanitize_identifier() {
  local raw="$1"
  local clean
  clean="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/_/g; s/_+/_/g; s/^_+//; s/_+$//')"
  if [[ -z "$clean" ]]; then
    clean="col"
  fi
  if [[ "$clean" =~ ^[0-9] ]]; then
    clean="c_${clean}"
  fi
  printf '%s' "$clean"
}

assert_config() {
  if [[ -z "$TARGET_ENGINE" || -z "$DATASET_ZIP" || -z "$DATASET_SLUG" ]]; then
    echo "TARGET_ENGINE, DATASET_ZIP y DATASET_SLUG son obligatorios." >&2
    exit 1
  fi
  if [[ -z "$TABLE_PREFIX" ]]; then
    TABLE_PREFIX="$(sanitize_identifier "$DATASET_SLUG")"
  fi
}

extract_dataset() {
  require_cmd unzip
  local zip_file="${PROJECT_ROOT}/${DATASET_ZIP}"
  if [[ ! -f "$zip_file" ]]; then
    echo "No existe el ZIP: $zip_file" >&2
    exit 1
  fi

  local out_dir="${WORK_ROOT}/${DATASET_SLUG}"
  rm -rf "$out_dir"
  mkdir -p "$out_dir"
  unzip -q "$zip_file" -d "$out_dir"
  printf '%s' "$out_dir"
}

collect_csv_files() {
  local dir="$1"
  find "$dir" -type f -iname '*.csv' ! -path '*/__MACOSX/*' | sort
}

read_columns_from_csv() {
  local csv_file="$1"
  python3 - "$csv_file" <<'PY'
import csv
import re
import sys

path = sys.argv[1]
with open(path, newline="", encoding="utf-8-sig") as f:
    reader = csv.reader(f)
    header = next(reader, [])

seen = {}
for i, col in enumerate(header, 1):
    col = col.strip().lower()
    col = re.sub(r"[^a-z0-9]+", "_", col)
    col = re.sub(r"_+", "_", col).strip("_")
    if not col:
        col = f"col_{i}"
    if col[0].isdigit():
        col = f"c_{col}"
    count = seen.get(col, 0) + 1
    seen[col] = count
    out = col if count == 1 else f"{col}_{count}"
    print(out)
PY
}

join_by() {
  local IFS="$1"
  shift
  printf '%s' "$*"
}

escape_sql_single_quotes() {
  printf '%s' "$1" | sed "s/'/''/g"
}

run_postgres_import() {
  require_cmd psql
  require_cmd python3
  : "${AWS_PG_HOST:?Define AWS_PG_HOST}"
  : "${AWS_PG_DB:?Define AWS_PG_DB}"
  : "${AWS_PG_USER:?Define AWS_PG_USER}"
  : "${AWS_PG_PASSWORD:?Define AWS_PG_PASSWORD}"
  local pg_port="${AWS_PG_PORT:-5432}"

  local dataset_dir
  dataset_dir="$(extract_dataset)"
  local sql_file="${WORK_ROOT}/${DATASET_SLUG}_postgres.sql"
  mkdir -p "$WORK_ROOT"
  : >"$sql_file"

  while IFS= read -r csv; do
    local base table
    base="$(basename "$csv" .csv)"
    table="$(sanitize_identifier "${TABLE_PREFIX}_${base}")"

    mapfile -t cols < <(read_columns_from_csv "$csv")
    if [[ "${#cols[@]}" -eq 0 ]]; then
      log "Saltando (sin cabecera): $csv"
      continue
    fi

    local col_defs=()
    local col_refs=()
    local c
    for c in "${cols[@]}"; do
      col_defs+=("\"${c}\" TEXT")
      col_refs+=("\"${c}\"")
    done

    local csv_escaped
    csv_escaped="$(escape_sql_single_quotes "$csv")"
    {
      printf 'CREATE TABLE IF NOT EXISTS "%s" (%s);\n' "$table" "$(join_by ', ' "${col_defs[@]}")"
      printf "\\copy \"%s\" (%s) FROM '%s' WITH (FORMAT csv, HEADER true);\n" \
        "$table" "$(join_by ', ' "${col_refs[@]}")" "$csv_escaped"
    } >>"$sql_file"
  done < <(collect_csv_files "$dataset_dir")

  PGPASSWORD="$AWS_PG_PASSWORD" psql \
    --host "$AWS_PG_HOST" \
    --port "$pg_port" \
    --username "$AWS_PG_USER" \
    --dbname "$AWS_PG_DB" \
    --file "$sql_file"
}

run_mysql_import() {
  require_cmd mysql
  require_cmd python3
  : "${AWS_MYSQL_HOST:?Define AWS_MYSQL_HOST}"
  : "${AWS_MYSQL_DB:?Define AWS_MYSQL_DB}"
  : "${AWS_MYSQL_USER:?Define AWS_MYSQL_USER}"
  : "${AWS_MYSQL_PASSWORD:?Define AWS_MYSQL_PASSWORD}"
  local mysql_port="${AWS_MYSQL_PORT:-3306}"

  local dataset_dir
  dataset_dir="$(extract_dataset)"
  local sql_file="${WORK_ROOT}/${DATASET_SLUG}_mysql.sql"
  mkdir -p "$WORK_ROOT"
  : >"$sql_file"

  while IFS= read -r csv; do
    local base table
    base="$(basename "$csv" .csv)"
    table="$(sanitize_identifier "${TABLE_PREFIX}_${base}")"

    mapfile -t cols < <(read_columns_from_csv "$csv")
    if [[ "${#cols[@]}" -eq 0 ]]; then
      log "Saltando (sin cabecera): $csv"
      continue
    fi

    local col_defs=()
    local col_refs=()
    local c
    for c in "${cols[@]}"; do
      col_defs+=("`${c}` LONGTEXT")
      col_refs+=("`${c}`")
    done

    local csv_escaped
    csv_escaped="$(printf '%s' "$csv" | sed -e "s/\\\\/\\\\\\\\/g" -e "s/'/\\\\'/g")"
    {
      printf 'CREATE TABLE IF NOT EXISTS `%s` (%s);\n' "$table" "$(join_by ', ' "${col_defs[@]}")"
      printf "LOAD DATA LOCAL INFILE '%s' INTO TABLE \`%s\` CHARACTER SET utf8mb4 FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"' LINES TERMINATED BY '\\n' IGNORE 1 LINES (%s);\n" \
        "$csv_escaped" "$table" "$(join_by ', ' "${col_refs[@]}")"
    } >>"$sql_file"
  done < <(collect_csv_files "$dataset_dir")

  MYSQL_PWD="$AWS_MYSQL_PASSWORD" mysql \
    --host "$AWS_MYSQL_HOST" \
    --port "$mysql_port" \
    --user "$AWS_MYSQL_USER" \
    --database "$AWS_MYSQL_DB" \
    --local-infile=1 <"$sql_file"
}

run_oracle_import() {
  require_cmd sqlplus
  require_cmd sqlldr
  require_cmd python3
  : "${AWS_ORACLE_HOST:?Define AWS_ORACLE_HOST}"
  : "${AWS_ORACLE_SERVICE:?Define AWS_ORACLE_SERVICE}"
  : "${AWS_ORACLE_USER:?Define AWS_ORACLE_USER}"
  : "${AWS_ORACLE_PASSWORD:?Define AWS_ORACLE_PASSWORD}"
  local oracle_port="${AWS_ORACLE_PORT:-1521}"
  local conn="${AWS_ORACLE_USER}/${AWS_ORACLE_PASSWORD}@//${AWS_ORACLE_HOST}:${oracle_port}/${AWS_ORACLE_SERVICE}"

  local dataset_dir
  dataset_dir="$(extract_dataset)"
  local sql_file="${WORK_ROOT}/${DATASET_SLUG}_oracle_tables.sql"
  mkdir -p "$WORK_ROOT"
  : >"$sql_file"

  while IFS= read -r csv; do
    local base table
    base="$(basename "$csv" .csv)"
    table="$(sanitize_identifier "${TABLE_PREFIX}_${base}")"

    mapfile -t cols < <(read_columns_from_csv "$csv")
    if [[ "${#cols[@]}" -eq 0 ]]; then
      log "Saltando (sin cabecera): $csv"
      continue
    fi

    local col_defs=()
    local col_list=()
    local c
    for c in "${cols[@]}"; do
      col_defs+=("\"${c}\" VARCHAR2(4000)")
      col_list+=("\"${c}\" CHAR(4000)")
    done

    {
      printf "BEGIN EXECUTE IMMEDIATE 'DROP TABLE \"%s\"'; EXCEPTION WHEN OTHERS THEN IF SQLCODE != -942 THEN RAISE; END IF; END;\n/\n" "$table"
      printf 'CREATE TABLE "%s" (%s);\n' "$table" "$(join_by ', ' "${col_defs[@]}")"
    } >>"$sql_file"

    local ctl_file="${WORK_ROOT}/${DATASET_SLUG}_${table}.ctl"
    local log_file="${WORK_ROOT}/${DATASET_SLUG}_${table}.log"
    local bad_file="${WORK_ROOT}/${DATASET_SLUG}_${table}.bad"
    cat >"$ctl_file" <<EOF
LOAD DATA
INFILE '$(escape_sql_single_quotes "$csv")'
APPEND
INTO TABLE "${table}"
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
TRAILING NULLCOLS
(
$(printf '  %s,\n' "${col_list[@]}" | sed '$ s/,$//')
)
EOF

    sqlplus -s "$conn" @"$sql_file" >/dev/null
    : >"$sql_file"
    sqlldr userid="$conn" control="$ctl_file" skip=1 log="$log_file" bad="$bad_file" errors=100000
  done < <(collect_csv_files "$dataset_dir")
}

run_dataset_import() {
  assert_config
  mkdir -p "$WORK_ROOT"
  case "$TARGET_ENGINE" in
    postgres)
      run_postgres_import
      ;;
    mysql)
      run_mysql_import
      ;;
    oracle)
      run_oracle_import
      ;;
    *)
      echo "Motor no soportado: $TARGET_ENGINE" >&2
      exit 1
      ;;
  esac
  log "Importacion finalizada para ${DATASET_SLUG} (${TARGET_ENGINE})."
}
