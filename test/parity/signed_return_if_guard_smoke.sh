#!/usr/bin/env bash
# Stage0/stage1 parity for a signed postfix return guard. The expression parser
# may consume `if` while parsing `-1`; both products must still accept the guard.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
STAGE1="$REPO_ROOT/scripts/elisac_stage1.sh"
FIXTURE="$REPO_ROOT/test/repro/signed_return_if_guard.elisa"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

"$STAGE0" -emit header -o "$TMP_DIR/stage0.h" "$FIXTURE" >"$TMP_DIR/stage0.log" 2>&1
"$STAGE1" -emit header -o "$TMP_DIR/stage1.h" "$FIXTURE" >"$TMP_DIR/stage1.log" 2>&1

test -s "$TMP_DIR/stage0.h"
test -s "$TMP_DIR/stage1.h"
echo "signed-return-if-guard smoke OK: stage0 and stage1 accept the same guarded return"
