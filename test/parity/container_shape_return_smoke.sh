#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

darray_short=$(printf 'def bad(values: darray[i32]) -> darray[i32, row]:\n    return values\n' | "$RPT")
printf '%s\n' "$darray_short" | grep -q 'return type expects darray\[i32, row\], got darray\[i32\]'

darray_shape=$(printf 'def bad(values: darray[i32, row]) -> darray[i32, col]:\n    return values\n' | "$RPT")
printf '%s\n' "$darray_shape" | grep -q 'return type expects darray\[i32, col\], got darray\[i32, row\]'

cstr_short=$(printf 'def bad(text: cstr) -> cstr[row]:\n    return text\n' | "$RPT")
printf '%s\n' "$cstr_short" | grep -q 'return type expects cstr\[row\], got cstr'

erase=$(printf 'def ok(values: darray[i32, row]) -> darray[i32]:\n    return values\n' | "$RPT")
printf '%s\n' "$erase" | grep -q '^D 0$'

echo "container shape return smoke OK" >&2
