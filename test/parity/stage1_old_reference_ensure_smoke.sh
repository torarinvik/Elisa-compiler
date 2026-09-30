#!/usr/bin/env bash
# Stage1 runtime ensure lowering for `old(reference[0])`: capture once at entry,
# preserve the reference on the exhausted path, and expose the successor on success.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
SOURCE="$ROOT/test/parity/fixtures/stage1_old_reference_ensure.elisa"
UNSAFE_SOURCE="$ROOT/test/parity/fixtures/stage1_old_effectful_snapshot_declines.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
"$STAGE1" -emit exe -O0 -o "$WORK/program" "$SOURCE" >"$WORK/build.log" 2>&1 || {
    cat "$WORK/build.log" >&2
    echo "stage1 old-reference ensure smoke: compile failed" >&2
    exit 1
}
"$WORK/program" >"$WORK/stdout" 2>"$WORK/stderr" || {
    status=$?
    cat "$WORK/stdout" "$WORK/stderr" >&2
    echo "stage1 old-reference ensure smoke: program exited $status" >&2
    exit 1
}

if "$STAGE1" -emit obj -O0 -o "$WORK/unsafe.o" "$UNSAFE_SOURCE" >"$WORK/unsafe.log" 2>&1; then
    echo "stage1 old-reference ensure smoke: entry-time user call was accepted" >&2
    exit 1
fi
if ! rg -q "old-value postcondition snapshot expression" "$WORK/unsafe.log"; then
    cat "$WORK/unsafe.log" >&2
    echo "stage1 old-reference ensure smoke: unsafe snapshot did not fail at the safety gate" >&2
    exit 1
fi

echo "stage1 old-reference ensure smoke OK: entry snapshots, success value, and exhaustion frame"
