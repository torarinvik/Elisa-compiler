#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_fn_value_extern_module_rows.py"

FIXTURE="$REPO_ROOT/test/repro/fn_value_extern_rows_module_identity.elisa"
report="$("$RPT" < "$FIXTURE")"
grep -qE '^P 0$' <<< "$report" || {
    echo "function-value extern module-row smoke: fixture did not parse cleanly" >&2
    printf '%s\n' "$report" >&2
    exit 1
}

for expected in \
    'variable "from_a_wrong" expects fn() -> void can[Disk], got fn() -> void can[Console]' \
    'variable "lambda_a_wrong" expects fn() -> void can[Disk], got fn() -> void can[Console]' \
    'variable "lambda_import_wrong" expects fn() -> void can[Disk], got fn() -> void can[Console]'; do
    grep -Fq "$expected" <<< "$report" || {
        echo "function-value extern module-row smoke: missing $expected" >&2
        printf '%s\n' "$report" >&2
        exit 1
    }
done

for forbidden in \
    'variable "from_a_ok" expects' \
    'variable "from_b_ok" expects' \
    'variable "lambda_a_ok" expects' \
    'variable "lambda_b_ok" expects' \
    'variable "lambda_import_ok" expects' \
    'variable "lambda_callback_arg_ok" expects' \
    'variable "callback" expects'; do
    if grep -Fq "$forbidden" <<< "$report"; then
        echo "function-value extern module-row smoke: unexpected $forbidden" >&2
        printf '%s\n' "$report" >&2
        exit 1
    fi
done

echo "function-value extern module-row smoke OK"
