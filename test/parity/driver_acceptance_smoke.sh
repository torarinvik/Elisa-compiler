#!/usr/bin/env bash
# DRIVER-level accept/reject parity, RATCHETED, in BOTH configurations.
#
# Every other semantic check in this gate measures the ANALYZER through test/breadth's
# parse_report. None of them measures what the DRIVER does with the analyzer's findings,
# and that gap hid a real divergence: stage1 compiled `a: u8 = 300` to an object while
# stage0 exited 1. The analyzer had reported it correctly the whole time — the driver's
# gate rejects on severity 1 only, and that kind was severity 0.
#
# semantic_gate_selfhost_smoke.sh compares two DRIVERS but only asserts both exit 0 on the
# compiler's own source, so it cannot see a MISSING rejection. This check can.
#
# TWO CONFIGURATIONS, because neither alone is honest:
#
#   BARE — the fixture as written. stage0 has the container and aggregate machinery built
#   INTO the compiler; stage1 lowers `dict`/`set`/tuples to definitions that live in
#   elisacore_std. A fixture with no `include` therefore has nothing for stage1 to lower
#   TO, and 13 fixtures exited 2 for that reason alone — an architectural difference
#   counted thirteen times, not thirteen backend bugs. Kept because a regression here is
#   still a regression, and because it is cheap (~20s).
#
#   WITH-STD — the same fixture behind the std, which is how every real program is
#   compiled (the wrapper resolves includes). This is the configuration that reflects
#   supported use, and it sees things BARE cannot: `for x in []:` agreed in BARE only
#   because the function was DECLINED, masking a severity that should have rejected it.
#   Costs ~3 min.
#
# Each baseline is the count of fixtures where the two compilers still disagree. Going
# above it fails; lowering it is a one-line commit. The standing WITH-STD split
# (2026-08-03) is 3 accept-gap / 0 reject-gap:
#   contract_ensure_result_void.neg — carries a `# smt` replay header the driver does not
#     honour; SMT is out of scope (docs/stage1_scope.md).
#   container_comparison.neg — `xs == ys` on two darrays. stage0 does not diagnose it
#     either: it emits invalid IR and LLVM rejects it ("Invalid operand types for ICmp").
#     stage1 DECLINES the function, so the file still compiles when the std supplies other
#     symbols. Neither compiler handles it; the shapes of the refusal differ.
#   dict_index_key_mismatch.neg — stage0 reports "cannot assign int to mutable i64&?" on
#     `xs[0] <- 9`; stage1's analyzer reports nothing. A genuinely MISSING diagnostic.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

# The stage0 selector belongs only to the oracle invocation. Keep it out of the stage1
# wrapper's environment so this test cannot accidentally compile with the installed/default
# compiler or let an oracle-specific path affect the self-hosted product.
stage1_compile() {
    env -u ELISACORE_BIN -u ELISA_CORE -u REPO_ROOT \
        ELISA_STAGE1_BIN="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}" \
        ELISA_RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$REPO_ROOT/build/runtime/elisacore_runtime.o}" \
        bash "$REPO_ROOT/scripts/elisac_stage1.sh" "$@"
}

# Compare both drivers over every fixture. $1 is "bare" or "withstd"; echoes the
# disagreement count and prints one line per disagreement.
compare_all() {
    local mode="$1" disagree=0 accept_gap=0 reject_gap=0 src probe r0 r1 a0 a1
    for src in "$REPO_ROOT"/test/fixtures/diagnostics/*.elisa; do
        probe="$src"
        if [ "$mode" = withstd ]; then
            probe="$WORK/probe.elisa"
            { printf 'include "%s/elisacore_std/elisacore_runtime.elisa"\n\n' "$REPO_ROOT"; cat "$src"; } > "$probe"
        fi
        "$ELISACORE_BIN" -emit obj -o "$WORK/s0.o" "$probe" >/dev/null 2>&1
        r0=$?
        stage1_compile -emit obj -o "$WORK/s1.o" "$probe" >/dev/null 2>&1
        r1=$?
        a0=$([ "$r0" -eq 0 ] && echo accept || echo reject)
        a1=$([ "$r1" -eq 0 ] && echo accept || echo reject)
        [ "$a0" = "$a1" ] && continue
        disagree=$((disagree + 1))
        if [ "$a0" = reject ]; then
            accept_gap=$((accept_gap + 1))
            echo "  [$mode] ACCEPT-GAP $(basename "$src") (stage0 rejects, stage1 accepts)" >&2
        else
            reject_gap=$((reject_gap + 1))
            echo "  [$mode] REJECT-GAP $(basename "$src") (stage0 accepts, stage1 exits $r1)" >&2
        fi
    done
    echo "$disagree $accept_gap $reject_gap"
}

status=0
for mode in bare withstd; do
    baseline_file="$REPO_ROOT/test/fixtures/driver_acceptance_${mode}.baseline"
    baseline="$(tr -d '[:space:]' < "$baseline_file")"
    read -r disagree accept_gap reject_gap <<< "$(compare_all "$mode")"
    if [ "$disagree" -gt "$baseline" ]; then
        echo "driver acceptance [$mode] FAILED: $disagree disagreements, ratchet allows <= $baseline" >&2
        status=1
    else
        echo "driver acceptance [$mode] OK: $disagree disagreements (ratchet $baseline) — $accept_gap accept-gap, $reject_gap reject-gap"
    fi
done
exit $status
