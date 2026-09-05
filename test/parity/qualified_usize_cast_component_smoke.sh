#!/usr/bin/env bash
# A qualified wasm32 usize constant widened to i64 must produce a valid component
# for both compiler generations. Before the type-inference fix, Stage1 emitted
# invalid LLVM (`icmp i64, i32`) and wasm-component-ld rejected the core module.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
SOURCE="$ROOT/test/repro/qualified_usize_cast_component.elisa"
WIT="$ROOT/test/repro/qualified_usize_cast_component.wit"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-qualified-usize.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "qualified usize cast component smoke SKIP: stage0 unavailable"; exit 0; }
[[ -x "$STAGE1" ]] || { echo "qualified usize cast component smoke SKIP: stage1 unavailable"; exit 0; }

build_component() {
    local compiler="$1"
    local name="$2"
    ELISA_WASM_NO_CACHE=1 \
      python3 "$ROOT/scripts/wasm_build.py" \
      --root "$ROOT" \
      --compiler "$compiler" \
      --source "$SOURCE" \
      --output "$WORK/$name.wasm" \
      --target wasm32-unknown-unknown \
      --wasm-only \
      --component-type "$WIT" \
      >"$WORK/$name.log" 2>&1
    [[ -s "$WORK/$name.wasm" ]] || { echo "$name component output is empty" >&2; exit 1; }
}

build_component "$STAGE0" stage0
build_component "$STAGE1" stage1

echo "qualified usize cast component parity OK"
