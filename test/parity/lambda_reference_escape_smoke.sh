#!/usr/bin/env bash
# A reference to a scalar is still a reference and must remain conservative.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
result=$(printf 'struct Holder:\n    value: sview\ndef f() -> void:\n    add = fn(a: i64&, b: i64&) => a + b\n' | "$RPT")
[[ "$result" == $'P 0\n'* ]]
[[ "$(printf '%s\n' "$result" | grep -c 'short-lived region escapes via store')" == 2 ]]
printf 'lambda reference escape smoke OK\n'
