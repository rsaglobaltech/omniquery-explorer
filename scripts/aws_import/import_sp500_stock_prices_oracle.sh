#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/aws_import_common.sh"

TARGET_ENGINE="oracle"
DATASET_ZIP="dbs/S&P+500+Stock+Prices+2014-2017.csv.zip"
DATASET_SLUG="sp500_stock_prices"
TABLE_PREFIX="sp500_prices"

run_dataset_import
