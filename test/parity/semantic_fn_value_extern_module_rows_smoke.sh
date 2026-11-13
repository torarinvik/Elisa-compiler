#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
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

scoped_report="$("$RPT" < "$REPO_ROOT/test/repro/fn_value_extern_permission_scope.elisa")"
if ! grep -qx 'P 0' <<< "$scoped_report" || ! grep -qx 'D 2' <<< "$scoped_report" \
    || ! grep -Fq 'variable "bad_a" expects' <<< "$scoped_report" \
    || ! grep -Fq 'variable "bad_b" expects' <<< "$scoped_report"; then
    echo "function-value extern module-row smoke: permission identities were lost" >&2
    printf '%s\n' "$scoped_report" >&2
    exit 1
fi

mixed_report="$("$RPT" < "$REPO_ROOT/test/repro/fn_value_extern_mixed_effects.elisa")"
if ! grep -qx 'P 0' <<< "$mixed_report" || ! grep -qx 'D 1' <<< "$mixed_report" \
    || ! grep -Fq 'variable "bad" expects fn() -> void can[Console], got fn() -> void can[Console, Memory]' <<< "$mixed_report"; then
    echo "function-value extern module-row smoke: canonical and extern rows did not combine" >&2
    printf '%s\n' "$mixed_report" >&2
    exit 1
fi

echo "function-value extern module-row smoke OK"
