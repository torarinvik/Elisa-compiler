#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$BIN"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/native-host-link.XXXXXX")"
finish() {
    local status=$?
    if [[ "$status" -eq 0 ]]; then
        rm -rf -- "$WORK"
    else
        echo "native host linking failed (status=$status); logs retained at $WORK" >&2
    fi
    exit "$status"
}
trap finish EXIT
mkdir "$WORK/path with spaces"
cp "$ROOT/test/repro/native_host_link.elisa" "$WORK/path with spaces/source.elisa"
export ELISA_RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
"$BIN" -emit exe -O2 -o "$WORK/path with spaces/program" "$WORK/path with spaces/source.elisa" >"$WORK/compile.out" 2>"$WORK/compile.err"
test -x "$WORK/path with spaces/program"
status=0
"$WORK/path with spaces/program" || status=$?
test "$status" -eq 23
"$BIN" -emit interpret "$WORK/path with spaces/source.elisa" >"$WORK/interpret.out" 2>"$WORK/interpret.err"
grep -Eq '\[ result[[:space:]]*\][[:space:]]*23' "$WORK/interpret.out"
if grep -Eq 'unable to disambiguate|linker command failed|unknown argument' "$WORK/compile.err" "$WORK/interpret.err"; then
    echo 'native host linking emitted a linker failure' >&2
    exit 1
fi
# A real override must be invoked in every mode, including a space in its path.
export ELISA_NATIVE_LINK_REAL_CLANG="${ELISA_CLANG:-$(command -v clang)}"
export ELISA_NATIVE_LINK_MARKER="$WORK/selected-driver.marker"
cp "$ROOT/test/repro/native_host_link_driver.sh" "$WORK/path with spaces/selected clang"
chmod +x "$WORK/path with spaces/selected clang"
ELISA_CLANG="$WORK/path with spaces/selected clang" "$BIN" -emit exe -o "$WORK/selected-program" "$WORK/path with spaces/source.elisa" >"$WORK/selected-exe.out" 2>"$WORK/selected-exe.err"
test -s "$ELISA_NATIVE_LINK_MARKER"
status=0
"$WORK/selected-program" || status=$?
test "$status" -eq 23
: > "$ELISA_NATIVE_LINK_MARKER"
ELISA_CLANG="$WORK/path with spaces/selected clang" "$BIN" -emit interpret "$WORK/path with spaces/source.elisa" >"$WORK/selected-interpret.out" 2>"$WORK/selected-interpret.err"
test -s "$ELISA_NATIVE_LINK_MARKER"
grep -Eq '\[ result[[:space:]]*\][[:space:]]*23' "$WORK/selected-interpret.out"
cp "$ROOT/test/repro/native_host_link_tests.elisa" "$WORK/path with spaces/tests.elisa"
: > "$ELISA_NATIVE_LINK_MARKER"
ELISA_CLANG="$WORK/path with spaces/selected clang" "$BIN" -emit test "$WORK/path with spaces/tests.elisa" >"$WORK/selected-test.out" 2>"$WORK/selected-test.err"
test -s "$ELISA_NATIVE_LINK_MARKER"
grep -Eq '\[ SUMMARY[[:space:]]*\] 1 test\(s\) selected; passed=1 skipped=0 failed=0' "$WORK/selected-test.out"
# No mode may silently fall back to PATH when the caller selected a linker.
if ELISA_CLANG="$WORK/missing clang" "$BIN" -emit exe -o "$WORK/must-not-exist" "$WORK/path with spaces/source.elisa" >"$WORK/missing-exe.out" 2>&1; then
    echo 'executable mode ignored the selected missing linker' >&2
    exit 1
fi
test ! -e "$WORK/must-not-exist"
if ELISA_CLANG="$WORK/missing clang" "$BIN" -emit interpret "$WORK/path with spaces/source.elisa" >"$WORK/missing-interpret.out" 2>&1; then
    echo 'interpreter mode ignored the selected missing linker' >&2
    exit 1
fi
if ELISA_CLANG="$WORK/missing clang" "$BIN" -emit test "$WORK/path with spaces/tests.elisa" >"$WORK/missing-test.out" 2>&1; then
    echo 'test mode ignored the selected missing linker' >&2
    exit 1
fi
echo 'native host linking: exe, interpret, and test honor the selected linker with space-containing paths'
