#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-effect-handler.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

if [[ ! -x "$STAGE1" ]]; then
    echo "effect_handler_stage1_smoke SKIP: no stage1 seed at $STAGE1"
    exit 0
fi

run_positive() {
    local fixture="$1"
    local stem="$(basename "$fixture" .elisa)"
    "$ROOT/scripts/elisac_stage1.sh" \
        -emit obj \
        -target-triple wasm32-unknown-unknown \
        -o "$WORK/$stem.o" \
        "$ROOT/test/fixtures/effects/$fixture" \
        >"$WORK/$stem.log" 2>&1 || {
        echo "effect compilation failed for $fixture" >&2
        sed -n '1,80p' "$WORK/$stem.log" >&2
        return 1
    }
    [[ -s "$WORK/$stem.o" ]] || {
        echo "effect handler output is empty for $fixture" >&2
        exit 1
    }
}

run_zero_overhead_ir() {
    local fixture="$1"
    local stem="$(basename "$fixture" .elisa)"
    "$ROOT/scripts/elisac_stage1.sh" \
        -emit llvm \
        -target-triple wasm32-unknown-unknown \
        -o "$WORK/$stem.ll" \
        "$ROOT/test/fixtures/effects/$fixture" \
        >"$WORK/$stem-llvm.log" 2>&1 || {
        echo "effect LLVM compilation failed for $fixture" >&2
        sed -n '1,80p' "$WORK/$stem-llvm.log" >&2
        return 1
    }
    grep -Eq 'call( [^@]*)?@([A-Za-z0-9_]+\.)?__handler__' "$WORK/$stem.ll" || {
        echo "expected a direct hidden-handler call in LLVM for $fixture" >&2
        sed -n '1,120p' "$WORK/$stem.ll" >&2
        exit 1
    }
    if grep -Eiq 'effect(_|\.)?(handler|dispatch|install)|continuation|resume' "$WORK/$stem.ll"; then
        echo "found runtime effect machinery in zero-overhead LLVM for $fixture" >&2
        exit 1
    fi
}

run_negative() {
    local fixture="$1"
    local expected="$2"
    local stem="$(basename "$fixture" .elisa)"
    if "$ROOT/scripts/elisac_stage1.sh" \
        -emit obj \
        -target-triple wasm32-unknown-unknown \
        -o "$WORK/$stem.o" \
        "$ROOT/test/fixtures/effects/$fixture" \
        >"$WORK/$stem.log" 2>&1; then
        echo "expected effect diagnostic for $fixture" >&2
        exit 1
    fi
    grep -Fq "$expected" "$WORK/$stem.log" || {
        echo "missing expected diagnostic for $fixture: $expected" >&2
        sed -n '1,40p' "$WORK/$stem.log" >&2
        exit 1
    }
}

# These fixtures return distinct values so a wrong handler/module or swapped capture
# can no longer pass merely because code generation succeeded.
run_native_result() {
    local fixture="$1" expected="$2"
    local stem="$(basename "$fixture" .elisa)"
    local clang="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
    if [[ ! -x "$clang" ]]; then
        echo "native effect check SKIP: clang unavailable for $fixture"
        return
    fi
    "$ROOT/scripts/elisac_stage1.sh" -emit obj -o "$WORK/$stem-native.o" \
        "$ROOT/test/fixtures/effects/$fixture" >"$WORK/$stem-native.log" 2>&1
    "$clang" "$WORK/$stem-native.o" -o "$WORK/$stem-native"
    local actual=0
    "$WORK/$stem-native" || actual=$?
    [[ "$actual" == "$expected" ]] || {
        echo "wrong effect result for $fixture: expected $expected, got $actual" >&2
        exit 1
    }
}

run_direct_equivalence() {
    local llvm_diff="${ELISA_LLVM_DIFF:-/opt/homebrew/opt/llvm/bin/llvm-diff}"
    local stem
    for stem in helper_equivalence helper_equivalence_manual helper_generic_equivalence helper_generic_equivalence_manual; do
        "$ROOT/scripts/elisac_stage1.sh" -O2 -emit llvm \
            -target-triple wasm32-unknown-unknown -o "$WORK/$stem.ll" \
            "$ROOT/test/fixtures/effects/$stem.elisa" >"$WORK/$stem.log" 2>&1 || {
            sed -n '1,80p' "$WORK/$stem.log" >&2
            return 1
        }
        grep -Eq '^define .*@calculate\(' "$WORK/$stem.ll" || {
            echo "missing runtime-input equivalence function in $stem" >&2
            return 1
        }
        "$ROOT/scripts/elisac_stage1.sh" -O2 -emit obj \
            -target-triple wasm32-unknown-unknown -o "$WORK/$stem-equivalence.o" \
            "$ROOT/test/fixtures/effects/$stem.elisa"
        if [[ "$(uname -s)" == Darwin ]]; then
            "$ROOT/scripts/elisac_stage1.sh" -O2 -emit obj \
                -o "$WORK/$stem-equivalence-native.o" \
                "$ROOT/test/fixtures/effects/$stem.elisa"
        fi
    done
    # Compare the entire public functions, including checked-arithmetic control
    # flow, with SSA-renaming-aware LLVM comparison. Both runtime inputs remain
    # unknown in calculate; a constant-return test would be a weaker guarantee.
    if [[ -x "$llvm_diff" ]]; then
        "$llvm_diff" "$WORK/helper_equivalence.ll" \
            "$WORK/helper_equivalence_manual.ll" calculate main
        "$llvm_diff" "$WORK/helper_generic_equivalence.ll" \
            "$WORK/helper_generic_equivalence_manual.ll" calculate main
    else
        echo "optimized LLVM comparison SKIP: llvm-diff unavailable (object comparison still runs)"
    fi
    cmp "$WORK/helper_equivalence-equivalence.o" \
        "$WORK/helper_equivalence_manual-equivalence.o"
    cmp "$WORK/helper_generic_equivalence-equivalence.o" \
        "$WORK/helper_generic_equivalence_manual-equivalence.o"
    # Mach-O objects for these fixtures carry no source-name metadata. Do not
    # demand byte equality on ELF, where a differing STT_FILE entry is harmless.
    if [[ "$(uname -s)" == Darwin ]]; then
        cmp "$WORK/helper_equivalence-equivalence-native.o" \
            "$WORK/helper_equivalence_manual-equivalence-native.o"
        cmp "$WORK/helper_generic_equivalence-equivalence-native.o" \
            "$WORK/helper_generic_equivalence_manual-equivalence-native.o"
    fi
}

run_positive "static_handler_bare.elisa"
run_positive "static_handler_capture.elisa"
run_positive "static_handler_scope_named.elisa"
run_positive "static_handler_qualified.elisa"
run_positive "static_handler_qualified_generic.elisa"
run_positive "handler_default_capture.elisa"
run_positive "handler_tail_resume.elisa"
run_positive "handler_resume_tail.elisa"
run_positive "nested_handler_forwarding.elisa"
run_positive "nested_handler_capture_forwarding.elisa"
run_positive "static_handler_via.elisa"
run_positive "static_handler_generic_explicit.elisa"
run_positive "handler_via_install.elisa"
run_positive "handler_via_bare_abstract.elisa"
run_positive "handler_target_via.elisa"
run_positive "effectful_helper.elisa"
run_positive "effectful_helper_capture.elisa"
run_positive "effectful_helper_module.elisa"
run_positive "effectful_helper_generic.elisa"
run_positive "effectful_helper_generic_capture.elisa"
run_positive "effectful_helper_generic_module.elisa"
run_positive "effectful_helper_two_handlers.elisa"
run_positive "effectful_helper_chain.elisa"
run_positive "effectful_helper_nested_module.elisa"
run_positive "effectful_helper_module_sibling.elisa"
run_positive "module_duplicate_handler_names.elisa"
run_positive "module_forward_handler.elisa"
run_positive "module_forward_duplicate_handler_names.elisa"
run_positive "helper_namespace.elisa"
run_positive "helper_nested_selection.elisa"
run_positive "helper_explicit_generic.elisa"
run_positive "helper_explicit_chain.elisa"
run_positive "helper_qualified_chain.elisa"
run_positive "helper_generic_handler_selection.elisa"
run_positive "helper_generic_phantom_effect.elisa"
run_positive "helper_generic_effect_inferred.elisa"
run_positive "helper_generic_const_enum_selection.elisa"
run_positive "helper_generic_equivalence.elisa"
run_positive "helper_generic_equivalence_manual.elisa"
run_positive "helper_defaults.elisa"
run_positive "helper_sibling_capture.elisa"
run_positive "helper_multiple_effects.elisa"
run_positive "helper_module_install.elisa"
run_positive "helper_nested_capture.elisa"
run_native_result "helper_namespace.elisa" 22
run_native_result "helper_explicit_chain.elisa" 31
run_native_result "helper_qualified_chain.elisa" 47
run_native_result "helper_multiple_effects.elisa" 33
run_native_result "helper_nested_capture.elisa" 22
run_native_result "module_duplicate_handler_names.elisa" 1
run_native_result "module_forward_handler.elisa" 7
run_native_result "module_forward_duplicate_handler_names.elisa" 1
run_native_result "helper_generic_handler_selection.elisa" 17
run_native_result "helper_generic_phantom_effect.elisa" 34
run_native_result "helper_generic_effect_inferred.elisa" 42
run_native_result "helper_generic_const_enum_selection.elisa" 34
run_native_result "helper_generic_equivalence.elisa" 17
run_native_result "helper_generic_equivalence_manual.elisa" 17
run_direct_equivalence
run_positive "handler_target_via_forward.elisa"
run_positive "via_grant_covers_both_rows.elisa"
run_positive "via_grant_bare_block.elisa"
run_positive "via_grant_bare_multi_rows.elisa"
run_zero_overhead_ir "static_handler_capture.elisa"
run_zero_overhead_ir "static_handler_scope_named.elisa"
run_zero_overhead_ir "static_handler_qualified.elisa"
run_zero_overhead_ir "static_handler_qualified_generic.elisa"
run_zero_overhead_ir "handler_default_capture.elisa"
run_zero_overhead_ir "nested_handler_forwarding.elisa"
run_zero_overhead_ir "nested_handler_capture_forwarding.elisa"
run_zero_overhead_ir "static_handler_generic_explicit.elisa"
run_zero_overhead_ir "handler_via_install.elisa"
run_zero_overhead_ir "handler_via_bare_abstract.elisa"
run_zero_overhead_ir "handler_target_via.elisa"
run_zero_overhead_ir "effectful_helper.elisa"
run_zero_overhead_ir "effectful_helper_capture.elisa"
run_zero_overhead_ir "effectful_helper_module.elisa"
run_zero_overhead_ir "effectful_helper_generic.elisa"
run_zero_overhead_ir "effectful_helper_generic_capture.elisa"
run_zero_overhead_ir "effectful_helper_generic_module.elisa"
run_zero_overhead_ir "effectful_helper_two_handlers.elisa"
run_zero_overhead_ir "effectful_helper_chain.elisa"
run_zero_overhead_ir "effectful_helper_nested_module.elisa"
run_zero_overhead_ir "effectful_helper_module_sibling.elisa"
run_zero_overhead_ir "module_duplicate_handler_names.elisa"
run_zero_overhead_ir "module_forward_handler.elisa"
run_zero_overhead_ir "module_forward_duplicate_handler_names.elisa"
run_zero_overhead_ir "helper_namespace.elisa"
run_zero_overhead_ir "helper_nested_selection.elisa"
run_zero_overhead_ir "helper_explicit_generic.elisa"
run_zero_overhead_ir "helper_explicit_chain.elisa"
run_zero_overhead_ir "helper_qualified_chain.elisa"
run_zero_overhead_ir "helper_generic_handler_selection.elisa"
run_zero_overhead_ir "helper_generic_phantom_effect.elisa"
run_zero_overhead_ir "helper_generic_effect_inferred.elisa"
run_zero_overhead_ir "helper_generic_const_enum_selection.elisa"
run_zero_overhead_ir "helper_defaults.elisa"
run_zero_overhead_ir "helper_sibling_capture.elisa"
run_zero_overhead_ir "helper_multiple_effects.elisa"
run_zero_overhead_ir "helper_module_install.elisa"
run_zero_overhead_ir "helper_nested_capture.elisa"
grep -Eq 'call i64 @__effect__emit__Sink__14__at_[0-9]+\(' "$WORK/helper_namespace.ll" || {
    echo "qualified helper selected the wrong module" >&2
    exit 1
}
grep -Eq 'call void @__effect__emit__Other__12__at_[0-9]+\(' "$WORK/helper_nested_selection.ll" || {
    echo "nested helper selected the outer handler" >&2
    exit 1
}
grep -Eq 'call void @Util.leaf\(\)' "$WORK/helper_sibling_capture.ll" || {
    echo "ordinary module sibling received handler captures" >&2
    exit 1
}
grep -A4 'define internal i1 @__effect__ask__[^ ]*__bool(' "$WORK/helper_generic_handler_selection.ll" | grep -Eq 'call i1 @__handler__BoolAnswer__get\(' || {
    echo "generic bool operation selected the wrong handler" >&2
    exit 1
}
grep -A4 'define internal i64 @__effect__ask__[^ ]*__i64(' "$WORK/helper_generic_handler_selection.ll" | grep -Eq 'call i64 @__handler__IntAnswer__get\(' || {
    echo "generic i64 operation selected the wrong handler" >&2
    exit 1
}
if grep -Eq 'call .*@emit\(|call .*@ask\(' "$WORK/helper_generic_handler_selection.ll"; then
    echo "generic effect helper remained as an ordinary call" >&2
    exit 1
fi
run_zero_overhead_ir "handler_target_via_forward.elisa"

capture_stem="handler_capture_once"
"$ROOT/scripts/elisac_stage1.sh" \
    -emit llvm \
    -target-triple wasm32-unknown-unknown \
    -o "$WORK/$capture_stem.ll" \
    "$ROOT/test/fixtures/effects/$capture_stem.elisa" \
    >"$WORK/$capture_stem-llvm.log" 2>&1
[[ "$(grep -Ec 'call i64 @make_capture\(' "$WORK/$capture_stem.ll")" == "1" ]] || {
    echo "expected handler capture expression to be evaluated once" >&2
    sed -n '1,160p' "$WORK/$capture_stem.ll" >&2
    exit 1
}
[[ "$(grep -Ec 'call void @__handler__TickHandler__ping' "$WORK/$capture_stem.ll")" == "2" ]] || {
    echo "expected both operations to call the hidden handler directly" >&2
    sed -n '1,160p' "$WORK/$capture_stem.ll" >&2
    exit 1
}
if grep -Eiq 'effect(_|\.)?(handler|dispatch|install)|continuation|resume' "$WORK/$capture_stem.ll"; then
    echo "found runtime effect machinery in zero-overhead LLVM for $capture_stem.elisa" >&2
    exit 1
fi

default_capture_stem="handler_default_capture"
[[ "$(grep -Ec 'store i64 7' "$WORK/$default_capture_stem.ll")" == "1" ]] || {
    echo "expected an omitted handler capture default to be evaluated once" >&2
    sed -n '1,120p' "$WORK/$default_capture_stem.ll" >&2
    exit 1
}
[[ "$(grep -Ec 'call void @__handler__Sink__ping' "$WORK/$default_capture_stem.ll")" == "2" ]] || {
    echo "expected both operations to reuse the materialized default capture" >&2
    sed -n '1,120p' "$WORK/$default_capture_stem.ll" >&2
    exit 1
}
if grep -Eiq 'effect(_|\\.)?(handler|dispatch|install)|continuation|resume' "$WORK/$default_capture_stem.ll"; then
    echo "found runtime effect machinery in zero-overhead LLVM for $default_capture_stem.elisa" >&2
    exit 1
fi

run_negative "mismatched_handler.neg.elisa" 'effect handler "Wrong" realizes "Other"'
run_negative "missing_operation.neg.elisa" 'effect "Tick" has no operation "pong"'
run_negative "unhandled_effect.neg.elisa" 'abstract effect operation Tick.ping requires an installed handler'
run_negative "handler_signature_mismatch.neg.elisa" 'handler "Bad" operation "ping" does not match the abstract operation signature'
run_negative "abstract_operation_value.neg.elisa" 'abstract effect operation Tick.ping cannot be used as a value'
run_negative "handler_specialization_call_mismatch.neg.elisa" 'abstract effect operation Writer[sview].write does not match the active handler specialization'
run_negative "handler_qualified_namespace_mismatch.neg.elisa" 'abstract effect operation A::Tick.ping does not match the active handler specialization; runtime effect dispatch is unavailable in the zero-overhead effect subset'
run_negative "handler_specialization_arity.neg.elisa" 'handler "Sink" has invalid specialization of abstract effect "Writer": expected 1 type argument(s), got 2'
run_negative "operation_specialization_arity.neg.elisa" 'abstract effect specialization Writer expects 1 type argument(s), got 2'
run_negative "forward_partial_handler.neg.elisa" 'abstract effect operation Tick.ping requires an installed handler'
run_negative "unknown_abstract_operation_row.neg.elisa" 'effect "Tick" has no operation "pong"'
run_negative "unknown_abstract_operation_call.neg.elisa" 'effect "Tick" has no operation "pong"'
run_negative "operation_effect_row.neg.elisa" 'abstract effect row "Tick.ping" names operation "ping"; effect rows must name the family "Tick"'
run_negative "handler_operation_target_row.neg.elisa" 'abstract effect row "Tick.ping" names operation "ping"; effect rows must name the family "Tick"'
run_negative "via_operation_effect_row.neg.elisa" 'abstract effect row "Tick.ping via Console.Write" names operation "ping"; effect rows must name the family "Tick"'
run_negative "duplicate_abstract_operation.neg.elisa" 'effect "Tick" declares operation "ping" more than once'
run_negative "duplicate_handler_operation.neg.elisa" 'effect handler "Bad" declares operation "ping" more than once'
run_negative "via_unknown_abstract.neg.elisa" 'abstract effect family "Missing" is not declared'
run_negative "via_unknown_permission.neg.elisa" 'concrete effect permission "NoSuch.Write" names unknown permission family "NoSuch"'
run_negative "handler_target_via_unknown_permission.neg.elisa" 'concrete effect permission "NoSuch.Write" names unknown permission family "NoSuch"'
run_negative "permission_member_mismatch.neg.elisa" 'permission "LocalConsole" has no member "Read"'
run_negative "handler_implementation_access.neg.elisa" 'compiler-generated static effect operation "__handler__H__ping" is private'
run_negative "handler_capture_arity.neg.elisa" 'effect handler "Sink" requires 1 capture argument(s), got 0'
run_negative "handler_nested_resume.neg.elisa" 'handler "Bad" operation "ping" is outside the zero-overhead resumable subset'
run_negative "handler_resume_non_tail.neg.elisa" 'handler "Bad" operation "ping" is outside the zero-overhead resumable subset'
run_negative "handler_resume_nonvoid.neg.elisa" 'handler "Bad" operation "ping" is outside the zero-overhead resumable subset'
run_negative "effectful_helper_unhandled.neg.elisa" 'abstract effect operation Tick.ping requires an installed handler'
run_negative "helper_mixed_unhandled.neg.elisa" 'effectful helper "emit_tick" requires an installed handler for abstract effect "Tick"'
run_negative "helper_generic_specialization_mismatch.neg.elisa" 'abstract effect specialization mismatch'
run_negative "helper_clone_private.neg.elisa" 'is private'

echo "effect handler stage1 smoke OK: handled effects, captures, nesting, resume, via permissions, and diagnostics are stable"
