#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/aws_import_common.sh"

TARGET_ENGINE="postgres"
DATASET_ZIP="dbs/Hospital+Patient+Records.zip"
DATASET_SLUG="hospital_patient_records"
TABLE_PREFIX="hospital_records"

run_dataset_import
