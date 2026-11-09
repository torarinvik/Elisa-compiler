#!/usr/bin/env bash
# Preserve the caller's linker environment across Python startup on macOS.
export ELISA_REBUILD_LIBRARY_PATH_SET="${LIBRARY_PATH+x}"
export ELISA_REBUILD_LIBRARY_PATH_VALUE="${LIBRARY_PATH-}"
export ELISA_REBUILD_SDKROOT_SET="${SDKROOT+x}"
export ELISA_REBUILD_SDKROOT_VALUE="${SDKROOT-}"
exec "${ELISA_TOOL_PYTHON:-python3}" "$(dirname -- "${BASH_SOURCE[0]}")/compiler_rebuild_timeout.py" "$@"
