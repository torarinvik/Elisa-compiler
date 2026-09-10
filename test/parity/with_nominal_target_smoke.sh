#!/usr/bin/env bash
# `with T{...}` is a typed reference binding. Nominally distinct structs with the same
# layout must not be interchangeable: accepting the mismatch would let a generated binding
# carry the wrong type through the update body and is a soundness bug.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
[[ -x "$STAGE1" ]] || { echo "with nominal target smoke SKIP: no stage1 product"; exit 0; }

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/elisa-with-nominal.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

reject_case() {
    local label="$1" compiler="$2" source="$3" log="$TMP_DIR/$1.log"
    if "$compiler" -emit obj -o "$TMP_DIR/$1.o" "$source" >"$log" 2>&1; then
        echo "with nominal target smoke FAIL: $label accepted a mismatched typed with" >&2
        cat "$log" >&2
        return 1
    fi
    grep -Eq 'expects (mutable )?Other(&)?, got (static mutable )?Point(&)?' "$log" || {
        echo "with nominal target smoke FAIL: $label rejected for the wrong reason" >&2
        cat "$log" >&2
        return 1
    }
}

accept_case() {
    local label="$1" compiler="$2" source="$3"
    "$compiler" -emit obj -o "$TMP_DIR/$1.o" "$source" >"$TMP_DIR/$1.log" 2>&1 || {
        echo "with nominal target smoke FAIL: $label rejected a matching typed with" >&2
        cat "$TMP_DIR/$1.log" >&2
        return 1
    }
}

BAD="$REPO_ROOT/test/parity/fixtures/with_nominal_target_mismatch.elisa"
GOOD="$REPO_ROOT/test/parity/fixtures/with_nominal_target_match.elisa"
reject_case stage0 "$ELISACORE_BIN" "$BAD" || exit 1
reject_case stage1 "$STAGE1" "$BAD" || exit 1
accept_case stage0_good "$ELISACORE_BIN" "$GOOD" || exit 1
accept_case stage1_good "$STAGE1" "$GOOD" || exit 1

echo "with nominal target smoke OK: stage0/stage1 reject mismatched typed with and accept matching typed with"
