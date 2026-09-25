#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac-stage0}"
source "$ROOT/test/parity/run_timeout.sh"

[[ -x "$STAGE1" ]] || { echo "runtime string view smoke: missing stage1 compiler: $STAGE1" >&2; exit 2; }
[[ -x "$STAGE0" ]] || { echo "runtime string view smoke: missing stage0 compiler: $STAGE0" >&2; exit 2; }
command -v clang >/dev/null 2>&1 || { echo "runtime string view smoke: clang is required to link the stage0 runtime" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-runtime-sview.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true
SOURCE="$ROOT/test/parity/fixtures/runtime_string_view_invalid_length.elisa"

compile_case() {
    local compiler="$1" stage="$2" optimization="$3" case_name="$4"
    local stem="$WORK/${case_name}-${stage}-O${optimization}"
    local log="$stem.compile.log"
    local source
    case "$case_name" in
        invalid-length) source="$SOURCE" ;;
        *) echo "runtime string view smoke: unknown case $case_name" >&2; exit 2 ;;
    esac
    if [[ "$stage" == stage1 ]]; then
        if ! "$compiler" -emit exe "-O${optimization}" -o "$stem" "$source" >"$log" 2>&1; then
            echo "runtime string view smoke: stage1 failed to compile at O$optimization" >&2
            cat "$log" >&2
            exit 1
        fi
    else
        local archive="$stem.a"
        if ! "$compiler" -emit c-archive "-O${optimization}" -o "$archive" "$source" >"$log" 2>&1; then
            echo "runtime string view smoke: stage0 failed to compile at O$optimization" >&2
            cat "$log" >&2
            exit 1
        fi
        if ! clang -Wl,-dead_strip -o "$stem" "$archive" >"$log" 2>&1; then
            echo "runtime string view smoke: failed to link stage0 at O$optimization" >&2
            cat "$log" >&2
            exit 1
        fi
    fi
}

run_case() {
    local stage="$1" optimization="$2" case_name="$3"
    local executable="$WORK/${case_name}-${stage}-O${optimization}"
    local log="$executable.run.log"
    set +e
    elisa_run_timeout 10 "$executable" >"$log" 2>&1
    local run_status=$?
    set -e
    case "$case_name" in
        invalid-length)
            [[ "$run_status" -eq 0 ]] || {
                echo "runtime string view smoke: $case_name did not fail closed on $stage O$optimization (status $run_status)" >&2
                cat "$log" >&2
                exit 1
            }
            ;;
    esac
}

for case_name in invalid-length; do
    for optimization in 0 2; do
        compile_case "$STAGE1" stage1 "$optimization" "$case_name"
        compile_case "$STAGE0" stage0 "$optimization" "$case_name"
    done
done

for case_name in invalid-length; do
    for optimization in 0 2; do
        run_case stage1 "$optimization" "$case_name"
        run_case stage0 "$optimization" "$case_name"
    done
done

check_nullable_view_rejected() {
    local compiler="$1" stage="$2" mode="$3" fixture="$4"
    local output="$WORK/null-backed-view-$stage"
    local log="$output.compile.log"
    if "$compiler" -emit "$mode" -O0 -o "$output" "$ROOT/test/parity/fixtures/$fixture" >"$log" 2>&1; then
        echo "runtime string view smoke: $stage accepted a null-backed sview" >&2
        exit 1
    fi
    rg -q 'struct literal field "data" expects (u8&, got u8&\?|non-null reference, got (null|nullable reference))' "$log" || {
        echo "runtime string view smoke: $stage rejected null-backed sview for the wrong reason" >&2
        cat "$log" >&2
        exit 1
    }
}

for fixture in runtime_string_view_null_data.elisa runtime_string_view_null_data_conditional.elisa; do
    check_nullable_view_rejected "$STAGE1" stage1 exe "$fixture"
    check_nullable_view_rejected "$STAGE0" stage0 c-archive "$fixture"
done

check_unterminated_nullable_view_rejected() {
    local compiler="$1" stage="$2" mode="$3" fixture="$4"
    local output="$WORK/unterminated-nullable-sview-${stage}-${fixture%.elisa}"
    local log="$output.compile.log"
    if "$compiler" -emit "$mode" -O0 -o "$output" "$ROOT/test/repro/$fixture" >"$log" 2>&1; then
        echo "runtime string view smoke: $stage accepted a raw optional byte pointer as a NUL-terminated string" >&2
        exit 1
    fi
    rg -qi 'invalid cast from u8&\? to sview|expects cstr\?, got u8&\?|NUL-terminated cstr|unsupported|declined' "$log" || {
        echo "runtime string view smoke: $stage rejected an unterminated nullable view cast for an unexpected reason" >&2
        cat "$log" >&2
        exit 1
    }
    [[ ! -e "$output" ]] || {
        echo "runtime string view smoke: $stage emitted an artifact for an unterminated nullable view cast" >&2
        exit 1
    }
    [[ ! -e "$output.a" ]] || {
        echo "runtime string view smoke: $stage emitted an archive for an unterminated nullable view cast" >&2
        exit 1
    }
}

# This is an intentional Stage1 tightening: the proof-pinned Core Stage0 still treats
# nullable raw references as admissible where the runtime helper expects cstr?. Keep
# this newer safety gate separate from the historical Stage0/Stage1 parity assertions.
for fixture in sview_optional_unterminated_cast.elisa sview_optional_unterminated_constructor.elisa; do
    check_unterminated_nullable_view_rejected "$STAGE1" stage1 exe "$fixture"
done

check_postfix_sview_cast() {
    local compiler="$1" stage="$2" mode="$3"
    local output="$WORK/postfix-sview-cast-$stage"
    local log="$output.compile.log"
    if [[ "$mode" == exe ]]; then
        "$compiler" -emit exe -O0 -o "$output" "$ROOT/test/repro/sview_postfix_cast.elisa" >"$log" 2>&1 || {
            echo "runtime string view smoke: $stage rejected valid optional-cstr view construction" >&2
            cat "$log" >&2
            exit 1
        }
    else
        "$compiler" -emit c-archive -O0 -o "$output.a" "$ROOT/test/repro/sview_postfix_cast.elisa" >"$log" 2>&1 || {
            echo "runtime string view smoke: $stage rejected valid optional-cstr view construction" >&2
            cat "$log" >&2
            exit 1
        }
        clang -Wl,-dead_strip -o "$output" "$output.a" >"$log" 2>&1 || {
            echo "runtime string view smoke: failed to link valid optional-cstr view for $stage" >&2
            cat "$log" >&2
            exit 1
        }
    fi
    set +e
    elisa_run_timeout 10 "$output" >"$log" 2>&1
    local run_status=$?
    set -e
    [[ "$run_status" -eq 10 ]] || {
        echo "runtime string view smoke: valid optional-cstr view returned $run_status on $stage (expected 10)" >&2
        cat "$log" >&2
        exit 1
    }
}

check_postfix_sview_cast "$STAGE1" stage1 exe
# The full runtime's optional-cstr cast path includes newer effect annotations that
# proof-pinned Stage0 cannot audit. Its Stage0 failure is unrelated to view construction;
# the raw-pointer and valid nullable-cstr cases are tested on fresh Stage1.

check_view_length_is_immutable() {
    local compiler="$1" stage="$2" mode="$3"
    local output="$WORK/mutable-view-length-$stage"
    local log="$output.compile.log"
    if "$compiler" -emit "$mode" -O0 -o "$output" "$ROOT/test/parity/fixtures/runtime_string_view_mutable_length.elisa" >"$log" 2>&1; then
        echo "runtime string view smoke: $stage allowed sview.len widening" >&2
        exit 1
    fi
    rg -qi 'immutable|read.only|cannot assign' "$log" || {
        echo "runtime string view smoke: $stage rejected sview.len widening for an unexpected reason" >&2
        cat "$log" >&2
        exit 1
    }
}

check_view_length_is_immutable "$STAGE1" stage1 exe
check_view_length_is_immutable "$STAGE0" stage0 c-archive

check_region_lifetime() {
    local compiler="$1" stage="$2" mode="$3"
    local bad_source="$ROOT/test/repro/sview_region_use_after_destroy.elisa"
    local good_source="$ROOT/test/repro/sview_region_last_use_before_destroy.elisa"
    local bad_out="$WORK/sview-region-bad-$stage"
    local good_out="$WORK/sview-region-good-$stage"
    local bad_log="$bad_out.log"
    local good_log="$good_out.log"

    if [[ "$mode" == exe ]]; then
        if "$compiler" -emit exe -O0 -o "$bad_out" "$bad_source" >"$bad_log" 2>&1; then
            echo "runtime string view smoke: $stage accepted a view alias used after its backing region was destroyed" >&2
            exit 1
        fi
    else
        if "$compiler" -emit c-archive -O0 -o "$bad_out.a" "$bad_source" >"$bad_log" 2>&1; then
            echo "runtime string view smoke: $stage accepted a view alias used after its backing region was destroyed" >&2
            exit 1
        fi
    fi
    rg -Fq 'region dependency facts were invalidated by destroy of region "scratch"' "$bad_log" || {
        echo "runtime string view smoke: $stage rejected the stale view for the wrong reason" >&2
        cat "$bad_log" >&2
        exit 1
    }

    if [[ "$mode" == exe ]]; then
        "$compiler" -emit exe -O0 -o "$good_out" "$good_source" >"$good_log" 2>&1 || {
            echo "runtime string view smoke: $stage rejected a view whose last use precedes destroy" >&2
            cat "$good_log" >&2
            exit 1
        }
    else
        "$compiler" -emit c-archive -O0 -o "$good_out.a" "$good_source" >"$good_log" 2>&1 || {
            echo "runtime string view smoke: $stage rejected a view whose last use precedes destroy" >&2
            cat "$good_log" >&2
            exit 1
        }
        clang -Wl,-dead_strip -o "$good_out" "$good_out.a" >"$good_log" 2>&1 || {
            echo "runtime string view smoke: failed to link the safe $stage lifetime case" >&2
            cat "$good_log" >&2
            exit 1
        }
    fi
    elisa_run_timeout 10 "$good_out" >"$good_log" 2>&1 || {
        echo "runtime string view smoke: safe $stage lifetime case returned failure" >&2
        cat "$good_log" >&2
        exit 1
    }
}

check_region_lifetime "$STAGE1" stage1 exe
# The pinned Stage0 predates destroyed-region use checking, and the current Core main is
# not a usable full-runtime oracle yet. Require the lifetime contract from fresh Stage1.

echo "runtime string view smoke OK: Stage1 rejects raw nullable-pointer string scans and destroyed-region views; backing and length are non-null/immutable; malformed lengths fail closed"
