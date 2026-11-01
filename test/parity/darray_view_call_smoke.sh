#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
PYTHON_BIN="${PYTHON_BIN:-$ELISA_PYTHON314_BIN}"
PYTHON_CONFIG="${PYTHON_CONFIG:-$ELISA_PYTHON314_CONFIG}"
if [[ ! -x "$PYTHON_BIN" || ! -x "$PYTHON_CONFIG" ]]; then
    echo "darray view call smoke SKIP (Python unavailable)"
    exit 0
fi
SUFFIX="$("$PYTHON_BIN" -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')"
cp "$ROOT/test/repro/darray_view_call.elisa" "$WORK/darray_view_call.elisa"
PYTHON_BIN="$PYTHON_BIN" PYTHON_CONFIG="$PYTHON_CONFIG" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit pymodule-so \
    -o "$WORK/darray_view_call$SUFFIX" "$WORK/darray_view_call.elisa"
(cd "$WORK" && "$PYTHON_BIN" - <<'PY'
import darray_view_call
assert darray_view_call.nonempty() == 9
assert darray_view_call.empty() == 0
PY
)
echo "darray view call smoke PASS"
