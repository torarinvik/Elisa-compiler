#!/usr/bin/env bash
# Optional payload values must be narrowed into a payload binding before a
# required-reference call; an optional reference itself requires a live null proof.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
OPT="$ELISA_LLVM_BIN_DIR/opt"
NEGATIVE="$ROOT/test/repro/optional_struct_global_ref_unchecked.elisa"
POSITIVE="$ROOT/test/parity/fixtures/optional_struct_global_ref_payload.elisa"

bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[ -x "$OPT" ] || { echo "optional_payload_ref_argument_smoke SKIP: no LLVM opt at $OPT"; exit 0; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-optional-payload-ref.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

if "$STAGE1" -emit llvm -o "$WORK/unsafe.ll" "$NEGATIVE" >"$WORK/unsafe.log" 2>&1; then
    echo "optional payload/ref smoke FAIL: unguarded optional-to-reference call compiled" >&2
    exit 1
fi
if [[ -e "$WORK/unsafe.ll" ]]; then
    echo "optional payload/ref smoke FAIL: rejected call still wrote LLVM" >&2
    exit 1
fi

"$STAGE1" -emit llvm -o "$WORK/payload.ll" "$POSITIVE" >"$WORK/payload.log" 2>&1
"$OPT" -passes=verify -disable-output "$WORK/payload.ll"
rg -q 'call i64 @read_ledger\(ptr %present\)' "$WORK/payload.ll" || {
    echo "optional payload/ref smoke FAIL: guarded binder was not borrowed by address" >&2
    exit 1
}
rg -q 'call i64 @read_ledger\(ptr %unwrap\.opt\)' "$WORK/payload.ll" || {
    echo "optional payload/ref smoke FAIL: narrowed optional reference lost its payload pointer" >&2
    exit 1
}
rg -q 'call i64 @borrow_optional_cell\(ptr @ledger\)' "$WORK/payload.ll" || {
    echo "optional payload/ref smoke FAIL: reference-to-optional did not borrow container storage" >&2
    exit 1
}

echo "optional payload/ref smoke OK: unsafe optional rejected; guarded payload and aliasing reference LLVM verify"
