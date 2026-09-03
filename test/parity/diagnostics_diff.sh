#!/usr/bin/env bash
# Differential diagnostic oracle: compare stage0's semantic diagnostics with stage1's
# machine-readable reporter over standalone fixtures. Stage1 may add sound supplemental
# diagnostics (for example unused-name warnings), so the oracle requires every stage0
# message to be represented by a stage1 message, but does not require equal counts.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
FIXTURES="${DIAGNOSTIC_DIFF_FIXTURES:-$REPO_ROOT/test/fixtures/diagnostics}"

source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

# Strips the LOCATION prefix and collapses runs of whitespace. Nothing else.
#
# It used to also run `s/[^[:alnum:]_]+/ /g`, flattening every quote, colon, paren and
# backtick to a space — so the comparison was blind to punctuation, and 66 of stage0's 190
# messages differed from stage1's in ways this gate reported as identical: `'x'` where
# stage0 writes `"x"`, `add can[Abort.Panic]` for `add can Abort.Panic`, `cannot be used;`
# for `cannot be used:`, a missing `&` on `static u8&`, and one hint whose parenthetical
# was the exact inverse of stage0's. All fixed; the strictness is what keeps them fixed.
normalize() {
    sed -E \
        -e 's/^[^:]*:[0-9]+:[0-9]+(-[0-9]+(:[0-9]+)?)?:[[:space:]]*//' \
        -e 's/^  L[0-9]+[[:space:]]*//' \
        -e 's/[[:space:]]+/ /g' \
        -e 's/^ //' -e 's/ $//'
}

# stage0 messages stage1 does not reproduce VERBATIM yet. Each is ASSERTED, not skipped: a
# known gap that gets fixed without being removed from this list fails the gate, so the list
# cannot quietly outlive the divergence (see the stale-gate lesson in the project notes).
#
# EMPTY, and that is the point: stage1 now reproduces every stage0 diagnostic in the corpus
# byte-for-byte. Three entries lived here and all three are fixed:
#   - the CALL form of the namespace hint rendered the placeholder `M::member`, because it was
#     raised from the bare-Ident walk which has no member name; it is now raised from the Call
#     arm, where the callee's Field node names the member.
#   - two OPTIONAL spellings dropped the `?` (`got i64` for `got i64?`). Both raise sites had a
#     comment asserting stage0 elides the wrapper; stage0 does not. `actual` now keeps the
#     optional family and `detail` carries the base, which is the channel NonBoolCondition
#     already used, so one convention renders both.
# Keep the mechanism: adding a genuinely-unfixed message here documents it AND fails the day it
# starts agreeing, so the list can never outlive the divergence it describes.
KNOWN_DIVERGENCES=()
known_hit=()

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
            is_known=0
            for known in ${KNOWN_DIVERGENCES+"${KNOWN_DIVERGENCES[@]}"}; do
                [ "$known" = "$expected" ] && is_known=1
            done
            if [ "$is_known" -eq 1 ]; then
                known_hit+=("$expected")
            else
                printf 'diagnostic mismatch: %s\nstage0: %s\nstage1: %s\n' \
                    "${fixture#"$REPO_ROOT"/}" "$expected" "${s1//$'\n'/ | }" >&2
                failed=$((failed + 1))
            fi
        fi
    done <<EOF
$s0
EOF
done

if [ "$failed" -ne 0 ]; then
    echo "diagnostics diff FAILED: $failed stage0 diagnostic(s) missing or changed" >&2
    exit 1
fi

# A KNOWN divergence that stopped diverging must be removed from the list, or the list stops
# describing reality and the next reader trusts it.
for known in ${KNOWN_DIVERGENCES+"${KNOWN_DIVERGENCES[@]}"}; do
    still=0
    for hit in ${known_hit+"${known_hit[@]}"}; do
        [ "$hit" = "$known" ] && still=1
    done
    if [ "$still" -eq 0 ]; then
        echo "diagnostics diff FAILED: KNOWN_DIVERGENCES lists a message stage1 now reproduces;" >&2
        echo "  remove it from the list: $known" >&2
        exit 1
    fi
done

echo "diagnostics diff OK: $checked fixtures, byte-exact except ${#KNOWN_DIVERGENCES[@]} asserted divergences"
