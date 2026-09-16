#!/usr/bin/env bash
# Both compiler stages must emit a valid wasm32 module for a checked darray
# access whose usize index is narrower than the darray's i64 count field.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
SOURCE="$ROOT/test/repro/wasm32_checked_index.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/wasm32-checked-index.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

compile_validate() {
    local label="$1" compiler="$2"
    local object="$WORK/$label.o" module="$WORK/$label.wasm"
    "$compiler" -emit obj -O0 -target-triple wasm32-unknown-wasi \
        -o "$object" "$SOURCE" >"$WORK/$label.compile.log" 2>&1 || {
        cat "$WORK/$label.compile.log" >&2
        echo "wasm32 checked-index smoke FAIL: $label did not compile" >&2
        exit 1
    }
    wasm-ld --no-entry --export-dynamic --allow-undefined --export=__heap_base \
        -o "$module" "$object"
    node -e 'const fs=require("fs");const p=process.argv[1];const b=fs.readFileSync(p);if(!WebAssembly.validate(b)){throw new Error(`${p}: invalid WebAssembly module`)}' "$module"
    echo "  $label: checked-index WebAssembly validates"
}

[[ -x "$STAGE0" ]] || { echo "wasm32 checked-index smoke FAIL: stage0 unavailable: $STAGE0" >&2; exit 1; }
[[ -x "${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}" ]] || { echo "wasm32 checked-index smoke FAIL: stage1 unavailable" >&2; exit 1; }
compile_validate stage0 "$STAGE0"
compile_validate stage1 "$STAGE1"
echo "wasm32 checked-index smoke OK"
