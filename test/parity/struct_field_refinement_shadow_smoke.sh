#!/usr/bin/env bash
# Unproven struct field refinements must block object emission. Loop/local shadows cannot inherit
# a same-named refined parameter's fact, while constants and refined parameters remain accepted.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
BAD="$ROOT/test/repro/struct_field_refinement_shadowed_loop.elisa"
BAD_STORE="$ROOT/test/repro/struct_field_refinement_unproven_store.elisa"
BAD_COMPOUND="$ROOT/test/repro/struct_field_refinement_unproven_compound_store.elisa"
BAD_REFINED="$ROOT/test/repro/struct_field_refinement_mismatched_param.elisa"
BAD_UPDATE="$ROOT/test/repro/struct_field_refinement_record_update.elisa"
BAD_STALE_ASSIGN="$ROOT/test/repro/struct_field_refinement_stale_after_assign.elisa"
BAD_STALE_CALL="$ROOT/test/repro/struct_field_refinement_stale_after_call.elisa"
BAD_ALIAS_WRITE="$ROOT/test/repro/struct_field_refinement_stale_after_alias_write.elisa"
GOOD="$ROOT/test/repro/struct_field_refinement_refined_param.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-field-refinement-shadow.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

"$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
"$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

# Matching input and field refinements remain valid on both stages, including a mutable-reference
# store through a parameter whose struct type is wrapped in `mutable` and `&`.
"$STAGE0" -emit obj -O0 -o "$WORK/good-stage0.o" "$GOOD" >"$WORK/good-stage0.log" 2>&1 || {
    cat "$WORK/good-stage0.log" >&2
    exit 1
}
ELISACORE_BIN="$STAGE0" ELISA_STAGE1_BIN="$STAGE1" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit obj -O0 -o "$WORK/good-stage1.o" "$GOOD" >"$WORK/good-stage1.log" 2>&1 || {
        cat "$WORK/good-stage1.log" >&2
        exit 1
    }

reject_stage1() {
    local source="$1"
    local stem="$2"
    if ELISACORE_BIN="$STAGE0" ELISA_STAGE1_BIN="$STAGE1" \
        bash "$ROOT/scripts/elisac_stage1.sh" -emit obj -O0 -o "$WORK/$stem.o" "$source" >"$WORK/$stem.log" 2>&1; then
        printf 'Stage1 emitted an object for an unproven struct field refinement: %s\n' "$source" >&2
        exit 1
    fi
    if [[ -e "$WORK/$stem.o" ]]; then
        printf 'Stage1 left an object behind after rejecting %s\n' "$source" >&2
        exit 1
    fi
    if ! grep -Fq 'where refinement on field "value" of Positive could not be proven statically' "$WORK/$stem.log"; then
        printf 'Stage1 rejected %s without the struct-field refinement diagnostic\n' "$source" >&2
        cat "$WORK/$stem.log" >&2
        exit 1
    fi
}

reject_stage1 "$BAD" "bad-construction"
reject_stage1 "$BAD_STORE" "bad-store"
reject_stage1 "$BAD_COMPOUND" "bad-compound-store"
reject_stage1 "$BAD_REFINED" "bad-mismatched-refinement"
reject_stage1 "$BAD_UPDATE" "bad-record-update"
reject_stage1 "$BAD_STALE_ASSIGN" "bad-stale-after-assign"
reject_stage1 "$BAD_STALE_CALL" "bad-stale-after-call"
reject_stage1 "$BAD_ALIAS_WRITE" "bad-stale-after-alias-write"

echo "struct-field refinement shadow smoke OK: unproven construction, stores, record updates, compound mutations, and stale interval facts are rejected; refined parameters and mutable-reference types are accepted"
