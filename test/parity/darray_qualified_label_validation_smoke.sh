#!/usr/bin/env bash
# Qualified calls with same-named module functions must validate labels against the
# exact resolved declaration before backend lowering.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

run_case() {
    local label="$1" call="$2" expected="$3" output
    output=$(printf '%s\n' \
        'module North:' \
        '    def store(values: darray[sview]&, count: i64) -> void:' \
        '        pass' \
        'module South:' \
        '    def store(numbers: darray[i64]&, count: i64) -> void:' \
        '        pass' \
        'def probe(texts: darray[sview]&, numbers: darray[i64]&) -> void:' \
        "    $call" | "$RPT")
    grep -qx 'P 0' <<< "$output" || { echo "$label: parse failed: $output" >&2; return 1; }
    if [[ "$expected" == accept ]]; then
        grep -qx 'D 0' <<< "$output" || { echo "$label: valid call rejected: $output" >&2; return 1; }
    else
        grep -Eq '^D [1-9][0-9]*$' <<< "$output" || { echo "$label: malformed call admitted: $output" >&2; return 1; }
        grep -qiE 'parameter|positional arguments after named' <<< "$output" || { echo "$label: missing named-call diagnostic: $output" >&2; return 1; }
    fi
}

run_case north_same_name 'North::store(values: texts, count: 1)' accept
run_case south_same_name 'South::store(numbers: numbers, count: 1)' accept
run_case wrong_owner_label 'North::store(numbers: numbers, count: 1)' reject
run_case unknown_label 'North::store(unknown: texts, count: 1)' reject
run_case duplicate_label 'North::store(values: texts, values: texts, count: 1)' reject
run_case positional_after_named 'North::store(values: texts, 1)' reject
echo 'qualified darray labels smoke PASS'
