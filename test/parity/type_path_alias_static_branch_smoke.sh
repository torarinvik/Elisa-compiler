#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
FIXTURE="$REPO_ROOT/test/repro/type_path_alias_static_branch.elisa"
fail() { echo "type-path alias static-branch smoke FAIL: $*" >&2; exit 1; }

check_report() {
    label="$1"
    report="$2"
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
    if grep -Fq '"ChainedAlias" is a namespace; write ChainedAlias::' <<< "$report"; then
        fail "$label treated an alias chained through an unresolved target as a definite module prefix: $report"
    fi
    nested_alias_count="$(grep -Fc '"NestedGlobalAlias" is a namespace; write NestedGlobalAlias::' <<< "$report" || true)"
    [[ "$nested_alias_count" -eq 1 ]] || fail "$label should resolve the Stage0-global alias declared in a nested module, got $nested_alias_count: $report"
    late_parent_alias_count="$(grep -Fc '"LateNestedAlias" is a namespace; write LateNestedAlias::' <<< "$report" || true)"
    [[ "$late_parent_alias_count" -eq 1 ]] || fail "$label should resolve a nested alias through its later-textual root alias, got $late_parent_alias_count: $report"
    ancestor_precedence_count="$(grep -Fc '"AncestorWins::Nested" is a namespace; write AncestorWins::Nested::' <<< "$report" || true)"
    [[ "$ancestor_precedence_count" -eq 1 ]] || fail "$label should keep the root definite alias ahead of its earlier textual nested possible alias, got $ancestor_precedence_count: $report"
    direct_precedence_count="$(grep -Fc '"DirectWins::Nested" is a namespace; write DirectWins::Nested::' <<< "$report" || true)"
    [[ "$direct_precedence_count" -eq 1 ]] || fail "$label should keep a direct alias ahead of a same-scope possible branch alias, got $direct_precedence_count: $report"
    raw_module_fallback_count="$(grep -Fc '"RawFallbackAlias" is a namespace; write RawFallbackAlias::' <<< "$report" || true)"
    [[ "$raw_module_fallback_count" -eq 1 ]] || fail "$label should retain a declared raw module path when a same-name alias registers after the target cutoff, got $raw_module_fallback_count: $report"
    scoped_precedence_count="$(grep -Fc '"ScopedAlias::Nested" is a namespace; write ScopedAlias::Nested::' <<< "$report" || true)"
    [[ "$scoped_precedence_count" -eq 1 ]] || fail "$label should prefer the nearest scoped raw module over a root module with the same short name, got $scoped_precedence_count: $report"
    if grep -Fq '"RawAliasOnlyTarget" is a namespace; write RawAliasOnlyTarget::' <<< "$report"; then
        fail "$label treated a later using-alias as a declared raw module for an earlier alias target: $report"
    fi
    branch_before_child_count="$(grep -Fc '"BranchBeforeChild::Nested" is a namespace; write BranchBeforeChild::Nested::' <<< "$report" || true)"
    [[ "$branch_before_child_count" -eq 1 ]] || fail "$label should let a parent branch alias win when its branch is traversed before the child module, got $branch_before_child_count: $report"
    branch_body_prepass_count="$(grep -Fc '"SharedBranchAlias::Nested" is a namespace; write SharedBranchAlias::Nested::' <<< "$report" || true)"
    [[ "$branch_body_prepass_count" -eq 1 ]] || fail "$label should pre-register direct aliases in one branch block before nested modules, got $branch_body_prepass_count: $report"
    branch_after_child_count="$(grep -Fc '"BranchAfterChild::Nested" is a namespace; write BranchAfterChild::Nested::' <<< "$report" || true)"
    [[ "$branch_after_child_count" -eq 1 ]] || fail "$label should let the earlier child alias beat a later parent branch alias, got $branch_after_child_count: $report"
    branch_chain_before_count="$(grep -Fc '"BranchChainBeforeHead" is a namespace; write BranchChainBeforeHead::' <<< "$report" || true)"
    [[ "$branch_chain_before_count" -eq 1 ]] || fail "$label should resolve an alias target through an earlier branch alias, got $branch_chain_before_count: $report"
    if grep -Fq '"BranchChainAfterHead" is a namespace; write BranchChainAfterHead::' <<< "$report"; then
        fail "$label resolved an alias target through a later branch alias: $report"
    fi
}

check_report native "$("$RPT" < "$FIXTURE")"
check_report unknown-target "$(ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown "$RPT" < "$FIXTURE")"

echo "type-path alias static-branch visibility OK"
