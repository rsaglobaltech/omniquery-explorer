#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# OmniQuery Explorer — shared run config
# ---------------------------------------------------------------------------

# Conexiones locales en Docker (descomenta una para probar):
# MySQL datasets
# export DATABASE_URL="mysql+aiomysql://admin:Server2026@127.0.0.1:3307/airline_passenger_satisfaction_db"
# export DATABASE_URL="mysql+aiomysql://admin:Server2026@127.0.0.1:3307/maven_fuzzy_factory_db"
# export DATABASE_URL="mysql+aiomysql://admin:Server2026@127.0.0.1:3307/videos_subcriptions_db"
# export DATABASE_URL="mysql+aiomysql://admin:Server2026@127.0.0.1:3307/uk_train_rides_db"
#
# PostgreSQL datasets
# export DATABASE_URL="postgresql+asyncpg://admin:Server2026@127.0.0.1:5433/airline_loyalty_program_db"
# export DATABASE_URL="postgresql+asyncpg://admin:Server2026@127.0.0.1:5433/bank_customer_churn_db"
# export DATABASE_URL="postgresql+asyncpg://admin:Server2026@127.0.0.1:5433/hospital_patient_records_db"
# export DATABASE_URL="postgresql+asyncpg://admin:Server2026@127.0.0.1:5433/restaurant_orders_db"

# Valor por defecto (puede sobrescribirse desde tu entorno)
#export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://admin:Server2026@127.0.0.1:5433/restaurant_orders_db}"
export DATABASE_URL="mysql+aiomysql://admin:Server2026@127.0.0.1:3307/videos_subcriptions_db"
export OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.2:latest}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"

# Logging / observabilidad de agentes
export OMNIQUERY_LOG_LEVEL="${OMNIQUERY_LOG_LEVEL:-INFO}"
export OMNIQUERY_LOG_FORMAT="${OMNIQUERY_LOG_FORMAT:-json}"
export OMNIQUERY_LOG_AGENT="${OMNIQUERY_LOG_AGENT:-}"
export OMNIQUERY_LOG_PAYLOAD_CHARS="${OMNIQUERY_LOG_PAYLOAD_CHARS:-1200}"
export OMNIQUERY_LOG_DIR="${OMNIQUERY_LOG_DIR:-.logs}"
# Si no defines OMNIQUERY_LOG_FILE, se usa omniquery-YYYY-MM-DD.logs automáticamente.
export OMNIQUERY_LOG_FILE="${OMNIQUERY_LOG_FILE:-}"

omniquery_run() {
  uv run omniquery "$@"
}
