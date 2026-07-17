#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

ungranted=$(printf 'def visit(values: darray[i32]) -> void:\n    parallel for value in values:\n        pass\n' | "$RPT")
printf '%s\n' "$ungranted" | grep -q 'parallel for requires an enclosing permission grant'

signature_granted=$(printf 'def visit(values: darray[i32]) -> void can[Pool.Submit, Pool.WaitAll]:\n    parallel for value in values:\n        pass\n' | "$RPT")
printf '%s\n' "$signature_granted" | grep -q '^D 0$'

locally_granted=$(printf 'def visit(values: darray[i32]) -> void:\n    can Pool.Submit, Pool.WaitAll:\n        parallel for value in values:\n            pass\n' | "$RPT")
printf '%s\n' "$locally_granted" | grep -q '^D 0$'

ordinary=$(printf 'def visit(values: darray[i32]) -> void:\n    for value in values:\n        pass\n' | "$RPT")
printf '%s\n' "$ordinary" | grep -q '^D 0$'

outer_mutation=$(printf 'def visit(values: darray[i32]) -> void can[Pool.Submit, Pool.WaitAll]:\n    total: mutable i32 = 0\n    parallel for value in values:\n        total <- total + value\n' | "$RPT")
printf '%s\n' "$outer_mutation" | grep -q 'parallel for body cannot mutate outer binding "total"'

local_mutation=$(printf 'def visit(values: darray[i32]) -> void can[Pool.Submit, Pool.WaitAll]:\n    parallel for value in values:\n        local: mutable i32 = value\n        local <- local + 1\n' | "$RPT")
printf '%s\n' "$local_mutation" | grep -q '^D 0$'

echo "parallel for grant smoke OK" >&2
