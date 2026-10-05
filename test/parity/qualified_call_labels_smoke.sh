#!/usr/bin/env bash
# Semantic admission must reject malformed labels before backend lowering.
set -euo pipefail
REPO_ROOT="${ELISA_TEST_REPO_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)}"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

check_case() {
    local label="$1" call="$2" expected="$3" output diagnostics
    output=$(printf '%s\n' \
        'module North:' \
        '    def store(values: darray[sview]&, count: i64) -> void:' \
        '        pass' \
        'module South:' \
        '    def store(numbers: darray[i64]&, count: i64) -> void:' \
        '        pass' \
        'def probe(texts: darray[sview]&) -> void:' \
        "    $call" | "$RPT")
    grep -qx 'P 0' <<< "$output" || { echo "$label: parse failure: $output" >&2; return 1; }
    diagnostics=$(awk '$1 == "D" { print $2 }' <<< "$output")
    [[ "$diagnostics" =~ ^[0-9]+$ ]] || { echo "$label: invalid reporter output: $output" >&2; return 1; }
    if [[ "$expected" == accept ]]; then
        [[ "$diagnostics" == 0 ]] || { echo "$label: valid call rejected: $output" >&2; return 1; }
    else
        [[ "$diagnostics" -gt 0 ]] || { echo "$label: malformed call admitted: $output" >&2; return 1; }
        grep -qiE 'argument|parameter' <<< "$output" || { echo "$label: rejection was not a call diagnostic: $output" >&2; return 1; }
    fi
}

check_case valid 'North::store(values: texts, count: 1)' accept
check_case reordered 'North::store(count: 1, values: texts)' accept
check_case positional 'North::store(texts, 1)' accept
check_case unknown 'North::store(numbers: texts, count: 1)' reject
check_case duplicate 'North::store(values: texts, values: texts, count: 1)' reject
check_case after_named 'North::store(values: texts, 1)' reject
echo 'qualified call labels smoke PASS'
