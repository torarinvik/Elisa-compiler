#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_function_annotation_generic_owner_identity.py"
python3 "$REPO_ROOT/test/proofs/check_extern_return_owner_identity.py"

check_diagnostic() {
  local source="$1"
  local expected="$2"
  local output
  output="$(printf '%s' "$source" | "$REPO_ROOT/build/parse_report")"
  [[ "$output" == *"D "* && "$output" == *"$expected"* ]] || {
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

check_absent() {
  local source="$1"
  local unexpected="$2"
  local output
  output="$(printf '%s' "$source" | "$REPO_ROOT/build/parse_report")"
  [[ "$output" != *"$unexpected"* ]] || {
    echo "unexpected annotation diagnostic: $unexpected" >&2
    printf '%s\n' "$output" >&2
    exit 1
  }
}

check_diagnostic $'@smoke\ndef sample_case() -> void:\n    pass\n' 'unknown function annotation @smoke'
check_diagnostic $'@smoke\nextern borrow_value(holder: i32&) -> i32&\n' 'unknown extern function annotation @smoke on "borrow_value"'
check_diagnostic $'@borrows_return(missing)\nextern borrow_value(holder: i32&) -> i32&\n' '@borrows_return on extern function "borrow_value" references unknown parameter "missing"'
check_diagnostic $'@borrows_return(count)\nextern borrow_value(count: i32) -> i32&\n' '@borrows_return on extern function "borrow_value" cannot borrow from parameter "count" of type i32'
check_diagnostic $'@test\ndef sample_case(value: int) -> void:\n    pass\n' '@test function "sample_case" must not take parameters'
check_diagnostic $'@bench\ndef hot_loop() -> int:\n    return 7\n' '@bench function "hot_loop" must return void, got int'
check_diagnostic $'@fixture\ndef shared_seed[T]() -> int:\n    return 7\n' '@fixture function "shared_seed" must not have type or shape parameters'
check_clean $'@test\ndef sample_case() -> void:\n    pass\n'
check_clean $'@bench\ndef hot_loop() -> void:\n    pass\n'
check_clean $'@fixture\ndef shared_seed() -> int:\n    return 7\n'
check_clean $'@link_name("borrow_value")\nextern borrow_value(holder: i32&) -> i32&\n'
check_absent $'#line 0 generic_owner.elisa\ndef generic_seed[T]() -> void:\n    pass\n#line 0 ordinary_owner.elisa\n@fixture\ndef ordinary_seed() -> void:\n    pass\n' '@fixture function "ordinary_seed" must not have type or shape parameters'
check_absent "$(cat "$REPO_ROOT/test/repro/extern_return_owner_line_zero.elisa")" '@borrows_return on extern function "second" references unknown return field path "second" in First'
check_absent "$(cat "$REPO_ROOT/test/repro/extern_return_owner_line_zero.elisa")" '@borrows_return(field, …) on extern function "second" requires a concrete struct return type, got'

echo "function annotation smoke OK"
