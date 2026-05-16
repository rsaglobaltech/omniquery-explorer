#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run-explore.sh
#   ./run-explore.sh --question "Which segment has most churn?"

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run-common.sh"
omniquery_run explore "$@"
