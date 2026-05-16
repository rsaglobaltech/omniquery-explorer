#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run-profile.sh
#   ./run-profile.sh --top 10

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run-common.sh"
omniquery_run profile "$@"
