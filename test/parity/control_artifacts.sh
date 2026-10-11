#!/usr/bin/env bash
# Preserve failed control evidence while keeping successful runs tidy.
elisa_control_artifacts() {
    ELISA_CONTROL_WORK="$1"
    trap elisa_control_cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    trap 'exit 129' HUP
}
elisa_control_cleanup() {
    local status=$?
    if [[ "$status" -eq 0 && "${ELISA_KEEP_INCREMENTAL_CACHE_CONTROL:-0}" != 1 ]]; then
        rm -rf "$ELISA_CONTROL_WORK"
    else
        printf 'control artifacts retained: %s (exit=%s)\n' "$ELISA_CONTROL_WORK" "$status" >&2
    fi
    return "$status"
}
