#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
RUNTIME="$ROOT/build/runtime/elisacore_runtime.o"
BAD="$ROOT/test/repro/rejected_region_new_darray_value.elisa"
BAD_CONDITIONAL="$ROOT/test/fixtures/semantic/adversarial_escape/region_new_conditional_darray_value.neg.elisa"
BAD_ASSIGNMENT="$ROOT/test/fixtures/semantic/adversarial_escape/region_new_darray_assignment.neg.elisa"
BAD_RETURN="$ROOT/test/fixtures/semantic/adversarial_escape/region_new_darray_return.neg.elisa"
BAD_ALIAS="$ROOT/test/fixtures/semantic/adversarial_escape/region_new_darray_alias_value.neg.elisa"
BAD_SVIEW="$ROOT/test/fixtures/semantic/adversarial_escape/region_new_sview_value.neg.elisa"
NEW_REF="$ROOT/test/fixtures/semantic/adversarial_escape/region_new_reference.pos.elisa"
PINNED_VALUE="$ROOT/test/repro/region_pinned_darray_value.elisa"
BY_VALUE_AUTO_READ="$ROOT/test/repro/region_new_by_value_auto_read.elisa"
SCALAR_AUTO_READ="$ROOT/test/repro/region_new_scalar_auto_read.elisa"
STRUCT_FIELD_AUTO_READ="$ROOT/test/repro/region_new_struct_field_auto_read.elisa"
DARRAY_ELEMENT_AUTO_READ="$ROOT/test/repro/region_new_darray_element_auto_read.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-region-new-soundness.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT

[[ -x "$STAGE0" ]] || { echo "missing Stage0 compiler: $STAGE0" >&2; exit 2; }
[[ -x "$ROOT/bin/elisac-stage1" ]] || { echo "missing Stage1 product; run scripts/elisac_stage1.sh --seed" >&2; exit 2; }
[[ -f "$RUNTIME" ]] || { echo "missing Stage1 runtime object: $RUNTIME" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"

reject_invalid_reference_as_value() {
    local compiler="$1" stage="$2" source="$3" expected_pattern="$4"
    local label="$5"
    if [[ "$stage" == "stage0" ]]; then
        if "$compiler" -emit obj -O0 -o "$WORK/$stage-$label.o" "$source" >"$WORK/$stage-$label.log" 2>&1; then
            echo "FAIL $stage accepted new[r] reference as a darray value" >&2
            exit 1
        fi
    else
        if bash "$compiler" -emit obj -O0 -o "$WORK/$stage-$label.o" "$source" >"$WORK/$stage-$label.log" 2>&1; then
            echo "FAIL $stage accepted new[r] reference as a darray value" >&2
            exit 1
        fi
    fi
    if ! rg -q "$expected_pattern" "$WORK/$stage-$label.log"; then
        echo "FAIL $stage did not reject $label with the expected darray type diagnostic" >&2
        rg -v 'warning:' "$WORK/$stage-$label.log" | head -5 >&2 || true
        exit 1
    fi
}

run_valid_case() {
    local source="$1" name="$2" opt="$3" stage compiler
    for stage in stage0 stage1; do
        compiler="$STAGE0"
        if [[ "$stage" == "stage1" ]]; then compiler="$STAGE1"; fi
        if [[ "$stage" == "stage0" ]]; then
            "$compiler" -emit obj "-$opt" -o "$WORK/$name-$stage-$opt.o" "$source" >"$WORK/$name-$stage-$opt.log" 2>&1
        else
            bash "$compiler" -emit obj "-$opt" -o "$WORK/$name-$stage-$opt.o" "$source" >"$WORK/$name-$stage-$opt.log" 2>&1
        fi
        if [[ "$stage" == "stage0" ]]; then
            if ! clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$WORK/$name-$stage-$opt" "$WORK/$name-$stage-$opt.o" >>"$WORK/$name-$stage-$opt.log" 2>&1; then
                clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$WORK/$name-$stage-$opt" "$WORK/$name-$stage-$opt.o" "$RUNTIME" >>"$WORK/$name-$stage-$opt.log" 2>&1
            fi
        else
            clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$WORK/$name-$stage-$opt" "$WORK/$name-$stage-$opt.o" "$RUNTIME" >>"$WORK/$name-$stage-$opt.log" 2>&1
        fi
        "$WORK/$name-$stage-$opt"
    done
}

reject_invalid_reference_as_value "$STAGE0" stage0 "$BAD" 'variable "generated" expects darray.*got' initializer
reject_invalid_reference_as_value "$STAGE1" stage1 "$BAD" 'variable "generated" expects darray.*got' initializer
reject_invalid_reference_as_value "$STAGE0" stage0 "$BAD_CONDITIONAL" 'variable "values" expects darray.*got' conditional
reject_invalid_reference_as_value "$STAGE1" stage1 "$BAD_CONDITIONAL" 'variable "values" expects darray.*got' conditional
reject_invalid_reference_as_value "$STAGE0" stage0 "$BAD_ASSIGNMENT" 'cannot assign .* to darray' assignment
reject_invalid_reference_as_value "$STAGE1" stage1 "$BAD_ASSIGNMENT" 'darray.*(got|reference|mutable)' assignment
reject_invalid_reference_as_value "$STAGE0" stage0 "$BAD_RETURN" 'return type expects darray.*got' return
reject_invalid_reference_as_value "$STAGE1" stage1 "$BAD_RETURN" 'darray.*(got|reference|mutable)' return
reject_invalid_reference_as_value "$STAGE0" stage0 "$BAD_ALIAS" 'variable "copy" expects darray.*got' alias
reject_invalid_reference_as_value "$STAGE1" stage1 "$BAD_ALIAS" 'variable "copy" expects darray.*got' alias
reject_invalid_reference_as_value "$STAGE0" stage0 "$BAD_SVIEW" 'variable "view" expects sview.*got' sview
reject_invalid_reference_as_value "$STAGE1" stage1 "$BAD_SVIEW" 'variable "view" expects sview.*got' sview
for opt in O0 O2; do
    run_valid_case "$NEW_REF" new-reference "$opt"
    run_valid_case "$PINNED_VALUE" pinned-value "$opt"
    run_valid_case "$BY_VALUE_AUTO_READ" by-value-auto-read "$opt"
    run_valid_case "$SCALAR_AUTO_READ" scalar-auto-read "$opt"
    run_valid_case "$STRUCT_FIELD_AUTO_READ" struct-field-auto-read "$opt"
    run_valid_case "$DARRAY_ELEMENT_AUTO_READ" darray-element-auto-read "$opt"
done
echo "region new/darray soundness OK (Stage0 and Stage1; O0/O2)"
