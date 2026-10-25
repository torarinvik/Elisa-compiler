#!/usr/bin/env bash
# Stage1 must reject the marker-only form that Stage0 rejects during error-set resolution.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
export ELISA_STAGE1_BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
export ELISA_RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
source "$ROOT/test/parity/build_parse_report.sh"

report=$("$RPT" < "$ROOT/test/fixtures/diagnostics/empty_error_set_subset.elisa")
grep -q '^D 1$' <<< "$report"
grep -q 'error\[...\] requires at least one qualified error tag' <<< "$report"

protocol_report=$("$RPT" < "$ROOT/test/fixtures/diagnostics/empty_protocol_error_set_subset.elisa")
grep -q '^D 1$' <<< "$protocol_report"
grep -q 'error\[...\] requires at least one qualified error tag' <<< "$protocol_report"

line_zero_protocol_report=$("$RPT" < "$ROOT/test/fixtures/diagnostics/empty_protocol_error_set_subset_line_zero.elisa")
grep -q '^D 1$' <<< "$line_zero_protocol_report"
grep -q 'error\[...\] requires at least one qualified error tag' <<< "$line_zero_protocol_report"

parameter_report=$("$RPT" < "$ROOT/test/fixtures/diagnostics/empty_protocol_callback_error_set_subset.elisa")
grep -q '^D 1$' <<< "$parameter_report"
grep -q 'error\[...\] requires at least one qualified error tag' <<< "$parameter_report"

bracket_report=$("$RPT" < "$ROOT/test/fixtures/diagnostics/empty_error_set_brackets.elisa")
grep -q '^D 1$' <<< "$bracket_report"
grep -q 'error\[...\] requires at least one qualified error tag' <<< "$bracket_report"

protocol_bracket_report=$("$RPT" < "$ROOT/test/fixtures/diagnostics/empty_protocol_error_set_brackets.elisa")
grep -q '^D 1$' <<< "$protocol_bracket_report"
grep -q 'error\[...\] requires at least one qualified error tag' <<< "$protocol_bracket_report"

callback_bracket_report=$("$RPT" < "$ROOT/test/fixtures/diagnostics/empty_callback_error_set_brackets.elisa")
grep -q '^D 1$' <<< "$callback_bracket_report"
grep -q 'error\[...\] requires at least one qualified error tag' <<< "$callback_bracket_report"

field_subset_report=$("$RPT" < "$ROOT/test/fixtures/diagnostics/empty_struct_field_error_set_subset.elisa")
grep -q '^D 1$' <<< "$field_subset_report"
grep -q 'error\[...\] requires at least one qualified error tag' <<< "$field_subset_report"

multiline_subset_report=$("$RPT" < "$ROOT/test/fixtures/diagnostics/empty_multiline_error_set_subset.elisa")
grep -q '^D 2$' <<< "$multiline_subset_report"
grep -q 'error\[...\] requires at least one qualified error tag' <<< "$multiline_subset_report"

echo "empty error-set subset diagnostic smoke OK" >&2
