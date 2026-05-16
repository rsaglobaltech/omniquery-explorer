#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run-ask.sh "How many species are there?"

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run-common.sh"

if [[ $# -lt 1 ]]; then
  echo "Usage: ./run-ask.sh \"<question>\""
  exit 1
fi

omniquery_run ask "$@"
