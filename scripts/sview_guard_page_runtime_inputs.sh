#!/usr/bin/env bash
# Resolve explicit runtime inputs for the sview baseline/candidate link test.
# Source this file; it performs no work by itself.

sview_guard_page_fail() {
    printf 'sview guard-page runtime configuration: %s\n' "$1" >&2
    return 2
}

sview_guard_page_resolve_runtimes() {
    local baseline="${ELISA_SVIEW_BASELINE_RUNTIME:-}"
    local candidate="${ELISA_SVIEW_CANDIDATE_RUNTIME:-}"

    if [[ -n "${ELISA_RUNTIME_OBJ:-}" ]]; then
        sview_guard_page_fail "ELISA_RUNTIME_OBJ is ambiguous; set ELISA_SVIEW_BASELINE_RUNTIME and ELISA_SVIEW_CANDIDATE_RUNTIME separately"
        return 2
    fi
    [[ -n "$baseline" ]] || {
        sview_guard_page_fail "set ELISA_SVIEW_BASELINE_RUNTIME explicitly"
        return 2
    }
    [[ -n "$candidate" ]] || {
        sview_guard_page_fail "set ELISA_SVIEW_CANDIDATE_RUNTIME explicitly"
        return 2
    }
    [[ -f "$baseline" ]] || {
        sview_guard_page_fail "missing baseline runtime object: $baseline"
        return 2
    }
    [[ -f "$candidate" ]] || {
        sview_guard_page_fail "missing candidate runtime object: $candidate"
        return 2
    }

    SVIEW_BASELINE_RUNTIME="$baseline"
    SVIEW_CANDIDATE_RUNTIME="$candidate"
    export SVIEW_BASELINE_RUNTIME SVIEW_CANDIDATE_RUNTIME
}
