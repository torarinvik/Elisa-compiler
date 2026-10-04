#!/usr/bin/env bash
set -euo pipefail
# The gate supplies both values; recording proves the selected driver ran.
printf '%s\n' invoked >> "$ELISA_NATIVE_LINK_MARKER"
exec "$ELISA_NATIVE_LINK_REAL_CLANG" "$@"
