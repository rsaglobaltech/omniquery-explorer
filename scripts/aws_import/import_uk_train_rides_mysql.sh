#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/aws_import_common.sh"

TARGET_ENGINE="mysql"
DATASET_ZIP="dbs/UK+Train+Rides.zip"
DATASET_SLUG="uk_train_rides"
TABLE_PREFIX="uk_train"

run_dataset_import
