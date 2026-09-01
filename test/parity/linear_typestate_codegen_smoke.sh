#!/usr/bin/env bash
# Stage0/stage1 backend regression for legacy linear typestate declarations.
# The probe must synthesize a constructor, preserve a named constructor argument, and emit the
# transition's hidden aggregate-state mutation without declining any function body.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURE="$ROOT/test/repro/linear_typestate_codegen_probe.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-linear-typestate.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

STAGE0="${ELISACORE_BIN:-${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"

[[ -x "$STAGE0" ]] || { echo "linear typestate smoke SKIP: no stage0 at $STAGE0" >&2; exit 0; }
[[ -x "$STAGE1" ]] || { echo "linear typestate smoke SKIP: no stage1 at $STAGE1" >&2; exit 0; }

"$STAGE0" -emit llvm -o "$WORK/stage0.ll" "$FIXTURE" >/dev/null 2>&1
"$STAGE1" -emit llvm -o "$WORK/stage1.ll" "$FIXTURE" >/dev/null 2>&1

for ir in "$WORK/stage0.ll" "$WORK/stage1.ll"; do
    ! rg -q '!elisa\.declined' "$ir" || {
        echo "linear typestate smoke FAIL: declined body in $ir" >&2
        exit 1
    }
    rg -q 'define .*@__typestate_Ticket_new' "$ir" || {
        echo "linear typestate smoke FAIL: generated constructor missing in $ir" >&2
        exit 1
    }
    rg -q 'call .*@__typestate_Ticket_new' "$ir" || {
        echo "linear typestate smoke FAIL: named Ticket.new call was not lowered in $ir" >&2
        exit 1
    }
    rg -q 'store i64 1' "$ir" || {
        echo "linear typestate smoke FAIL: redeem transition did not store Used state in $ir" >&2
        exit 1
    }
done

echo "linear typestate codegen OK: stage0 and stage1 synthesize named constructors and transitions"
