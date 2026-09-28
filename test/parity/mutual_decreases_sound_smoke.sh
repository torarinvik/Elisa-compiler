#!/usr/bin/env bash
# The mutual-decreases checker accepts only when every edge in the recursive cycle
# strictly decreases the actual callee measure argument.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/elisac_stage1.sh"
FIXTURES="$REPO_ROOT/test/parity/fixtures"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

"$WRAPPER" -emit obj -O0 -o "$WORK/valid.o" "$FIXTURES/mutual_decreases_valid.elisa"
"$WRAPPER" -emit obj -O0 -o "$WORK/measure-not-first.o" "$FIXTURES/mutual_decreases_measure_not_first.elisa"
"$WRAPPER" -emit obj -O0 -o "$WORK/capture-not-shadow.o" "$FIXTURES/mutual_decreases_capture_not_shadow.elisa"
"$WRAPPER" -emit obj -O0 -o "$WORK/capture-reference-args.o" "$FIXTURES/mutual_decreases_capture_with_reference_args.elisa"
"$WRAPPER" -emit obj -O0 -o "$WORK/module-qualified-call.o" "$FIXTURES/mutual_decreases_module_qualified_call.elisa"

for fixture in mutual_decreases_unchanged_edge mutual_decreases_wrong_parameter mutual_decreases_unsigned_multistep mutual_decreases_contract_unchanged; do
    set +e
    output="$("$WRAPPER" -emit obj -O0 -o "$WORK/$fixture.o" "$FIXTURES/$fixture.elisa" 2>&1)"
    status=$?
    set -e
    if [[ "$status" -eq 0 || "$output" != *'mutually-recursive cycle'* ]]; then
        printf 'mutual-decreases regression %s: expected conservative cycle rejection, status %s\n%s\n' \
            "$fixture" "$status" "$output" >&2
        exit 1
    fi
done

echo "mutual decreases smoke OK: valid edges accepted; unchanged and wrong-parameter edges rejected"
