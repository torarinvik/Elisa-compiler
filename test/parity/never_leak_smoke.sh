#!/usr/bin/env bash
# -Wnever-leak (stage1 only, opt-in): src/semantic/check_never_leak*.elisa and
# src/driver/elisac_never_leak*.elisa.
#
#   - OFF by default: illegal.elisa draws no finding without the flag (every gate unaffected).
#   - legal.elisa draws none in either mode. fixed.elisa (illegal.elisa with each STRICT rewrite
#     applied verbatim) draws none under gentle and, under strict, only the accumulator candidate
#     no rewrite fits (`seen`); both compilers build and run it (exit 0 checks the results).
#   - the stat rows of illegal.elisa are exactly expected-rows.txt (category, local, line; the
#     rows are the same in both modes).
#   - the full warning text is exactly expected-strict.txt under -Wnever-leak=strict and
#     expected-gentle.txt under -Wnever-leak, -W never-leak and -Wnever-leak=gentle (gentle is
#     the default: it accepts a local whose last use is the next statement and does not report
#     accumulator candidates no rewrite fits: 11 vs 6 findings).
#   - -Werror=never-leak[=strict] fails the compile; -permissive turns it off.
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
        findings="$(printf '%s\n' "$output" | grep -c '\[-Wnever-leak\]$' || true)"
        allowed=0
        if [[ "$legal" == fixed && "$flag" == -Wnever-leak=strict ]]; then
            allowed=1
            [[ "$output" == *"accumulator \`seen\` stays mutable"*"no loop-value rewrite applies"* ]] || fail "fixed.elisa under strict must report only \`seen\` (no rewrite fits): $output"
        fi
        [[ "$findings" -eq "$allowed" ]] || fail "$legal.elisa drew $findings findings under $flag (expected $allowed): $output"
    done
done

# fixed.elisa is real code: both compilers build it and it checks its own results (exit 0).
STAGE0="${ELISACORE_BIN:-$REPO_ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-never-leak.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
bash "$WRAPPER" -emit exe -o "$WORK/fixed.s1" "$FIXTURES/fixed.elisa" >"$WORK/build.log" 2>&1 || fail "stage1 cannot build fixed.elisa: $(cat "$WORK/build.log")"
"$WORK/fixed.s1" || fail "fixed.elisa (stage1) exited $?"
[[ -x "$STAGE0" ]] || fail "missing stage0 compiler: $STAGE0"
. "$REPO_ROOT/scripts/platform.sh"
"$STAGE0" -emit c-archive -O2 -o "$WORK/fixed.a" "$FIXTURES/fixed.elisa" >"$WORK/build.log" 2>&1 || fail "stage0 cannot build fixed.elisa: $(cat "$WORK/build.log")"
clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$WORK/fixed.s0" "$WORK/fixed.a" >"$WORK/build.log" 2>&1 || fail "cannot link stage0 fixed.elisa: $(cat "$WORK/build.log")"
"$WORK/fixed.s0" || fail "fixed.elisa (stage0) exited $?"

export ELISA_STAGE1_NEVER_LEAK_STATS=1
for flag in -Wnever-leak -Wnever-leak=strict; do
    check "$flag" "$FIXTURES/illegal.elisa"
    [[ "$status" -eq 0 ]] || fail "a warning must not fail the compile ($flag, exit $status): $output"
    rows="$(printf '%s\n' "$output" | awk -F'\t' '$1 == "never-leak-stat" { n = split($2, at, ":"); print $3 "\t" $4 "\t" at[n] }')"
    expected="$(grep -v '^#' "$FIXTURES/expected-rows.txt")"
    [[ "$rows" == "$expected" ]] || fail "rows ($flag) differ from expected-rows.txt:
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
warnings="$(grep -c '\[-Wnever-leak\]$' "$FIXTURES/expected-strict.txt")"
[[ "$warnings" -eq 11 ]] || fail "expected-strict.txt must hold 11 findings, has $warnings"
warnings="$(grep -c '\[-Wnever-leak\]$' "$FIXTURES/expected-gentle.txt")"
[[ "$warnings" -eq 6 ]] || fail "expected-gentle.txt must hold 6 findings, has $warnings"

for flag in -Werror=never-leak -Werror=never-leak=strict; do
    check "$flag" "$FIXTURES/illegal.elisa"
    [[ "$status" -ne 0 && "$output" == *": error: local"* ]] || fail "$flag must fail the compile (exit $status)"
done
check -Wnever-leak=strict -Werror=never-leak "$FIXTURES/illegal.elisa"
[[ "$output" == *"error: local \`bar\`"* ]] || fail "-Werror=never-leak after =strict must stay strict: $output"

check -permissive -Wnever-leak "$FIXTURES/illegal.elisa"
[[ "$status" -eq 0 && "$output" != *"never-leak"* ]] || fail "-permissive must turn the lint off: $output"

echo "never-leak smoke OK: off by default, strict 11 and gentle 6 findings (accumulators included) pinned verbatim, legal and rewritten fixtures clean, fixed.elisa runs on both compilers"
