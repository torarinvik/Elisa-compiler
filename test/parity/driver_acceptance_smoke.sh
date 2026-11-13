#!/usr/bin/env bash
# DRIVER-level accept/reject parity in both configurations.
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
# Every disagreement fails. A deliberate Stage1 safety rejection is still reported:
# Stage0 must be fixed rather than making Stage1 accept an unsafe program.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE REPO_ROOT

ACCEPT_TIMEOUT="${ELISA_ACCEPT_TIMEOUT:-300}"
[[ "$ACCEPT_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || { echo "ELISA_ACCEPT_TIMEOUT must be positive" >&2; exit 2; }

# The stage0 selector belongs only to the oracle invocation. Keep it out of the stage1
# wrapper's environment so this test cannot accidentally compile with the installed/default
# compiler or let an oracle-specific path affect the self-hosted product.
stage1_compile() {
    timeout "$ACCEPT_TIMEOUT" env -u ELISACORE_BIN -u ELISA_CORE -u REPO_ROOT \
        ELISA_STAGE1_BIN="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}" \
        ELISA_RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$REPO_ROOT/build/runtime/elisacore_runtime.o}" \
        bash "$REPO_ROOT/scripts/elisac_stage1.sh" "$@"
}

compiler_log_has_crash() {
    # Go runtime crashes use exit 2, just like some ordinary compiler declines.
    # Require both a crash heading and stack evidence, not the exit code alone.
    grep -Eq '^(fatal error: |panic: )' "$1" &&
        grep -Eq '^(runtime stack:|goroutine [0-9]+ )' "$1"
}

compiler_log_has_infrastructure_failure() {
    grep -Eq '^(stage[01] product is stale:|stage[01] provenance cannot be verified:|build incomplete: initial analysis checkpoint saved)' "$1"
}

# WORKER: `--one <mode> <resdir> <src>` compares both drivers on ONE fixture in a private
# temp dir and writes a single result line (`same|ACCEPT-GAP|REJECT-GAP <tab> name <tab> r1`).
# Phase T: the fixture loop was serial (~3 min on the Mac, 45+ min on a loaded 32-core
# host); every fixture is independent, so the driver below fans out with xargs -P.
if [[ "${1:-}" == "--one" ]]; then
    mode="$2"; resdir="$3"; src="$4"
    exec </dev/null
    w="$(mktemp -d "$resdir/case.XXXXXX")"
    probe="$src"
    if [ "$mode" = withstd ]; then
        probe="$w/probe.elisa"
        { printf 'include "%s/elisacore_std/elisacore_runtime.elisa"\n\n' "$REPO_ROOT"; cat "$src"; } > "$probe"
    fi
    timeout "$ACCEPT_TIMEOUT" "$ELISACORE_BIN" -emit obj -o "$w/s0.o" "$probe" >"$w/stage0.compile.log" 2>&1; r0=$?
    stage1_compile -emit obj -o "$w/s1.o" "$probe" >"$w/stage1.compile.log" 2>&1; r1=$?
    a0=$([ "$r0" -eq 0 ] && echo accept || echo reject)
    a1=$([ "$r1" -eq 0 ] && echo accept || echo reject)
    verdict=same
    if [[ "$r0" -ge 124 || "$r1" -ge 124 ]]; then
        verdict=INCONCLUSIVE
    elif { [[ "$r0" -ne 0 ]] && { compiler_log_has_crash "$w/stage0.compile.log" || compiler_log_has_infrastructure_failure "$w/stage0.compile.log"; }; } ||
         { [[ "$r1" -ne 0 ]] && { compiler_log_has_crash "$w/stage1.compile.log" || compiler_log_has_infrastructure_failure "$w/stage1.compile.log"; }; }; then
        verdict=INCONCLUSIVE
    elif [ "$a0" != "$a1" ]; then
        [ "$a0" = reject ] && verdict=ACCEPT-GAP || verdict=REJECT-GAP
    fi
    deliberate=""
    grep -q '^# corpus: deliberate-decline' "$src" && deliberate="deliberate Stage1 rejection"
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$verdict" "$(basename "$src")" "$r1" "$r0" "$w" "$deliberate" > "$resdir/$(basename "$src").res"
    exit 0
fi

source "$REPO_ROOT/test/parity/resolve_elisac.sh"
export ELISACORE_BIN

WORK="$(mktemp -d)"
cleanup_acceptance() {
    local exit_status=$?
    if [[ "$exit_status" -eq 0 ]]; then
        rm -rf "$WORK"
    else
        echo "driver acceptance: failure evidence retained at $WORK" >&2
    fi
}
trap cleanup_acceptance EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
source "$REPO_ROOT/test/parity/host_jobs.sh"
# A long pole: it starts first and sets the gate's makespan, so it takes the wider
# allowance (ELISA_HEAVY_JOBS, exported by run_all) rather than the fair share.
JOBS="${ELISA_ACCEPT_JOBS:-${ELISA_HEAVY_JOBS:-$(elisa_host_jobs)}}"

# Compare both drivers over every fixture. $1 is "bare" or "withstd"; echoes the
# disagreement count and prints one line per disagreement (sorted, so gate logs diff).
compare_all() {
    local mode="$1" disagree=0 accept_gap=0 reject_gap=0 inconclusive=0 processed=0 resdir="$WORK/$1" verdict name r1 r0 logs deliberate note expected actual
    mkdir -p "$resdir"
    expected="$(find "$REPO_ROOT/test/fixtures/diagnostics" -maxdepth 1 -name '*.elisa' -print | wc -l | tr -d '[:space:]')"
    if [ "$expected" -eq 0 ]; then
        echo "  [$mode] INCONCLUSIVE: no diagnostic fixtures found" >&2
        echo "0 0 0 1"
        return
    fi
    if ! find "$REPO_ROOT/test/fixtures/diagnostics" -maxdepth 1 -name '*.elisa' -print0 \
        | xargs -0 -P "$JOBS" -n 1 bash "${BASH_SOURCE[0]}" --one "$mode" "$resdir"; then
        echo "  [$mode] INCONCLUSIVE: a fixture worker failed" >&2
        inconclusive=$((inconclusive + 1))
    fi
    actual="$(find "$resdir" -maxdepth 1 -name '*.res' -print | wc -l | tr -d '[:space:]')"
    if [ "$actual" -ne "$expected" ]; then
        echo "  [$mode] INCONCLUSIVE: $actual results for $expected fixtures" >&2
        inconclusive=$((inconclusive + 1))
    fi
    while IFS=$'\t' read -r verdict name r1 r0 logs deliberate; do
        processed=$((processed + 1))
        if [[ ! "$r0" =~ ^[0-9]+$ || ! "$r1" =~ ^[0-9]+$ || -z "$name" || -z "$logs" ]]; then
            echo "  [$mode] INCONCLUSIVE: malformed fixture result for $name" >&2
            inconclusive=$((inconclusive + 1))
            continue
        fi
        [ "$verdict" = same ] && continue
        if [[ "$verdict" = INCONCLUSIVE ]]; then
            inconclusive=$((inconclusive + 1))
            echo "  [$mode] INCONCLUSIVE $name (stage0=$r0 stage1=$r1; logs=$logs)" >&2
            continue
        fi
        disagree=$((disagree + 1))
        if [ "$verdict" = ACCEPT-GAP ]; then
            accept_gap=$((accept_gap + 1))
            echo "  [$mode] ACCEPT-GAP $name (stage0 exits $r0, stage1 accepts; logs=$logs)" >&2
        else
            reject_gap=$((reject_gap + 1))
            note=""
            [ -z "$deliberate" ] || note="; $deliberate"
            echo "  [$mode] REJECT-GAP $name (stage0 accepts, stage1 exits $r1$note; logs=$logs)" >&2
        fi
    done < <(cat "$resdir"/*.res 2>/dev/null | sort -t $'\t' -k2)
    if [ "$processed" -ne "$expected" ]; then
        echo "  [$mode] INCONCLUSIVE: $processed readable results for $expected fixtures" >&2
        inconclusive=$((inconclusive + 1))
    fi
    echo "$disagree $accept_gap $reject_gap $inconclusive"
}

status=0
for mode in bare withstd; do
    read -r disagree accept_gap reject_gap inconclusive <<< "$(compare_all "$mode")"
    if [[ "$inconclusive" -gt 0 ]]; then
        echo "driver acceptance [$mode] INCONCLUSIVE: $inconclusive timeout/signal/infrastructure exits" >&2
        status=1
    fi
    if [ "$disagree" -gt 0 ]; then
        echo "driver acceptance [$mode] FAILED: $disagree disagreements ($accept_gap accept-gap, $reject_gap reject-gap)" >&2
        status=1
    elif [[ "$inconclusive" -eq 0 ]]; then
        echo "driver acceptance [$mode] OK: no disagreements"
    fi
done
exit $status
