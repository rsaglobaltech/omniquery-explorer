#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/aws_import_common.sh"

TARGET_ENGINE="postgres"
DATASET_ZIP="dbs/Bank+Customer+Churn.zip"
DATASET_SLUG="bank_customer_churn"
TABLE_PREFIX="bank_churn"

run_dataset_import
