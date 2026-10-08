#!/usr/bin/env bash
# Stage1-only: contract annotations must not replace declared error families.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-contract-try.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
"$STAGE1" -emit obj -O0 -o "$WORK/positive.o" "$ROOT/test/repro/contract_try_error_family.elisa" >"$WORK/positive.log" 2>&1
if "$STAGE1" -emit obj -O0 -o "$WORK/negative.o" "$ROOT/test/repro/contract_try_error_family_rejected.elisa" >"$WORK/negative.log" 2>&1; then
    echo "contract try smoke FAIL: incompatible destination accepted" >&2
    exit 1
fi
rg -q 'cannot propagate Failure from a function returning OtherFailure' "$WORK/negative.log"
if rg -q 'cannot propagate __' "$WORK/negative.log"; then
    cat "$WORK/negative.log" >&2
    exit 1
fi
"$STAGE1" -emit obj -O0 -o "$WORK/modules.o" "$ROOT/test/repro/module_local_try_error_family.elisa" >"$WORK/modules.log" 2>&1
if "$STAGE1" -emit obj -O0 -o "$WORK/cross-module.o" "$ROOT/test/fixtures/diagnostics/try_propagation_module_scope.pos.elisa" >"$WORK/cross-module.log" 2>&1; then
    echo "contract try smoke FAIL: incompatible module family accepted" >&2
    exit 1
fi
rg -q 'cannot propagate AErr from a function returning BErr' "$WORK/cross-module.log"
echo "contract try error-family smoke OK"
