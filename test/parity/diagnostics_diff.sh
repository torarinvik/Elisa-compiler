#!/usr/bin/env bash
# Differential diagnostic oracle: compare stage0's semantic diagnostics with stage1's
# machine-readable reporter over standalone fixtures. Stage1 may add sound supplemental
# diagnostics (for example unused-name warnings), so the oracle requires every stage0
# message to be represented by a stage1 message, but does not require equal counts.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
FIXTURES="${DIAGNOSTIC_DIFF_FIXTURES:-$REPO_ROOT/test/fixtures/diagnostics}"

source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

normalize() {
    sed -E \
        -e 's/^[^:]*:[0-9]+:[0-9]+(-[0-9]+(:[0-9]+)?)?:[[:space:]]*//' \
        -e 's/^  L[0-9]+[[:space:]]*//' \
        -e 's/[^[:alnum:]_]+/ /g' \
        -e 's/[[:space:]]+/ /g' \
        -e 's/^ //' -e 's/ $//' \
        | tr '[:upper:]' '[:lower:]'
}

stage1_messages() {
    "$REPO_ROOT/build/parse_report" < "$1" \
        | awk '/^D [0-9]+$/{in_diag=1; next} in_diag && /^  L[0-9]+ /{sub(/^  L[0-9]+ /, ""); print}' \
        | normalize
}

stage0_messages() {
    local err status
    err="$(mktemp)"
    "$ELISACORE_BIN" -emit semantic "$1" >/dev/null 2>"$err"
    status=$?
    if [ "$status" -ne 0 ] || [ -s "$err" ]; then
        grep -E ':[0-9]+:[0-9]+' "$err" | normalize
    fi
    rm -f "$err"
    return 0
}

failed=0
checked=0
for fixture in "$FIXTURES"/*.elisa; do
    [ -f "$fixture" ] || continue
    checked=$((checked + 1))
    s0="$(stage0_messages "$fixture")"
    s1="$(stage1_messages "$fixture")"
    while IFS= read -r expected; do
        [ -n "$expected" ] || continue
        found=0
        while IFS= read -r actual; do
            [ "$actual" = "$expected" ] && found=1
        done <<EOF
$s1
EOF
        if [ "$found" -eq 0 ]; then
            printf 'diagnostic mismatch: %s\nstage0: %s\nstage1: %s\n' \
                "${fixture#"$REPO_ROOT"/}" "$expected" "${s1//$'\n'/ | }" >&2
            failed=$((failed + 1))
        fi
    done <<EOF
$s0
EOF
done

if [ "$failed" -ne 0 ]; then
    echo "diagnostics diff FAILED: $failed stage0 diagnostic(s) missing or changed" >&2
    exit 1
fi
echo "diagnostics diff OK: $checked fixtures, all stage0 diagnostics represented by stage1"
