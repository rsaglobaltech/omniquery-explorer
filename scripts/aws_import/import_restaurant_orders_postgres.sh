#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/aws_import_common.sh"

TARGET_ENGINE="postgres"
DATASET_ZIP="dbs/Restaurant_Orders.zip"
DATASET_SLUG="restaurant_orders"
TABLE_PREFIX="restaurant_orders"

run_dataset_import
