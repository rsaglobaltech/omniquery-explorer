#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# OmniQuery Explorer — run script
# Usage:
#   ./run.sh ask   "How many species are there?"
#   ./run.sh suggest
#   ./run.sh profile
#   ./run.sh explore  "How many species are there?"
#   ./run.sh schema
# ---------------------------------------------------------------------------

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://reader:NWDMCE5xdipIjRrp@hh-pgsql-public.ebi.ac.uk:5432/pfmegrnargs}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.2:latest}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"

uv run omniquery "$@"
