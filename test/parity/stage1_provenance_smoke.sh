#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"

python3 "$REPO_ROOT/scripts/test_stage1_provenance.py"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$REPO_ROOT/bin/elisac-stage1"
echo "stage1 provenance smoke OK"
