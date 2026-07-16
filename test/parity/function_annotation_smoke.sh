#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
REPO_ROOT="$REPO_ROOT" ELISACORE_BIN="$ELISACORE_BIN" bash "$REPO_ROOT/test/parity/build_parse_report.sh"

check_diagnostic() {
  local source="$1"
  local expected="$2"
  local output
  output="$(printf '%s' "$source" | "$REPO_ROOT/build/parse_report")"
  [[ "$output" == *"D 1"* && "$output" == *"$expected"* ]] || {
    echo "missing annotation diagnostic: $expected" >&2
    printf '%s\n' "$output" >&2
    exit 1
  }
}

check_clean() {
  local source="$1"
  local output
  output="$(printf '%s' "$source" | "$REPO_ROOT/build/parse_report")"
  [[ "$output" != *"unknown function annotation"* && "$output" != *"unknown extern function annotation"* ]] || {
    echo "supported annotation was rejected" >&2
    printf '%s\n' "$output" >&2
    exit 1
  }
}

check_diagnostic $'@smoke\ndef sample_case() -> void:\n    pass\n' 'unknown function annotation @smoke'
check_diagnostic $'@smoke\nextern borrow_value(holder: i32&) -> i32&\n' 'unknown extern function annotation @smoke on "borrow_value"'
check_clean $'@test\ndef sample_case() -> void:\n    pass\n'
check_clean $'@link_name("borrow_value")\nextern borrow_value(holder: i32&) -> i32&\n'

echo "function annotation smoke OK"
