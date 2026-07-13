#!/usr/bin/env bash
# The stage1 parity gate: run EVERY test/parity/*_smoke.sh plus the two standing
# invariants (self-hostable 0 unresolved across the frontend, and lexer token parity
# stage1 == stage0). Exists because the smoke scripts were previously ungated — no target
# ran them, so a regression could rot silently (see the "test tree never gated" lesson).
# One green run here means every stage1-owned guarantee still holds.
#
# KNOWN pre-existing failures (NOT regressions — present before the docs/125 step-13
# refusal work; a green delta means "no NEW failures"):
#   - machine_from_smoke.sh — the machine-from nested-binding SIGBUS (region/codegen).
#   - diagnostics_smoke.sh — literal_comparison_impossible.neg false-positive (1/52).
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
