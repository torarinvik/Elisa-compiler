#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
REPO_ROOT="$REPO_ROOT" ELISACORE_BIN="$ELISACORE_BIN" bash "$REPO_ROOT/test/parity/build_parse_report.sh"

check_case() {
  local source="$1"
  local expected="$2"
  local output
  output="$(printf '%s' "$source" | "$REPO_ROOT/build/parse_report")"
  [[ "$output" == *"$expected"* ]] || {
    echo "missing array-bounds diagnostic: $expected" >&2
    printf '%s\n' "$output" >&2
    exit 1
  }
}

check_case $'const IDX: usize = 4\n\ndef bad() -> u8:\n    buf: u8[4] = zeroed\n    return buf[IDX]\n' "index out of bounds: 'buf' has 4 elements, index is 4"
check_case $'def bad() -> view[u8]:\n    buf: u8[4] = zeroed\n    return buf[2:5]\n' 'constant slice end 5 out of bounds for array of length 4'
check_case $'def bad() -> view[u8]:\n    buf: u8[4] = zeroed\n    return buf[3:1]\n' 'constant slice start 3 is after end 1'

echo "array bounds smoke OK"
