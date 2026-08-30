#!/usr/bin/env bash
# Explicit guards for the two historical regressions named by run_all.sh:
# the literal-comparison false positive and the machine-from payload-binding crash.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
export ELISA_CORE
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "historical regression guard FAIL: $1" >&2; exit 1; }

pos="$REPO_ROOT/test/fixtures/diagnostics/literal_comparison_impossible.pos.elisa"
neg="$REPO_ROOT/test/fixtures/diagnostics/literal_comparison_impossible.neg.elisa"
[ -f "$pos" ] || fail "missing literal-comparison positive fixture"
[ -f "$neg" ] || fail "missing literal-comparison negative fixture"

out=$("$RPT" < "$pos")
echo "$out" | grep -q "comparison is always vacuous" || fail "literal-comparison positive no longer fires: $out"
out=$("$RPT" < "$neg")
echo "$out" | grep -q "comparison is always vacuous" && fail "literal-comparison negative false positive: $out"

bash "$REPO_ROOT/test/parity/machine_from_smoke.sh" >/tmp/stage1_machine_from_regression.$$.log 2>&1 || {
    tail -5 /tmp/stage1_machine_from_regression.$$.log >&2
    fail "machine-from payload-binding regression"
}
rm -f /tmp/stage1_machine_from_regression.$$.log
echo "historical regression guards OK: literal comparison FP + machine-from payload binding"
