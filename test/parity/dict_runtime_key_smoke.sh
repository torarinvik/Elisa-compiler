#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

float_key=$(printf 'def use(values: dict[f64, i32], key: f64) -> mutable i32&?:\n    return values.get(key)\n' | "$RPT")
grep -q 'runtime-backed dict keys must be cstr, an integer type, bool, or a const enum' <<< "$float_key"

int_key=$(printf 'def use(values: dict[i64, i32], key: i64) -> mutable i32&?:\n    return values.get(key)\n' | "$RPT")
grep -q '^D 0$' <<< "$int_key"

echo "dict runtime key smoke OK" >&2
