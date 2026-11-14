#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/scripts/platform.sh"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
"$ELISA_TOOL_PYTHON" "$ROOT/test/proofs/check_pointer_erasure_generic_owner_identity.py"
"$ELISA_TOOL_PYTHON" "$ROOT/test/parity/generic_cast_smoke.py"
