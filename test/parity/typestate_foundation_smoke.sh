#!/usr/bin/env bash
# Paired soundness controls for the typestate cleanup. Rejecting a fixture for
# a backend decline is not a passing semantic rejection.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-typestate-foundation.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

for compiler in "$STAGE0" "$STAGE1"; do
    [[ -x "$compiler" ]] || { echo "typestate foundation: missing compiler $compiler" >&2; exit 1; }
    for fixture in derived_contextual_constructor.pos typestate_for_preserve.pos typestate_match_join.pos; do
        elisa_run_timeout 30 "$compiler" -emit llvm -o "$WORK/positive.ll" \
            "$ROOT/test/fixtures/diagnostics/$fixture.elisa" >"$WORK/compile.log" 2>&1 || {
            cat "$WORK/compile.log" >&2
            exit 1
        }
        ! rg -q '!elisa\.declined' "$WORK/positive.ll" || { echo "typestate foundation: declined positive $fixture" >&2; exit 1; }
    done
    for fixture in derived_contextual_constructor.neg typestate_for_zero_iteration.neg typestate_match_join.neg typestate_match_arm_entry.neg; do
        set +e
        elisa_run_timeout 30 "$compiler" -emit llvm -o "$WORK/negative.ll" \
            "$ROOT/test/fixtures/diagnostics/$fixture.elisa" >"$WORK/reject.log" 2>&1
        status=$?
        set -e
        [[ "$status" -eq 1 ]] || { echo "typestate foundation: expected semantic rejection for $fixture, got $status" >&2; cat "$WORK/reject.log" >&2; exit 1; }
        if [[ "$fixture" == derived_contextual_constructor.neg ]]; then
            rg -q 'does not satisfy derived state Open' "$WORK/reject.log"
        else
            rg -q 'read_file' "$WORK/reject.log"
        fi
    done
    elisa_run_timeout 30 "$compiler" -emit llvm -o "$WORK/state-call-positive.ll" \
        "$ROOT/test/repro/named_protocol_state_call_compatible.pos.elisa" >"$WORK/compile.log" 2>&1 || {
        cat "$WORK/compile.log" >&2
        exit 1
    }
    ! rg -q '!elisa\.declined' "$WORK/state-call-positive.ll" || {
        echo "typestate foundation: declined compatible named-state call" >&2
        exit 1
    }
    set +e
    elisa_run_timeout 30 "$compiler" -emit llvm -o "$WORK/state-call-negative.ll" \
        "$ROOT/test/repro/named_protocol_state_call_mismatch.neg.elisa" >"$WORK/reject.log" 2>&1
    state_call_status=$?
    set -e
    [[ "$state_call_status" -eq 1 ]] || {
        echo "typestate foundation: expected wrong named-state call rejection, got $state_call_status" >&2
        cat "$WORK/reject.log" >&2
        exit 1
    }
    rg -q 'expects (Snapshot\[Observed\], got Snapshot\[Running\]|the subject in typestate Observed)' "$WORK/reject.log" || {
        echo "typestate foundation: wrong named-state call lacked its semantic diagnostic" >&2
        cat "$WORK/reject.log" >&2
        exit 1
    }
    elisa_run_timeout 30 "$compiler" -emit llvm -o "$WORK/named.ll" \
        "$ROOT/test/repro/named_typestate_codegen_probe.elisa" >"$WORK/compile.log" 2>&1 || {
        cat "$WORK/compile.log" >&2
        exit 1
    }
    ! rg -q '!elisa\.declined' "$WORK/named.ll" || { echo "typestate foundation: declined named-state body" >&2; exit 1; }
    rg -q '^%ProtocolFile(__Open)? = type \{ i1 \}$' "$WORK/named.ll" || {
        echo "typestate foundation: named state changed the single-bool struct layout" >&2
        exit 1
    }
    for optimization in 0 2; do
        emit_mode=exe
        output="$WORK/named"
        if [[ "$compiler" == "$STAGE0" ]]; then
            emit_mode=c-archive
            output="$WORK/named.a"
        fi
        elisa_run_timeout 30 "$compiler" -emit "$emit_mode" "-O$optimization" -o "$output" \
            "$ROOT/test/repro/named_typestate_codegen_probe.elisa" >"$WORK/compile.log" 2>&1 || {
            cat "$WORK/compile.log" >&2
            exit 1
        }
        if [[ "$compiler" == "$STAGE0" ]]; then
            elisa_run_timeout 30 "${ELISA_CLANG:-clang}" -Wl,-dead_strip -o "$WORK/named" "$output" >"$WORK/link.log" 2>&1 || {
                cat "$WORK/link.log" >&2
                exit 1
            }
        fi
        elisa_run_timeout 10 "$WORK/named"
    done
done
echo "typestate foundation OK: contextual construction, loop/match joins, named-state construction/borrows at O0/O2"
