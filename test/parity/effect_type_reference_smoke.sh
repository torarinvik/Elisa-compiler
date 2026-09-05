#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
if [[ ! -x "$STAGE1" || ! -f "$RUNTIME" || ! -x "$CLANG" ]]; then
    echo "effect type reference smoke SKIP: local compiler/runtime/clang unavailable"
    exit 0
fi
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-effect-types.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ELISA_STAGE1_BIN="$STAGE1" bash "$ROOT/scripts/elisac_stage1.sh" -O0 -emit obj \
    -o "$WORK/check.o" "$ROOT/test/breadth/effect_type_reference.elisa" \
    >"$WORK/build.log" 2>&1 || {
    sed -n '1,100p' "$WORK/build.log" >&2
    exit 1
}
if [[ "$(uname -s)" == Darwin ]]; then
    "$CLANG" -Wl,-dead_strip "$WORK/check.o" "$RUNTIME" -o "$WORK/check"
else
    "$CLANG" "$WORK/check.o" "$RUNTIME" -o "$WORK/check"
fi
actual=0
"$WORK/check" || actual=$?
[[ "$actual" == 42 ]] || {
    echo "effect type reference smoke FAIL: parser structure check returned $actual" >&2
    exit 1
}
echo "effect type reference smoke OK: generic, nested, reference and via row types survive parsing"
