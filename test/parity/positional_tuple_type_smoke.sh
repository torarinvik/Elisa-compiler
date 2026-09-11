#!/usr/bin/env bash
# Type annotations use named tuple fields. Both compiler generations must reject a
# positional tuple at the parser boundary, including in struct fields and aliases.
set -uo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/structpy-tree}"
source "$ROOT/test/parity/resolve_elisac.sh"

fail() { echo "positional tuple type smoke FAIL: $1" >&2; exit 1; }
SOURCE="$ROOT/test/repro/positional_tuple_type.elisa"
STAGE1_BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
[ -x "$STAGE1_BIN" ] || fail "missing stage1 product at $STAGE1_BIN"

check_rejected() {
    local label="$1"
    shift
    local output status
    if output=$("$@" -emit interpret "$SOURCE" 2>&1); then
        status=0
    else
        status=$?
    fi
    [ "$status" -ne 0 ] || fail "$label accepted positional tuple type"
    printf '%s\n' "$output" | grep -q "expected :, got ," || fail "$label lost the tuple-type diagnostic"
    [ "$(printf '%s\n' "$output" | grep -c "expected :, got ,")" -ge 2 ] || fail "$label missed one tuple-type diagnostic"
}

check_rejected stage0 "$ELISACORE_BIN"
check_rejected stage1 "$STAGE1_BIN"
echo "positional tuple type smoke OK: stage0 and stage1 reject struct-field and alias forms"
