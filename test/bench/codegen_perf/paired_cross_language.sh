#!/usr/bin/env bash
# Paired Stage1 compiler A/B driver with one host lock held across every run.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if (( $# < 4 || $# > 5 )); then
  echo "usage: paired_cross_language.sh REFERENCE_STAGE1 REFERENCE_SOURCE_ROOT CANDIDATE_STAGE1 CANDIDATE_SOURCE_ROOT [OUTPUT_DIR]" >&2
  exit 2
fi
exec python3 "$SCRIPT_DIR/paired_runner.py" "$@"
