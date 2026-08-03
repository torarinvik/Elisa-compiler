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
run_one "stage0 parser reference inventory"        "$REPO_ROOT/test/parity/parser_reference_inventory_smoke.sh"
run_one "parser acceptance parity (stage1 == stage0)" "$REPO_ROOT/test/parity/parser_acceptance_diff.sh"
run_one "semantic acceptance parity (stage1 == stage0)" "$REPO_ROOT/test/parity/semantic_acceptance_diff.sh"
run_one "diagnostics message parity (stage1 covers stage0)" "$REPO_ROOT/test/parity/diagnostics_diff.sh"
run_one "internal-suite differential (ratchet)" "$REPO_ROOT/test/parity/semantic_internal_diff.sh"
run_one "optimisation pipeline answer parity" "$REPO_ROOT/test/parity/opt_pipeline_smoke.sh"
run_one "-emit tokens byte parity" "$REPO_ROOT/test/parity/emit_tokens_parity_smoke.sh"
run_one "-emit ast byte parity" "$REPO_ROOT/test/parity/emit_ast_parity_smoke.sh"
run_one "-emit deps byte parity" "$REPO_ROOT/test/parity/emit_deps_parity_smoke.sh"
# The only check that compares ANSWERS rather than acceptance: compile a corpus of real
# programs with both compilers, RUN both, require the same exit code. Every other check
# here would pass a stage1 that compiles everything and computes the wrong result — as it
# did for `.uintptr()` on a ref, through a green gate and a byte-identical gen3 fixpoint.
run_one "behavioural differential corpus (ratchet)" "$REPO_ROOT/test/parity/differential_corpus.sh"
run_one "diagnostic breadth baseline"              "$REPO_ROOT/test/breadth/run.sh" --baseline "$REPO_ROOT/test/fixtures/diagnostics.baseline.tsv" "$REPO_ROOT/test/fixtures/diagnostics"

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
