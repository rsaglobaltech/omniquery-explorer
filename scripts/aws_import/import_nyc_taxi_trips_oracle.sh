#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/aws_import_common.sh"

TARGET_ENGINE="oracle"
DATASET_ZIP="dbs/NYC_Taxi_Trips.zip"
DATASET_SLUG="nyc_taxi_trips"
TABLE_PREFIX="nyc_taxi"

run_dataset_import
