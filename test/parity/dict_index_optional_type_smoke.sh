#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_ROOT="$ROOT"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$ROOT/test/parity/build_parse_report.sh"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-dict-index-type.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

invalid="$ROOT/test/parity/fixtures/rejected_dict_index_value.elisa"
if "$STAGE1" -emit obj -O0 -o "$WORK/invalid.o" "$invalid" >"$WORK/invalid.log" 2>&1; then
    echo "dictionary index type smoke: nullable dictionary reference was accepted as a value" >&2
    exit 1
fi
rg -Fq 'optional reference to dictionary value' "$WORK/invalid.log" || {
    echo "dictionary index type smoke: rejection did not identify the fallible dictionary lookup" >&2
    cat "$WORK/invalid.log" >&2
    exit 1
}

valid="$ROOT/test/parity/fixtures/dict_index_get_else.elisa"
valid_report="$("$RPT" < "$valid" 2>&1)"
if ! grep -qE '^P 0$' <<< "$valid_report" || rg -Fq 'optional reference to dictionary value' <<< "$valid_report"; then
    echo "dictionary index type smoke: explicit get-else unwrap failed semantic validation" >&2
    printf '%s\n' "$valid_report" >&2
    exit 1
fi

echo "dictionary index type smoke OK: direct nullable-reference value is rejected; explicit unwrap stays semantically valid"
