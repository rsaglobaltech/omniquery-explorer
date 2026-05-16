#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run-suggest.sh

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run-common.sh"
omniquery_run suggest "$@"
