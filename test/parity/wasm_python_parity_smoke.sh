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
set -u
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"

# This parity test invokes the compiler several times. Keep it disabled after
# the runaway compiler-chain incidents unless the user explicitly reauthorizes
# validation. Do not use run_timeout.sh here: its timeout retry would relaunch
# a compiler whose descendants may still be exiting.
if [ "${ELISASCRIPT_VALIDATION_REAUTHORIZED:-0}" != "1" ]; then
    echo "wasm_python_parity_smoke: validation is disabled; explicit reauthorization is required" >&2
    exit 125
fi

# Always use this checkout's stage1 product, never an installed wrapper or the
# stage0 compiler. The stage1 wrapper refuses stale products and monitors the
# compiler process RSS; require an explicit cap below the previously observed
# runaway footprint rather than accepting its much higher default.
STAGE1_BIN="$ROOT/bin/elisac-stage1"
WRAPPER="$ROOT/scripts/elisac_stage1.sh"
if [ ! -x "$STAGE1_BIN" ] || [ ! -x "$WRAPPER" ]; then
    echo "wasm_python_parity_smoke FAIL: local stage1 product or wrapper is missing" >&2
    exit 2
fi
raw_stage1_rss_limit="${ELISA_STAGE1_MAX_RSS_KB:-}"
case "$raw_stage1_rss_limit" in
    ''|*[!0-9]*|0)
        echo "wasm_python_parity_smoke: set ELISA_STAGE1_MAX_RSS_KB to an explicit positive RSS limit" >&2
        exit 125
        ;;
esac
if [ "${#raw_stage1_rss_limit}" -gt 7 ]; then
    echo "wasm_python_parity_smoke: ELISA_STAGE1_MAX_RSS_KB may not exceed 2097152 KB" >&2
    exit 2
fi
stage1_rss_limit_kb=$((10#$raw_stage1_rss_limit))
if [ "$stage1_rss_limit_kb" -eq 0 ] || [ "$stage1_rss_limit_kb" -gt 2097152 ]; then
    echo "wasm_python_parity_smoke: ELISA_STAGE1_MAX_RSS_KB must be in 1..2097152 KB" >&2
    exit 2
fi
ELISA_STAGE1_MAX_RSS_KB="$stage1_rss_limit_kb"
export ELISA_STAGE1_BIN="$STAGE1_BIN"
export ELISA_STAGE1_MAX_RSS_KB

BOUNDED_RUNNER="$ROOT/test/parity/run_bounded_stage1_command.py"
if [ ! -f "$BOUNDED_RUNNER" ]; then
    echo "wasm_python_parity_smoke: refusing to run without the process-tree RSS supervisor" >&2
    exit 125
fi
RUN() { python3 "$BOUNDED_RUNNER" "$@"; }

[ -x "$WRAPPER" ] || { echo "wasm_python_parity_smoke FAIL: no stage1 wrapper at $WRAPPER" >&2; exit 1; }
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
compare_one int-width "$ROOT/test/repro/int_width_abi.elisa"
compare_one width-edges "$ROOT/test/repro/wasm_width_edges.elisa"
compare_one missing-import "$ROOT/test/repro/wasm_missing_import.elisa"

if [ "$status" = 0 ]; then
    echo "wasm_python_parity ok: $compared artifacts identical across both packagers"
fi
exit "$status"
