#!/usr/bin/env bash
# Stage0 rejects passing a mutable aggregate local to a by-value aggregate parameter.
# Keep Stage1 aligned: accepting it lets the invalid mutable-reference-to-value conversion
# reach code generation and was the exact acceptance gap found by the syllogism port.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
SOURCE="$ROOT/test/repro/mutable_aggregate_to_value.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/mutable-aggregate-value.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

check_rejected() {
    local label="$1" compiler="$2" log="$WORK/$1.log" status=0
    "$compiler" -emit obj -O0 -o "$WORK/$label.o" "$SOURCE" >"$log" 2>&1 || status=$?
    if [[ "$status" -eq 0 ]]; then
        echo "mutable aggregate-to-value smoke FAIL: $label accepted invalid conversion" >&2
        exit 1
    fi
    grep -q 'candidate' "$log" || {
        cat "$log" >&2
        echo "mutable aggregate-to-value smoke FAIL: $label lost the candidate diagnostic" >&2
        exit 1
    }
    echo "  $label: rejected mutable Grade -> Grade"
}

check_rejected stage0 "$STAGE0"
check_rejected stage1 "$STAGE1"
echo "mutable aggregate-to-value smoke OK"
