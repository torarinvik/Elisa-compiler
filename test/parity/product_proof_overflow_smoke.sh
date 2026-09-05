#!/usr/bin/env bash
# Product-bound provers must decline unrepresentable corners instead of using host overflow.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/elisac_stage1.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

check_unproven() {
    local name="$1"
    local expected="$2"
    local source="$REPO_ROOT/test/parity/fixtures/$name.elisa"
    local output status
    set +e
    output="$("$WRAPPER" -emit obj -O0 -o "$WORK/$name.o" "$source" 2>&1)"
    status=$?
    set -e
    if [[ "$status" -ne 1 || "$output" != *"$expected"* ]]; then
        printf 'product-proof overflow regression (%s): expected an unproven diagnostic, got %s\n%s\n' "$name" "$status" "$output" >&2
        exit 1
    fi
}

check_unproven assert_by_product_overflow 'could not be proven'

set +e
ensure_output="$("$WRAPPER" -emit obj -O0 -o "$WORK/product_proof_overflow.o" "$REPO_ROOT/test/parity/fixtures/product_proof_overflow.elisa" 2>&1)"
ensure_status=$?
set -e
if [[ "$ensure_status" -gt 1 ]]; then
    printf 'product-proof overflow regression (ensure): compiler failed unexpectedly with %s\n%s\n' "$ensure_status" "$ensure_output" >&2
    exit 1
fi

echo "product-proof overflow smoke OK: unrepresentable product corners were declined"
