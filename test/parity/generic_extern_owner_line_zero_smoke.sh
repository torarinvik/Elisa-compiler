#!/usr/bin/env bash
# Same-logical-line generic extern declarations must retain distinct owner pairs.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/repro/generic_extern_owner_line_zero.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

python3 "$ROOT/test/proofs/check_generic_extern_owner_identity.py"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
"$STAGE1" -emit llvm -o "$WORK/generic_extern_owner.ll" "$FIXTURE" >"$WORK/compiler.log" 2>&1 || {
    cat "$WORK/compiler.log" >&2
    echo "generic extern owner smoke FAIL: stage1 declined the line-zero fixture" >&2
    exit 1
}

grep -Fq 'declare void @first_record__i64(ptr, i64)' "$WORK/generic_extern_owner.ll" || {
    echo "generic extern owner smoke FAIL: first declaration did not emit its i64 specialization" >&2
    exit 1
}
grep -Fq 'declare void @second_record__i64(ptr, i64)' "$WORK/generic_extern_owner.ll" || {
    echo "generic extern owner smoke FAIL: second declaration did not emit its i64 specialization" >&2
    exit 1
}

echo "generic extern same-line owner smoke OK"
