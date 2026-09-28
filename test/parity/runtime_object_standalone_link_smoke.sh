#!/usr/bin/env bash
# The installed runtime object links STANDALONE: `cc prog.o elisacore_runtime.o`, with no
# -dead_strip and none of the driver's generated shim files. It used to leave the
# native-callback family and va_copy/va_end undefined, so only links that went through the
# driver (weak shims + -dead_strip) or a stage0 harness (-dead_strip) worked.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
bash "$ROOT/scripts/build_runtime_object.sh" >/dev/null || exit $?
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-runtime-standalone.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

cat > "$WORK/p.elisa" <<'SRC'
def main() -> i64:
    xs: mutable darray[i64] = []
    for i in 0..<10 |xs|:
        xs.push(i)
    return xs[9]
SRC
"$STAGE1" -emit obj -O0 -o "$WORK/p.o" "$WORK/p.elisa" >/dev/null 2>&1 || { echo "runtime standalone link FAIL: stage1 did not compile the probe"; exit 1; }
"${ELISA_CLANG:-cc}" -o "$WORK/p" "$WORK/p.o" "$RUNTIME_OBJ" 2>"$WORK/link.err" || {
    echo "runtime standalone link FAIL:"; head -12 "$WORK/link.err"; exit 1; }
"$WORK/p"; status=$?
[[ "$status" == 9 ]] || { echo "runtime standalone link FAIL: exit $status, want 9"; exit 1; }
echo "runtime standalone link OK: prog.o + elisacore_runtime.o links with no shims and no dead-strip"
