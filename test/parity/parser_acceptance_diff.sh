#!/usr/bin/env bash
# Differentially replay every source exercised through stage0's parser test
# helpers and require stage1 to make the same accept/reject decision.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
ORACLE_DIR="$ELISA_CORE/compiler"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ORACLE="$WORK/oracle.tsv"
MISMATCHES="$WORK/mismatches.tsv"

export ELISA_CORE
export REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

(cd "$ORACLE_DIR" && ELISA_PARSER_PARITY_OUT="$ORACLE" go test ./src/parser -count=1 >/dev/null)
case_count="$(wc -l < "$ORACLE" | tr -d ' ')"
[[ "$case_count" -gt 0 ]] || {
    echo "parser acceptance diff FAILED: stage0 emitted no oracle cases" >&2
    exit 1
}

while IFS=$'\t' read -r name expected_errors notices encoded; do
    out="$(printf '%s' "$encoded" | openssl base64 -d -A | "$RPT")"
    actual_errors="$(printf '%s\n' "$out" | awk '$1 == "P" { print $2; exit }')"
    [[ -n "$actual_errors" ]] || actual_errors=999999
    expected_class=0
    actual_class=0
    [[ "$expected_errors" -gt 0 ]] && expected_class=1
    [[ "$actual_errors" -gt 0 ]] && actual_class=1
    if [[ "$expected_class" != "$actual_class" ]]; then
        printf '%s\t%s\t%s\t%s\n' "$name" "$expected_errors" "$actual_errors" "$encoded" >> "$MISMATCHES"
    fi
done < "$ORACLE"

mismatch_count=0
[[ -f "$MISMATCHES" ]] && mismatch_count="$(wc -l < "$MISMATCHES" | tr -d ' ')"
if [[ "$mismatch_count" -ne 0 ]]; then
    echo "parser acceptance diff FAILED: $mismatch_count/$case_count stage0 cases disagree" >&2
    cut -f1-3 "$MISMATCHES" >&2
    exit 1
fi

echo "parser acceptance diff OK: $case_count/$case_count stage0 cases agree" >&2
