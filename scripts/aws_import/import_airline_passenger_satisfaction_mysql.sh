#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/aws_import_common.sh"

TARGET_ENGINE="mysql"
DATASET_ZIP="dbs/Airline+Passenger+Satisfaction.zip"
DATASET_SLUG="airline_passenger_satisfaction"
TABLE_PREFIX="airline_satisfaction"

run_dataset_import
