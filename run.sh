#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# OmniQuery Explorer — run script
# Usage:
#   ./run.sh ask "How many species are there?"
#   ./run.sh suggest
#   ./run.sh profile
#   ./run.sh explore "How many species are there?"
#   ./run.sh schema
# ---------------------------------------------------------------------------

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run-common.sh"
omniquery_run "$@"
