#!/usr/bin/env bash
# A loop binder must not inherit a same-named parameter's where-refinement fact.
# `PreconditionUnproven` is a warning-level semantic diagnostic, so inspect the semantic
# reporter instead of treating ordinary object compilation as a rejection oracle.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
BAD="$ROOT/test/repro/struct_field_refinement_shadowed_loop.elisa"
GOOD="$ROOT/test/repro/struct_field_refinement_refined_param.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-field-refinement-shadow.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

"$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
"$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

REPO_ROOT="$ROOT"
ELISA_STAGE1_BIN="$STAGE1"
source "$ROOT/test/parity/build_parse_report.sh"

# Matching input and field refinements remain a valid construction on both stages.
"$STAGE0" -emit obj -O0 -o "$WORK/good-stage0.o" "$GOOD" >"$WORK/good-stage0.log" 2>&1 || {
    cat "$WORK/good-stage0.log" >&2
    exit 1
}
ELISACORE_BIN="$STAGE0" ELISA_STAGE1_BIN="$STAGE1" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit obj -O0 -o "$WORK/good-stage1.o" "$GOOD" >"$WORK/good-stage1.log" 2>&1 || {
        cat "$WORK/good-stage1.log" >&2
        exit 1
    }

bad_report="$("$RPT" < "$BAD")"
if ! grep -Fq 'precondition of "where refinement on field" could not be proven statically at this call' <<<"$bad_report"; then
    printf 'shadowed field refinement warning was not reported\n%s\n' "$bad_report" >&2
    exit 1
fi

good_report="$("$RPT" < "$GOOD")"
if grep -Fq 'precondition of "where refinement on field" could not be proven statically at this call' <<<"$good_report"; then
    printf 'matching refined parameter was reported as unproven\n%s\n' "$good_report" >&2
    exit 1
fi

echo "struct-field refinement shadow smoke OK: loop shadowing is reported; matching refined parameters remain accepted"
