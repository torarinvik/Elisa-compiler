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

# The stage0 selector belongs only to the oracle invocation. Keep it out of the stage1
# wrapper's environment so this test cannot accidentally compile with the installed/default
# compiler or let an oracle-specific path affect the self-hosted product.
stage1_compile() {
    env -u ELISACORE_BIN -u ELISA_CORE -u REPO_ROOT \
        ELISA_STAGE1_BIN="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}" \
        ELISA_RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$REPO_ROOT/build/runtime/elisacore_runtime.o}" \
        bash "$REPO_ROOT/scripts/elisac_stage1.sh" "$@"
}

# WORKER: `--one <mode> <resdir> <src>` compares both drivers on ONE fixture in a private
# temp dir and writes a single result line (`same|ACCEPT-GAP|REJECT-GAP <tab> name <tab> r1`).
# Phase T: the fixture loop was serial (~3 min on the Mac, 45+ min on a loaded 32-core
# host); every fixture is independent, so the driver below fans out with xargs -P.
if [[ "${1:-}" == "--one" ]]; then
    mode="$2"; resdir="$3"; src="$4"
    exec </dev/null
    w="$(mktemp -d)"; trap 'rm -rf "$w"' EXIT INT TERM HUP
    probe="$src"
    if [ "$mode" = withstd ]; then
        probe="$w/probe.elisa"
        { printf 'include "%s/elisacore_std/elisacore_runtime.elisa"\n\n' "$REPO_ROOT"; cat "$src"; } > "$probe"
    fi
    "$ELISACORE_BIN" -emit obj -o "$w/s0.o" "$probe" >/dev/null 2>&1; r0=$?
    stage1_compile -emit obj -o "$w/s1.o" "$probe" >/dev/null 2>&1; r1=$?
    a0=$([ "$r0" -eq 0 ] && echo accept || echo reject)
    a1=$([ "$r1" -eq 0 ] && echo accept || echo reject)
    verdict=same
    if [ "$a0" != "$a1" ]; then
        [ "$a0" = reject ] && verdict=ACCEPT-GAP || verdict=REJECT-GAP
    fi
    printf '%s\t%s\t%s\n' "$verdict" "$(basename "$src")" "$r1" > "$resdir/$(basename "$src").res"
    exit 0
fi

source "$REPO_ROOT/test/parity/resolve_elisac.sh"
export ELISACORE_BIN

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
source "$REPO_ROOT/test/parity/host_jobs.sh"
# A long pole: it starts first and sets the gate's makespan, so it takes the wider
# allowance (ELISA_HEAVY_JOBS, exported by run_all) rather than the fair share.
JOBS="${ELISA_ACCEPT_JOBS:-${ELISA_HEAVY_JOBS:-$(elisa_host_jobs)}}"

# Compare both drivers over every fixture. $1 is "bare" or "withstd"; echoes the
# disagreement count and prints one line per disagreement (sorted, so gate logs diff).
compare_all() {
    local mode="$1" disagree=0 accept_gap=0 reject_gap=0 resdir="$WORK/$1" verdict name r1
    mkdir -p "$resdir"
    # A fixture carrying `# corpus: deliberate-decline` is a program stage0 accepts and stage1
    # rejects ON PURPOSE (a stage0 unsoundness stage1 closes, e.g. a view of a frame-local
    # array escaping via return) -- the same exclusion the differential corpus applies.
    while IFS= read -r -d '' fixture; do
        grep -q '^# corpus: deliberate-decline' "$fixture" || printf '%s\0' "$fixture"
    done < <(find "$REPO_ROOT/test/fixtures/diagnostics" -maxdepth 1 -name '*.elisa' -print0) \
        | xargs -0 -P "$JOBS" -n 1 bash "${BASH_SOURCE[0]}" --one "$mode" "$resdir"
    while IFS=$'\t' read -r verdict name r1; do
        [ "$verdict" = same ] && continue
        disagree=$((disagree + 1))
        if [ "$verdict" = ACCEPT-GAP ]; then
            accept_gap=$((accept_gap + 1))
            echo "  [$mode] ACCEPT-GAP $name (stage0 rejects, stage1 accepts)" >&2
        else
            reject_gap=$((reject_gap + 1))
            echo "  [$mode] REJECT-GAP $name (stage0 accepts, stage1 exits $r1)" >&2
        fi
    done < <(cat "$resdir"/*.res 2>/dev/null | sort -t $'\t' -k2)
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
