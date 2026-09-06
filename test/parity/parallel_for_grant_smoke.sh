#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

ungranted=$(printf 'def visit(values: darray[i32]) -> void:\n    parallel for value in values:\n        pass\n' | "$RPT")
grep -q 'parallel for requires an enclosing permission grant' <<< "$ungranted"

signature_granted=$(printf 'def visit(values: darray[i32]) -> void can[Pool.Submit, Pool.WaitAll]:\n    parallel for value in values:\n        pass\n' | "$RPT")
grep -q '^D 0$' <<< "$signature_granted"

locally_granted=$(printf 'def visit(values: darray[i32]) -> void:\n    can Pool.Submit, Pool.WaitAll:\n        parallel for value in values:\n            pass\n' | "$RPT")
grep -q '^D 0$' <<< "$locally_granted"

ordinary=$(printf 'def visit(values: darray[i32]) -> void:\n    for value in values:\n        pass\n' | "$RPT")
grep -q '^D 0$' <<< "$ordinary"

outer_mutation=$(printf 'def visit(values: darray[i32]) -> void can[Pool.Submit, Pool.WaitAll]:\n    total: mutable i32 = 0\n    parallel for value in values:\n        total <- total + value\n' | "$RPT")
grep -q 'parallel for body cannot mutate outer binding "total"' <<< "$outer_mutation"

local_mutation=$(printf 'def visit(values: darray[i32]) -> void can[Pool.Submit, Pool.WaitAll]:\n    parallel for value in values:\n        local: mutable i32 = value\n        local <- local + 1\n' | "$RPT")
grep -q '^D 0$' <<< "$local_mutation"

echo "parallel for grant smoke OK" >&2
