#!/usr/bin/env bash
# Operation-specific unsafe capabilities must be lexical and must not leak across grants.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
python3 "$REPO_ROOT/test/proofs/check_strict_unsafe_generic_owner_identity.py"

python3 "$REPO_ROOT/test/parity/unsafe_grant_scope_cases.py" "$STAGE1" "$REPO_ROOT"
