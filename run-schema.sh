#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run-schema.sh

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run-common.sh"
omniquery_run schema "$@"
