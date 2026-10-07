#!/usr/bin/env bash
# -Wnever-leak (stage1 only, opt-in): src/semantic/check_never_leak*.elisa and
# src/driver/elisac_never_leak*.elisa.
#
#   - OFF by default: illegal.elisa draws no finding without the flag (every gate unaffected).
#   - legal.elisa and fixed.elisa (illegal.elisa with each suggested rewrite applied) draw none.
#   - illegal.elisa draws exactly the rows in expected.tsv (category, local, line).
#   - every finding carries a `fix` or an explanation of why no block rewrite exists.
#   - -Werror=never-leak fails the compile; -permissive turns the lint off.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$REPO_ROOT/scripts/elisac_stage1.sh"
FIXTURES="$REPO_ROOT/test/fixtures/never_leak"
fail() { printf 'never-leak smoke FAILED: %s\n' "$1" >&2; exit 1; }

check() {
    set +e
    output="$(bash "$WRAPPER" -emit check "$@" 2>&1)"
    status=$?
    set -e
}

check "$FIXTURES/illegal.elisa"
[[ "$status" -eq 0 ]] || fail "illegal.elisa without the flag exited $status: $output"
[[ "$output" != *"never-leak"* ]] || fail "the lint ran without being requested: $output"

for legal in legal fixed; do
    check -Wnever-leak "$FIXTURES/$legal.elisa"
    [[ "$status" -eq 0 ]] || fail "$legal.elisa exited $status: $output"
    [[ "$output" != *"[-Wnever-leak]"* ]] || fail "$legal.elisa drew a finding: $output"
done

export ELISA_STAGE1_NEVER_LEAK_STATS=1
check -W never-leak "$FIXTURES/illegal.elisa"
[[ "$status" -eq 0 ]] || fail "a warning must not fail the compile (exit $status): $output"
rows="$(printf '%s\n' "$output" | awk -F'\t' '$1 == "never-leak-stat" { n = split($2, at, ":"); print $3 "\t" $4 "\t" at[n] }')"
expected="$(grep -v '^#' "$FIXTURES/expected.tsv")"
[[ "$rows" == "$expected" ]] || fail "rows differ from expected.tsv:
$(diff <(printf '%s\n' "$expected") <(printf '%s\n' "$rows") || true)"
warnings="$(printf '%s\n' "$output" | grep -c 'warning: local .* stays visible after its last use \[-Wnever-leak\]' || true)"
fixes="$(printf '%s\n' "$output" | grep -c '^  fix\|^  no block rewrite' || true)"
[[ "$warnings" -eq 6 && "$fixes" -ge 6 ]] || fail "expected 6 warnings each with a fix, got $warnings warnings and $fixes fixes"
[[ "$output" == *"      lol: i64 =
          bar: i64 = seed + 1
          baz(bar)
      sink(lol)"* ]] || fail "the chain rewrite is not the user's own code nested under the binding: $output"
[[ "$output" == *"while index < limit |index: i64 = 0|:"* ]] || fail "the loop-header rewrite is missing: $output"
unset ELISA_STAGE1_NEVER_LEAK_STATS

check -Werror=never-leak "$FIXTURES/illegal.elisa"
[[ "$status" -ne 0 && "$output" == *": error: local"* ]] || fail "-Werror=never-leak must fail the compile (exit $status)"

check -permissive -Wnever-leak "$FIXTURES/illegal.elisa"
[[ "$status" -eq 0 && "$output" != *"never-leak"* ]] || fail "-permissive must turn the lint off: $output"

echo "never-leak smoke OK: off by default, 6 findings with rewrites, legal and rewritten fixtures clean"
