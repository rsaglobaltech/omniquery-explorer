#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/aws_import_common.sh"

TARGET_ENGINE="mysql"
DATASET_ZIP="dbs/Maven+Fuzzy+Factory.zip"
DATASET_SLUG="maven_fuzzy_factory"
TABLE_PREFIX="maven_fuzzy"

run_dataset_import
