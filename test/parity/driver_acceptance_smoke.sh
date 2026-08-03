#!/usr/bin/env bash
# DRIVER-level accept/reject parity, RATCHETED.
#
# Every other semantic check in this gate measures the ANALYZER through test/breadth's
# parse_report. None of them measures what the DRIVER actually does with the analyzer's
# findings, and that gap hid a real divergence: stage1 compiled `a: u8 = 300` to an object
# while stage0 exited 1. The analyzer had reported it correctly the whole time — the
# driver's gate rejects on severity 1 only, and that kind was severity 0.
#
# semantic_gate_selfhost_smoke.sh compares two DRIVERS but only asserts both exit 0 on the
# compiler's own source, so it cannot see a MISSING rejection. This check can: it runs both
# compilers over every diagnostics fixture and compares the accept/reject DECISION.
#
# The baseline is the count of fixtures where they still disagree. Going above it fails;
# lowering it is a one-line commit. The standing split (2026-08-03) is
#   1  stage0 rejects / stage1 accepts — contract_ensure_result_void.neg carries a `# smt`
#      replay header; the driver passes enable_smt=false, and SMT is out of scope
#      (docs/stage1_scope.md).
#  17  stage0 accepts / stage1 rejects — all exit 2, a CODEGEN decline on a shape the
#      compiler itself never uses (array literals, affine collections, tuple/or patterns,
#      structural params). Each is a backend gap, not a policy choice.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

BASELINE_FILE="$REPO_ROOT/test/fixtures/driver_acceptance.baseline"
baseline="$(tr -d '[:space:]' < "$BASELINE_FILE")"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

disagree=0
accept_gap=0
reject_gap=0
for src in "$REPO_ROOT"/test/fixtures/diagnostics/*.elisa; do
    "$ELISACORE_BIN" -emit obj -o "$WORK/s0.o" "$src" >/dev/null 2>&1
    r0=$?
    bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit obj -o "$WORK/s1.o" "$src" >/dev/null 2>&1
    r1=$?
    a0=$([ "$r0" -eq 0 ] && echo accept || echo reject)
    a1=$([ "$r1" -eq 0 ] && echo accept || echo reject)
    [ "$a0" = "$a1" ] && continue
    disagree=$((disagree + 1))
    if [ "$a0" = reject ]; then
        accept_gap=$((accept_gap + 1))
        echo "  ACCEPT-GAP $(basename "$src") (stage0 rejects, stage1 accepts)"
    else
        reject_gap=$((reject_gap + 1))
        echo "  REJECT-GAP $(basename "$src") (stage0 accepts, stage1 exits $r1)"
    fi
done

if [ "$disagree" -gt "$baseline" ]; then
    echo "driver acceptance FAILED: $disagree disagreements, ratchet allows <= $baseline" >&2
    exit 1
fi
echo "driver acceptance OK: $disagree disagreements (ratchet $baseline) — $accept_gap accept-gap, $reject_gap reject-gap"
