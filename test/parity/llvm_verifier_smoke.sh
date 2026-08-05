#!/usr/bin/env bash
# The emitted module must be VALID LLVM IR — `opt -passes=verify` clean, for every repro
# fixture.
#
# This exists because the object path TOLERATES invalid IR. Three separate malformed-IR
# classes rode along in every std-including program for as long as anyone had looked:
#
#   call @snprintf(i8 %elem, …)          where the declaration says `ptr`
#   zext ptr @handler to i64             an invalid cast opcode (stage0 emits ptrtoint)
#   ret %Task__opt0__unknown             from a function declared `%Task__i64__unknown`
#
# None of them changed an answer at -O0, so the differential corpus was silent; the first
# symptom was the -O1/-O2 pass pipeline dying with SIGBUS on one fixture. A verifier run is
# the direct check, and it is cheap: `-emit llvm` plus one `opt` per fixture.
#
# Fixtures that INCLUDE the std are the interesting ones (the std is where the malformed IR
# lived), so they are not skipped — this smoke reads includes exactly as the compiler does.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
OPT="$(dirname "$LLVM_CONFIG")/opt"

[ -x "$STAGE1" ]   || { echo "llvm_verifier_smoke SKIP: no stage1 seed at $STAGE1"; exit 0; }
[ -x "$OPT" ]      || { echo "llvm_verifier_smoke SKIP: no llvm opt at $OPT"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

checked=0
failed=0
for src in "$ROOT"/test/repro/*.elisa; do
    name="$(basename "$src" .elisa)"
    if ! bash "$ROOT/scripts/elisac_stage1.sh" -emit llvm -o "$WORK/$name.ll" "$src" >/dev/null 2>&1; then
        # A fixture stage1 declines is not this smoke's business — the decline census owns that.
        continue
    fi
    checked=$((checked + 1))
    if ! "$OPT" -passes=verify -disable-output "$WORK/$name.ll" >"$WORK/$name.err" 2>&1; then
        echo "  FAIL $name: emitted module is not valid LLVM IR"
        grep -vE '^\s*$' "$WORK/$name.err" | head -3 | sed 's/^/       /'
        failed=$((failed + 1))
    fi
done

if [ "$failed" -ne 0 ]; then
    echo "llvm_verifier FAILED: $failed of $checked emitted modules are invalid"
    exit 1
fi
echo "llvm_verifier OK: $checked emitted modules are valid LLVM IR"
