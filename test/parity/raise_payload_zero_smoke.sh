#!/usr/bin/env bash
# A `raise` must zero the payload out-param with a zero OF THE PAYLOAD TYPE. stage1 stored an
# `i64 0` through the slot regardless of the payload, so a `bool`/`u8`/`i32 error[E]` callee
# wrote 8 bytes into the caller's narrower `call.error.out` alloca -- a stack smash that was
# harmless on macOS and segfaulted on Linux (adversarial try_operand_short_circuit and
# try_as_binary_operand, exit -11; reproduced by cross-emitting for aarch64-linux). The Mac
# cannot see the crash, so this smoke asserts the IR directly: the bool-payload raise path
# stores `i1 false`, never an `i64 0`, and both compilers' programs agree.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/repro/raise_narrow_payload_zero.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-raise-zero.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

"$STAGE0" -emit obj -O0 -o "$WORK/stage0.o" "$FIXTURE"
cc "$WORK/stage0.o" -o "$WORK/stage0"
"$STAGE1" -emit exe -O0 -o "$WORK/stage1" "$FIXTURE"
set +e
"$WORK/stage0"; rc0=$?
"$WORK/stage1"; rc1=$?
set -e
if [[ "$rc0" != "$rc1" ]]; then
    echo "raise_payload_zero FAIL: stage0 exited $rc0, stage1 exited $rc1" >&2
    exit 1
fi

"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$FIXTURE"
# The raising functions store through their payload out-param `%0`; the zero must have the
# payload's own width. An `i64 0` into the bool/u8/i32 slot is the bug.
flag_body="$(awk '/^define.*@flag\(/,/^}/' "$WORK/stage1.ll")"
if grep -q 'store i64 0, ptr %0' <<<"$flag_body"; then
    echo "raise_payload_zero FAIL: bool-payload raise stores an i64 zero through the out-param" >&2
    exit 1
fi
if ! grep -q 'store i1 false, ptr %0' <<<"$flag_body"; then
    echo "raise_payload_zero FAIL: bool-payload raise does not store an i1 zero" >&2
    exit 1
fi
for fn in small narrow; do
    body="$(awk "/^define.*@$fn\\(/,/^}/" "$WORK/stage1.ll")"
    if grep -q 'store i64 0, ptr %0' <<<"$body"; then
        echo "raise_payload_zero FAIL: $fn raise stores an i64 zero through a narrower out-param" >&2
        exit 1
    fi
done
echo "raise_payload_zero OK: exit $rc0 on both; raise zeroes carry the payload width"
