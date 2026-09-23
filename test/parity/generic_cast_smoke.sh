#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
python3 "$ROOT/test/parity/generic_cast_smoke.py"
