#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

darray_short=$(printf 'def bad(values: darray[i32]) -> darray[i32, row]:\n    return values\n' | "$RPT")
grep -q 'return type expects darray\[i32, row\], got darray\[i32\]' <<< "$darray_short"

darray_shape=$(printf 'def bad(values: darray[i32, row]) -> darray[i32, col]:\n    return values\n' | "$RPT")
grep -q 'return type expects darray\[i32, col\], got darray\[i32, row\]' <<< "$darray_shape"

cstr_short=$(printf 'def bad(text: cstr) -> cstr[row]:\n    return text\n' | "$RPT")
grep -q 'return type expects cstr\[row\], got cstr' <<< "$cstr_short"

erase=$(printf 'def ok(values: darray[i32, row]) -> darray[i32]:\n    return values\n' | "$RPT")
grep -q '^D 0$' <<< "$erase"

echo "container shape return smoke OK" >&2
