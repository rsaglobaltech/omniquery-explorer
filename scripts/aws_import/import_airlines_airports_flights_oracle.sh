#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/aws_import_common.sh"

TARGET_ENGINE="oracle"
DATASET_ZIP="dbs/Airlines+Airports+Cancellation+Codes+&+Flights.zip"
DATASET_SLUG="airlines_airports_flights"
TABLE_PREFIX="airlines_flights"

run_dataset_import
