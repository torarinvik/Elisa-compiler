#!/usr/bin/env bash
# A module-local bare call must not inherit a same-named sibling module's signature.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
SOURCE="$ROOT/test/repro/qualified_firm_argument_collision.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/qualified-firm-args.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

compile_and_check() {
    local label="$1" compiler="$2" execute="$3" object="$WORK/$1.o" executable="$WORK/$1"
    "$compiler" -emit obj -O0 -o "$object" "$SOURCE" >"$WORK/$label.log" 2>&1 || {
        cat "$WORK/$label.log" >&2
        echo "qualified firm-argument smoke FAIL: $label did not compile" >&2
        exit 1
    }
    [[ "$execute" == 1 ]] || {
        echo "  $label: module-local call passed compilation"
        return
    }
    cc "$object" -o "$executable" >"$WORK/$label-link.log" 2>&1 || {
        cat "$WORK/$label-link.log" >&2
        echo "qualified firm-argument smoke FAIL: $label did not link" >&2
        exit 1
    }
    local status=0
    "$executable" || status=$?
    [[ "$status" -eq 42 ]] || {
        echo "qualified firm-argument smoke FAIL: $label returned $status, expected 42" >&2
        exit 1
    }
    echo "  $label: module-local call returned 42"
}

[[ -x "${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}" ]] || {
    echo "qualified firm-argument smoke FAIL: stage1 compiler unavailable" >&2
    exit 1
}
[[ -x "$STAGE0" ]] || {
    echo "qualified firm-argument smoke FAIL: stage0 compiler unavailable: $STAGE0" >&2
    exit 1
}
compile_and_check stage1 "$STAGE1" 1
compile_and_check stage0 "$STAGE0" 0
echo "qualified firm-argument smoke OK"
