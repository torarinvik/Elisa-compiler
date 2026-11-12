#!/usr/bin/env bash
# Execute the freestanding component arena ABI as a core WASM module.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
command -v wasm-ld >/dev/null
command -v node >/dev/null
bash "$ROOT/scripts/elisac_stage1.sh" -emit obj -O0 -target-triple wasm32-unknown-unknown \
    -o "$WORK/frame.o" "$ROOT/test/repro/wasm_component_frame_block.elisa"
wasm-ld --no-entry --export=check_frame --export=overflow_frame --export-memory \
    --initial-memory=2097152 -o "$WORK/frame.wasm" "$WORK/frame.o"
node --input-type=module - "$WORK/frame.wasm" <<'NODE'
import {readFileSync} from 'node:fs';
const {instance} = await WebAssembly.instantiate(readFileSync(process.argv[2]), {});
const result = instance.exports.check_frame();
if (result !== 0) throw new Error(`frame allocation or release failed: ${result}`);
let trapped = false;
try { instance.exports.overflow_frame(); } catch (error) {
  if (!(error instanceof WebAssembly.RuntimeError)) throw error;
  trapped = true;
}
if (!trapped) throw new Error('frame overflow did not trap');
console.log('component frame block allocation, release and overflow OK');
NODE
