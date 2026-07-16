#!/usr/bin/env bash
# The stage1 parity gate: run EVERY test/parity/*_smoke.sh plus the two standing
# invariants (self-hostable 0 unresolved across the frontend, and lexer token parity
# stage1 == stage0). Exists because the smoke scripts were previously ungated — no target
# ran them, so a regression could rot silently (see the "test tree never gated" lesson).
# One green run here means every stage1-owned guarantee still holds.
#
# As of 2026-07-14 the gate is FULLY GREEN — no known failures (the earlier machine_from
# nested-binding SIGBUS and the diagnostics literal_comparison_impossible FP are both fixed).
# It now also runs flow_strict_census_smoke.sh (docs/125 step 15 graduation): the strict
# block-`if` ban is a gate-enforced standard — the compiler's src + std stay at 0 block-`if`s.
#
#   Usage:  ELISA_CORE=/path/to/Elisa-core  test/parity/run_all.sh
#           (ELISA_CORE defaults to ../../Go projects/Elisa-core)
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"

pass=0
fail=0
failed_names=()

run_one() {
  local name="$1"; shift
  if bash "$@" >/tmp/stage1_gate.$$.log 2>&1; then
    printf '  ok   %s\n' "$name"
    pass=$((pass + 1))
  else
    printf '  FAIL %s\n' "$name"
    tail -3 /tmp/stage1_gate.$$.log | sed 's/^/       /'
    fail=$((fail + 1))
    failed_names+=("$name")
  fi
}

echo "stage1 parity gate — standing invariants:"
# Runtime drift guard: the vendored elisacore_std must stay byte-identical to Elisa-core's
# canonical copy (README "Single source of truth"). Reconciled 2026-07-15 (backlog item 9):
# the docs/125 postfix-guard remodel was adopted into Elisa-core's canonical runtime and
# re-vendored core->stage1; the 6 apparent content diffs were all semantically-identical
# remodels (test.elisa now routes asserts through the existing fail() helper; the collections
# trusted-Alias/UncheckedIndex wrappers are redundant under stdlib trust; concurrency was a
# ternary collapse). The mirror is byte-identical again, so this guard now runs.
run_one "runtime drift guard (elisacore_std in sync)" "$REPO_ROOT/scripts/check_runtime_drift.sh"
run_one "self-hostable (0 unresolved / 132 files)" "$REPO_ROOT/test/parity/check_self_hostable.sh"
run_one "lexer parity (stage1 == stage0)"          "$REPO_ROOT/test/parity/run_parity.sh"

echo "stage1 parity gate — behavioral smokes:"
for smoke in "$REPO_ROOT"/test/parity/*_smoke.sh; do
  run_one "$(basename "$smoke")" "$smoke"
done

rm -f /tmp/stage1_gate.$$.log
echo "----------------------------------------"
if [[ $fail -eq 0 ]]; then
  echo "stage1 parity gate OK: $pass checks passed"
  exit 0
fi
echo "stage1 parity gate FAILED: $fail of $((pass + fail)) checks failed:"
printf '  - %s\n' "${failed_names[@]}"
exit 1
