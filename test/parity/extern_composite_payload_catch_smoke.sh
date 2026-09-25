#!/usr/bin/env bash
# Preserve the Stage0 LLVM-signature characterization and run Stage1 against the real C ABI.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
LLVM_BIN="$(dirname -- "$LLVM_CONFIG")"
OPT="${ELISA_OPT:-$LLVM_BIN/opt}"
CLANG="${ELISA_CLANG:-$LLVM_BIN/clang}"
FIXTURE="$ROOT/test/repro/extern_multi_family_payload.elisa"
STUB="$ROOT/test/repro/extern_multi_family_payload_stub.ll"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-extern-composite-catch.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
[[ -x "$OPT" ]] || { echo "extern composite catch smoke: missing opt: $OPT" >&2; exit 2; }
[[ -x "$CLANG" ]] || { echo "extern composite catch smoke: missing clang: $CLANG" >&2; exit 2; }
"$OPT" -passes=verify -disable-output "$STUB"

for level in 0 2; do
    llvm="$WORK/stage0-O${level}.ll"
    "$STAGE0" -emit llvm "-O$level" -o "$llvm" "$FIXTURE"
    "$OPT" -passes=verify -disable-output "$llvm"
    DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
        "$CLANG" "-O$level" -Wno-override-module -o "$WORK/stage0-O$level" "$llvm" "$STUB"

    set +e
    "$WORK/stage0-O$level"
    stage0_result=$?
    set -e
    if [[ "$stage0_result" -ne 42 ]]; then
        echo "extern composite catch smoke FAILED at -O$level: Stage0=$stage0_result expected=42" >&2
        exit 1
    fi
done

bash "$ROOT/test/parity/extern_composite_payload_c_abi_smoke.sh"

echo "extern composite payload catch smoke OK: Stage0 LLVM stub baseline and Stage1 native C ABI pass at -O0 and -O2"
