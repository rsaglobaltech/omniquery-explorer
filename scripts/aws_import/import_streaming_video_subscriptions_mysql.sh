#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/aws_import_common.sh"

TARGET_ENGINE="mysql"
DATASET_ZIP="dbs/Streaming+Video+Subscriptions.zip"
DATASET_SLUG="streaming_video_subscriptions"
TABLE_PREFIX="streaming_subs"

run_dataset_import
