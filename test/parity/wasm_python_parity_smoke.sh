#!/usr/bin/env bash
# `-emit wasm` in the DRIVER vs scripts/wasm_build.py, byte for byte (§4.4).
#
# The Python is no longer on stage1's path — the driver builds the runtime object, runs
# wasm-ld, and writes the manifest and the JS/TS facade itself (src/driver/emit_wasm.elisa).
# The Python stays because it is also the only WASM packager stage0 has (see
# wasm_component_runtime_smoke.sh, which drives it with --compiler "$ELISACORE_BIN"), so it
# doubles as the oracle for the port: both paths are asked for the same module and every
# sidecar must come back identical. A facade or manifest that drifts by one byte breaks a
# published ABI, and neither the Node smoke nor the manifest assertions would notice —
# wasm_smoke.sh checks a handful of fields, this checks all of them.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/run_timeout.sh"
RUN() { elisa_run_timeout 300 "$@"; }
set -u
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="${ELISA_STAGE1_WRAPPER:-$ROOT/scripts/elisac_stage1.sh}"

[ -x "$WRAPPER" ] || { echo "wasm_python_parity_smoke SKIP: no stage1 wrapper at $WRAPPER"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "wasm_python_parity_smoke SKIP: no python3"; exit 0; }
command -v wasm-ld >/dev/null 2>&1 || { echo "wasm_python_parity_smoke SKIP: no wasm-ld"; exit 0; }
[ -f "$ROOT/scripts/wasm_build.py" ] || { echo "wasm_python_parity_smoke SKIP: no wasm_build.py"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
mkdir -p "$WORK/driver" "$WORK/python"

status=0
compared=0

compare_one() {
    local label="$1" source="$2"

    RUN "$WRAPPER" -emit wasm -o "$WORK/driver/$label.wasm" "$source" >"$WORK/driver-$label.log" 2>&1 || {
        echo "wasm_python_parity FAIL: driver build of $label failed" >&2
        sed -n '1,20p' "$WORK/driver-$label.log" >&2
        status=1; return
    }
    RUN python3 "$ROOT/scripts/wasm_build.py" \
        --root "$ROOT" --compiler "$WRAPPER" \
        --source "$source" --output "$WORK/python/$label.wasm" \
        >"$WORK/python-$label.log" 2>&1 || {
        echo "wasm_python_parity FAIL: python build of $label failed" >&2
        sed -n '1,20p' "$WORK/python-$label.log" >&2
        status=1; return
    }

    for sidecar in json mjs d.ts d.mts; do
        local a="$WORK/driver/$label.$sidecar" b="$WORK/python/$label.$sidecar"
        if [ ! -s "$a" ]; then echo "wasm_python_parity FAIL: driver wrote no $label.$sidecar" >&2; status=1; continue; fi
        if [ ! -s "$b" ]; then echo "wasm_python_parity FAIL: python wrote no $label.$sidecar" >&2; status=1; continue; fi
        if cmp -s "$a" "$b"; then
            compared=$(( compared + 1 ))
        else
            echo "wasm_python_parity FAIL: $label.$sidecar differs" >&2
            diff -u "$b" "$a" | sed -n '1,40p' >&2
            status=1
        fi
    done
    # The link line is the same on both paths, so the module itself must match too.
    if cmp -s "$WORK/driver/$label.wasm" "$WORK/python/$label.wasm"; then
        compared=$(( compared + 1 ))
    else
        echo "wasm_python_parity FAIL: $label.wasm differs ($(wc -c <"$WORK/driver/$label.wasm") vs $(wc -c <"$WORK/python/$label.wasm") bytes)" >&2
        status=1
    fi
}

compare_one demo "$ROOT/test/repro/wasm_minimal.elisa"
compare_one missing-import "$ROOT/test/repro/wasm_missing_import.elisa"

if [ "$status" = 0 ]; then
    echo "wasm_python_parity ok: $compared artifacts identical across both packagers"
fi
exit "$status"
