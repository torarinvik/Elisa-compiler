#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
# Value-threading call sites (STYLE_GUIDE.md section 6; src/semantic/check_value_threading*.elisa).
#
#   - legal.elisa (every accepted form: `x <- f(x)`, the method spelling, a two-element result
#     `a, last <- pop_one(a)`, a field of an owned struct, a loop threading a collection, a
#     moved copy `y = f(x)`, `return f(x)`, a threaded function threading its own parameter
#     on) checks clean and its program exits 0 at -O0 and -O2;
#   - illegal.elisa draws exactly expected.txt (one finding per rule, each with the rewrite in
#     the program's own names) and fails the compile;
#   - fixed.elisa (illegal.elisa with each suggested rewrite applied) checks clean and runs.
# stage0 has no value-threading (it rejects writing an immutable parameter), so these are
# stage1-only; value_threading_codegen_smoke.sh runs the `&` twins on stage0.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$ROOT/scripts/elisac_stage1.sh"
FIXTURES="$ROOT/test/fixtures/value_threading"
fail() { printf 'value threading smoke FAILED: %s\n' "$1" >&2; exit 1; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-value-threading-sites.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

check() {
    set +e
    output="$(bash "$WRAPPER" -emit check "$@" 2>&1)"
    status=$?
    set -e
}

for clean in legal fixed; do
    check "$FIXTURES/$clean.elisa"
    [[ "$status" -eq 0 && -z "$output" ]] || fail "$clean.elisa must check clean (exit $status): $output"
    for level in -O0 -O2; do
        bash "$WRAPPER" "$level" -emit exe -o "$WORK/$clean" "$FIXTURES/$clean.elisa" >"$WORK/build.log" 2>&1 || fail "stage1 $level cannot build $clean.elisa: $(cat "$WORK/build.log")"
        "$WORK/$clean" || fail "$clean.elisa ($level) exited $?"
    done
done

check "$FIXTURES/illegal.elisa"
[[ "$status" -ne 0 ]] || fail "illegal.elisa must fail the check: $output"
text="${output//"$FIXTURES/"/}"
[[ "$text" == "$(cat "$FIXTURES/expected.txt")" ]] || fail "illegal.elisa output differs from expected.txt:
$(diff "$FIXTURES/expected.txt" <(printf '%s\n' "$text") || true)"
findings="$(grep -c '^illegal.elisa:' "$FIXTURES/expected.txt" || true)"
[[ "$findings" -eq 5 ]] || fail "expected.txt must hold 5 findings, has $findings"

echo "value threading smoke OK: legal and fixed check clean and run at -O0/-O2, illegal.elisa's $findings findings pinned verbatim"
