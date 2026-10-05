#!/usr/bin/env bash
# Resolve the two independently-provenanced runtime objects used by the sview
# baseline/candidate link test. Source this file; it performs no work by itself.

sview_guard_page_fail() {
    printf 'sview guard-page runtime configuration: %s\n' "$1" >&2
    return 2
}

sview_guard_page_compiler_root() {
    local binary="$1" declared_root="$2" directory
    if [[ -n "$declared_root" ]]; then
        cd -- "$declared_root" && pwd
        return
    fi
    directory="$(cd -- "$(dirname -- "$binary")" 2>/dev/null && pwd)" || return 1
    if [[ "$(basename -- "$directory")" == bin ]]; then
        cd -- "$(dirname -- "$directory")" && pwd
    else
        return 1
    fi
}

sview_guard_page_resolve_runtimes() {
    local root="$1" baseline="$2" candidate="$3"
    local baseline_root candidate_root baseline_abi candidate_abi shared

    baseline_root="$(sview_guard_page_compiler_root "$baseline" "${ELISA_SVIEW_BASELINE_ROOT:-}")" || baseline_root=""
    candidate_root="$(sview_guard_page_compiler_root "$candidate" "${ELISA_SVIEW_CANDIDATE_ROOT:-}")" || candidate_root=""

    baseline_abi="${ELISA_SVIEW_BASELINE_ABI_ID:-}"
    candidate_abi="${ELISA_SVIEW_CANDIDATE_ABI_ID:-}"
    shared="${ELISA_RUNTIME_OBJ:-}"

    if [[ -n "${ELISA_SVIEW_BASELINE_RUNTIME:-}" || -n "${ELISA_SVIEW_CANDIDATE_RUNTIME:-}" ]]; then
        [[ -z "$shared" ]] || {
            sview_guard_page_fail "do not mix ELISA_RUNTIME_OBJ with separate sview runtime selections"
            return 2
        }
        if [[ -z "${ELISA_SVIEW_BASELINE_RUNTIME:-}" && -z "$baseline_root" ]]; then
            sview_guard_page_fail "set ELISA_SVIEW_BASELINE_RUNTIME or ELISA_SVIEW_BASELINE_ROOT for a non-checkout baseline compiler"
            return 2
        fi
        if [[ -z "${ELISA_SVIEW_CANDIDATE_RUNTIME:-}" && -z "$candidate_root" ]]; then
            sview_guard_page_fail "set ELISA_SVIEW_CANDIDATE_RUNTIME or ELISA_SVIEW_CANDIDATE_ROOT for a non-checkout candidate compiler"
            return 2
        fi
        SVIEW_BASELINE_RUNTIME="${ELISA_SVIEW_BASELINE_RUNTIME:-$baseline_root/build/runtime/elisacore_runtime.o}"
        SVIEW_CANDIDATE_RUNTIME="${ELISA_SVIEW_CANDIDATE_RUNTIME:-$candidate_root/build/runtime/elisacore_runtime.o}"
    elif [[ -n "$shared" ]]; then
        # Legacy sharing is opt-in only with matching content-derived ABI IDs.
        # Merely placing two binaries under one directory is not proof that their
        # runtime ABI inputs match (especially when stale-product overrides exist).
        if [[ ! "$baseline_abi" =~ ^[0-9a-f]{64}$ || "$baseline_abi" != "$candidate_abi" ]]; then
            sview_guard_page_fail "shared ELISA_RUNTIME_OBJ requires matching 64-character SHA-256 ELISA_SVIEW_BASELINE_ABI_ID and ELISA_SVIEW_CANDIDATE_ABI_ID"
            return 2
        fi
        SVIEW_BASELINE_RUNTIME="$shared"
        SVIEW_CANDIDATE_RUNTIME="$shared"
    else
        if [[ -z "${ELISA_SVIEW_BASELINE_RUNTIME:-}" && -z "$baseline_root" ]]; then
            sview_guard_page_fail "set ELISA_SVIEW_BASELINE_RUNTIME or ELISA_SVIEW_BASELINE_ROOT for a non-checkout baseline compiler"
            return 2
        fi
        if [[ -z "${ELISA_SVIEW_CANDIDATE_RUNTIME:-}" && -z "$candidate_root" ]]; then
            sview_guard_page_fail "set ELISA_SVIEW_CANDIDATE_RUNTIME or ELISA_SVIEW_CANDIDATE_ROOT for a non-checkout candidate compiler"
            return 2
        fi
        SVIEW_BASELINE_RUNTIME="${ELISA_SVIEW_BASELINE_RUNTIME:-$baseline_root/build/runtime/elisacore_runtime.o}"
        SVIEW_CANDIDATE_RUNTIME="${ELISA_SVIEW_CANDIDATE_RUNTIME:-$candidate_root/build/runtime/elisacore_runtime.o}"
    fi

    [[ -f "$SVIEW_BASELINE_RUNTIME" ]] || {
        sview_guard_page_fail "missing baseline runtime object: $SVIEW_BASELINE_RUNTIME"
        return 2
    }
    [[ -f "$SVIEW_CANDIDATE_RUNTIME" ]] || {
        sview_guard_page_fail "missing candidate runtime object: $SVIEW_CANDIDATE_RUNTIME"
        return 2
    }

    export SVIEW_BASELINE_RUNTIME SVIEW_CANDIDATE_RUNTIME
}
