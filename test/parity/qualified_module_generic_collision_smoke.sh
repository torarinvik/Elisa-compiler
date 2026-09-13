#!/usr/bin/env bash
# A qualified monomorphic module function wins over a same-named unrelated generic.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
SOURCE="$ROOT/test/repro/qualified_module_generic_collision.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/qualified-module-generic.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

compile_and_check() {
    local label="$1" compiler="$2" object="$WORK/$1.o" executable="$WORK/$1"
    "$compiler" -emit obj -O0 -o "$object" "$SOURCE" >"$WORK/$label.log" 2>&1 || {
        cat "$WORK/$label.log" >&2
        echo "qualified module generic smoke FAIL: $label did not compile" >&2
        exit 1
    }
    # This fixture is deliberately scalar-only; omitting the runtime keeps the
    # regression focused on qualified generic dispatch, without unrelated host
    # callback stubs from the shared runtime object.
    cc "$object" -o "$executable" >"$WORK/$label-link.log" 2>&1 || {
        cat "$WORK/$label-link.log" >&2
        echo "qualified module generic smoke FAIL: $label did not link" >&2
        exit 1
    }
    set +e
    "$executable"
    local status=$?
    set -e
    [[ "$status" -eq 42 ]] || {
        echo "qualified module generic smoke FAIL: $label returned $status, expected 42" >&2
        exit 1
    }
    echo "  $label: qualified module member returned 42"
}

[[ -x "${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}" ]] || { echo "qualified module generic smoke SKIP: no stage1 seed"; exit 0; }
compile_and_check stage1 "$STAGE1"
if [[ -x "$STAGE0" ]]; then
    compile_and_check stage0 "$STAGE0"
else
    echo "  stage0: SKIP (no compiler at $STAGE0)"
fi

echo "qualified module generic smoke OK"
