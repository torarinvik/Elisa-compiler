#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

string_slice=$(printf 'def bad(text: cstr[row]) -> void:\n    while text[0:1]:\n        pass\n' | "$RPT")
grep -q 'while condition must be bool' <<< "$string_slice"

array_slice=$(printf 'def bad(values: darray[i32]) -> void:\n    if values[0:1]:\n        pass\n' | "$RPT")
grep -q 'if condition must be bool' <<< "$array_slice"

comparison=$(printf 'def ok(text: cstr[row]) -> void:\n    while text[0:1] == "x":\n        pass\n' | "$RPT")
grep -q '^D 0$' <<< "$comparison"

echo "slice condition smoke OK" >&2
