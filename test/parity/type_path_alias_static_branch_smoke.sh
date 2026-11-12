#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
FIXTURE="$REPO_ROOT/test/repro/type_path_alias_static_branch.elisa"
fail() { echo "type-path alias static-branch smoke FAIL: $*" >&2; exit 1; }

check_report() {
    label="$1"
    report="$2"
    # These are the namespace diagnostics from the current Stage0 analyzer.
    # The other names belong to nested scopes or inactive/unknown imports.
    for name in ActiveAlias 'ActiveAlias::Nested' 'AncestorWins::Nested' 'DirectWins::Nested' BranchChainBeforeHead BranchChainAfterHead; do
        count="$(grep -Fc "\"$name\" is a namespace; write $name::" <<< "$report" || true)"
        [[ "$count" -eq 1 ]] || fail "$label expected one namespace diagnostic for $name, got $count: $report"
    done
    for name in InactiveAlias NestedGlobalAlias LateNestedAlias 'ScopedAlias::Nested' RawFallbackAlias RawAliasOnlyTarget 'BranchBeforeChild::Nested' 'SharedBranchAlias::Nested' 'BranchAfterChild::Nested'; do
        if grep -Fq "\"$name\" is a namespace; write $name::" <<< "$report"; then
            fail "$label treated $name as a visible namespace: $report"
        fi
    done
    chained_count="$(grep -Fc '"ChainedAlias" is a namespace; write ChainedAlias::' <<< "$report" || true)"
    [[ "$chained_count" -eq 1 ]] || fail "$label has unexpected chained alias diagnostic: $report"
    possible_count="$(grep -Fc '"PossibleAlias" is a namespace; write PossibleAlias::' <<< "$report" || true)"
    [[ "$possible_count" -eq "$3" ]] || fail "$label has unexpected target alias diagnostic: $report"
    count="$(grep -Fc 'is a namespace; write ' <<< "$report" || true)"
    [[ "$count" -eq $((7 + $3)) ]] || fail "$label produced unexpected namespace diagnostics ($count): $report"
}

check_report native "$("$RPT" < "$FIXTURE")" 0
check_report wasm-target "$(ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown "$RPT" < "$FIXTURE")" 1

shadow_report="$("$RPT" < "$REPO_ROOT/test/repro/type_path_alias_lexical_shadow.elisa")"
for line in 11 14; do
    grep -Fq "L$line \"Choice::Nested\" is a namespace; write Choice::Nested::Item" <<< "$shadow_report" || fail "nested alias does not shadow the root alias at line $line: $shadow_report"
done
grep -Fq 'L16 "Choice" is a namespace; write Choice::Item' <<< "$shadow_report" || fail "root alias is not visible outside the nested scope: $shadow_report"
[[ "$(grep -Fc 'is a namespace; write ' <<< "$shadow_report" || true)" -eq 3 ]] || fail "unexpected shadowing diagnostics: $shadow_report"

chain_report="$("$RPT" < "$REPO_ROOT/test/repro/type_path_alias_chain_shadow.elisa")"
grep -Fq 'L16 "Selected::Inner" is a namespace; write Selected::Inner::Item' <<< "$chain_report" || fail "chained alias did not resolve through the nearest scope: $chain_report"

echo "type-path alias static-branch visibility OK"
