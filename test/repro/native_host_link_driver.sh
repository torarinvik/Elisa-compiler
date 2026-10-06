#!/usr/bin/env bash
set -euo pipefail
# Check the actual argument vector, not just whether the override was invoked.
has_arg() {
    local expected="$1"
    shift
    local argument
    for argument in "$@"; do
        [[ "$argument" != "$expected" ]] || return 0
    done
    return 1
}
has_arg -fno-builtin "$@"
case "$(uname -s)" in
    Linux)
        has_arg -pthread "$@"
        has_arg -no-pie "$@"
        has_arg -Wl,--gc-sections "$@"
        has_arg -lm "$@"
        ! has_arg -Wl,-dead_strip "$@"
        ;;
    Darwin)
        has_arg -Wl,-dead_strip "$@"
        ! has_arg -no-pie "$@"
        ! has_arg -Wl,--gc-sections "$@"
        ;;
    *) echo 'unsupported host for native linker policy gate' >&2; exit 2 ;;
esac
# The gate supplies both values; recording proves the selected driver ran and
# that its platform-specific policy checks passed.
printf '%s\n' invoked >> "$ELISA_NATIVE_LINK_MARKER"
exec "$ELISA_NATIVE_LINK_REAL_CLANG" "$@"
