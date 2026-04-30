#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/aws_import_common.sh"

TARGET_ENGINE="postgres"
DATASET_ZIP="dbs/Airline+Loyalty+Program.zip"
DATASET_SLUG="airline_loyalty_program"
TABLE_PREFIX="airline_loyalty"

run_dataset_import
