#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
FIXTURE="$REPO_ROOT/test/repro/type_path_alias_static_branch.elisa"
fail() { echo "type-path alias static-branch smoke FAIL: $*" >&2; exit 1; }

check_report() {
    label="$1"
    report="$2"
    expected_choice_count="$3"
    active_count="$(grep -Fc '"ActiveAlias" is a namespace; write ActiveAlias::' <<< "$report" || true)"
    [[ "$active_count" -eq 1 ]] || fail "$label should retain the definite ActiveAlias namespace diagnostic, got $active_count: $report"
    nested_count="$(grep -Fc '"ActiveAlias::Nested" is a namespace; write ActiveAlias::Nested::' <<< "$report" || true)"
    [[ "$nested_count" -eq 1 ]] || fail "$label should retain the nested module prefix diagnostic through ActiveAlias, got $nested_count: $report"
    if grep -Fq '"InactiveAlias" is a namespace; write InactiveAlias::' <<< "$report"; then
        fail "$label treated a proven-inactive alias as a visible module prefix: $report"
    fi
    if grep -Fq '"PossibleAlias" is a namespace; write PossibleAlias::' <<< "$report"; then
        fail "$label treated an unresolved alias as a definite module prefix: $report"
    fi
    choice_count="$(grep -Fc '"Choice::Nested" is a namespace; write Choice::Nested::' <<< "$report" || true)"
    [[ "$choice_count" -eq "$expected_choice_count" ]] || fail "$label expected $expected_choice_count Choice::Nested namespace diagnostics after alias precedence, got $choice_count: $report"
}

check_report native "$("$RPT" < "$FIXTURE")" 1
check_report unknown-target "$(ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown "$RPT" < "$FIXTURE")" 0

echo "type-path alias static-branch visibility OK"
