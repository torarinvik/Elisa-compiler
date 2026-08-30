#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

arity=$(printf 'struct Pair[?, ?]:\n    value: i32\ndef bad(value: Pair[&]) -> Pair[&]:\n    return value\n' | "$RPT")
printf '%s\n' "$arity" | grep -q "expects 2 aggregate state arguments, got 1"

plain=$(printf 'struct Plain:\n    value: i32\ndef bad(value: Plain[&]) -> Plain[&]:\n    return value\n' | "$RPT")
printf '%s\n' "$plain" | grep -q "does not declare an aggregate state parameter"

valid=$(printf 'struct Holder[?, ?]:\n    value: i32\ndef read(value: Holder[&, !]) -> i32:\n    return value.value\n' | "$RPT")
printf '%s\n' "$valid" | grep -q '^D 0$'

generic=$(printf 'struct Box[T]:\n    value: T\ndef read(value: Box[i32]) -> i32:\n    return value.value\n' | "$RPT")
printf '%s\n' "$generic" | grep -q '^D 0$'

echo "aggregate state arity smoke OK" >&2
