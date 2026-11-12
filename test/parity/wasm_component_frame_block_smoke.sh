#!/usr/bin/env bash
# Execute the freestanding component arena ABI as a core WASM module.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_ROOT="$ROOT"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}"
source "$ROOT/test/parity/resolve_elisac.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
command -v wasm-ld >/dev/null
command -v node >/dev/null
bash "$ROOT/scripts/elisac_stage1.sh" -emit obj -O0 -target-triple wasm32-unknown-unknown \
    -o "$WORK/frame.o" "$ROOT/test/repro/wasm_component_frame_block.elisa"
wasm-ld --no-entry --export=check_frame --export=overflow_frame --export-memory \
    --initial-memory=2097152 -o "$WORK/frame.wasm" "$WORK/frame.o"
"$ELISACORE_BIN" -emit obj -O0 -target-triple wasm32-unknown-unknown \
    -o "$WORK/frame-stage0.o" "$ROOT/test/repro/wasm_component_frame_block.elisa"
# Stage0 emits memset for the fixture's zeroed arrays. Supply its freestanding
# implementation here so the test does not depend on a WASI sysroot.
cat > "$WORK/memset.c" <<'C'
void *memset(void *destination, int value, unsigned long count) {
    unsigned char *bytes = destination;
    for (unsigned long i = 0; i < count; ++i) bytes[i] = (unsigned char)value;
    return destination;
}
C
clang -target wasm32-unknown-unknown -fno-builtin -c "$WORK/memset.c" -o "$WORK/memset.o"
wasm-ld --no-entry --export=check_frame --export=overflow_frame --export-memory \
    --initial-memory=2097152 -o "$WORK/frame-stage0.wasm" "$WORK/frame-stage0.o" "$WORK/memset.o"
node --input-type=module - "$WORK/frame.wasm" "$WORK/frame-stage0.wasm" <<'NODE'
import {readFileSync} from 'node:fs';
for (const path of process.argv.slice(2)) {
const {instance} = await WebAssembly.instantiate(readFileSync(path), {});
const result = instance.exports.check_frame();
if (result !== 0) throw new Error(`frame allocation or release failed: ${result}`);
let trapped = false;
try { instance.exports.overflow_frame(); } catch (error) {
  if (!(error instanceof WebAssembly.RuntimeError)) throw error;
  trapped = true;
}
if (!trapped) throw new Error('frame overflow did not trap');
}
console.log('component frame block allocation, release and overflow OK on both compilers');
NODE
