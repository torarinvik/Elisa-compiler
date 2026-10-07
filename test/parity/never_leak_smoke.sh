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
    for flag in -Wnever-leak -Wnever-leak=strict; do
        check "$flag" "$FIXTURES/$legal.elisa"
        [[ "$status" -eq 0 ]] || fail "$legal.elisa ($flag) exited $status: $output"
        [[ "$output" != *"[-Wnever-leak]"* ]] || fail "$legal.elisa drew a finding under $flag: $output"
    done
done

export ELISA_STAGE1_NEVER_LEAK_STATS=1
for flag in -Wnever-leak -Wnever-leak=strict; do
    check "$flag" "$FIXTURES/illegal.elisa"
    [[ "$status" -eq 0 ]] || fail "a warning must not fail the compile ($flag, exit $status): $output"
    rows="$(printf '%s\n' "$output" | awk -F'\t' '$1 == "never-leak-stat" { n = split($2, at, ":"); print $3 "\t" $4 "\t" at[n] }')"
    expected="$(grep -v '^#' "$FIXTURES/expected.tsv")"
    [[ "$rows" == "$expected" ]] || fail "rows ($flag) differ from expected.tsv:
$(diff <(printf '%s\n' "$expected") <(printf '%s\n' "$rows") || true)"
done
unset ELISA_STAGE1_NEVER_LEAK_STATS

# The full text, with the fixture directory stripped from each location.
expect_text() {
    local wanted="$1"; shift
    check "$@" "$FIXTURES/illegal.elisa"
    [[ "$status" -eq 0 ]] || fail "$* exited $status: $output"
    text="${output//"$FIXTURES/"/}"
    [[ "$text" == "$(cat "$FIXTURES/$wanted")" ]] || fail "$* output differs from $wanted:
$(diff "$FIXTURES/$wanted" <(printf '%s\n' "$text") || true)"
}
expect_text expected-strict.txt -Wnever-leak=strict
expect_text expected-gentle.txt -Wnever-leak
expect_text expected-gentle.txt -W never-leak
expect_text expected-gentle.txt -Wnever-leak=gentle
expect_text expected-strict.txt -W never-leak=strict
warnings="$(grep -c 'stays visible after its last use \[-Wnever-leak\]' "$FIXTURES/expected-strict.txt")"
[[ "$warnings" -eq 6 ]] || fail "expected-strict.txt must hold 6 findings, has $warnings"
warnings="$(grep -c 'stays visible after its last use \[-Wnever-leak\]' "$FIXTURES/expected-gentle.txt")"
[[ "$warnings" -eq 2 ]] || fail "expected-gentle.txt must hold 2 findings, has $warnings"

for flag in -Werror=never-leak -Werror=never-leak=strict; do
    check "$flag" "$FIXTURES/illegal.elisa"
    [[ "$status" -ne 0 && "$output" == *": error: local"* ]] || fail "$flag must fail the compile (exit $status)"
done
check -Wnever-leak=strict -Werror=never-leak "$FIXTURES/illegal.elisa"
[[ "$output" == *"error: local \`bar\`"* ]] || fail "-Werror=never-leak after =strict must stay strict: $output"

check -permissive -Wnever-leak "$FIXTURES/illegal.elisa"
[[ "$status" -eq 0 && "$output" != *"never-leak"* ]] || fail "-permissive must turn the lint off: $output"

echo "never-leak smoke OK: off by default, strict 6 and gentle 2 findings pinned verbatim, legal and rewritten fixtures clean"
