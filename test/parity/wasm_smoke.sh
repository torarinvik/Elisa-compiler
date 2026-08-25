#!/usr/bin/env bash
# End-to-end WASM product smoke: Elisa source -> wasm-ld -> generated ESM facade -> Node.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="${ELISA_STAGE1_WRAPPER:-$ROOT/scripts/elisac_stage1.sh}"

[[ -x "$WRAPPER" ]] || { echo "wasm_smoke SKIP: no stage1 wrapper at $WRAPPER"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "wasm_smoke SKIP: no python3"; exit 0; }
command -v node >/dev/null 2>&1 || { echo "wasm_smoke SKIP: no node"; exit 0; }
command -v wasm-ld >/dev/null 2>&1 || { echo "wasm_smoke SKIP: no wasm-ld"; exit 0; }

python3 "$ROOT/test/parity/wasm_build_unit.py"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

"$WRAPPER" -emit wasm -o "$WORK/elisa-demo.wasm" "$ROOT/test/repro/wasm_minimal.elisa"
"$WRAPPER" -emit wasm -o "$WORK/missing-import.wasm" "$ROOT/test/repro/wasm_missing_import.elisa"
for artifact in elisa-demo.wasm elisa-demo.mjs elisa-demo.d.ts elisa-demo.d.mts elisa-demo.json; do
    [[ -s "$WORK/$artifact" ]] || { echo "wasm_smoke FAIL: missing $artifact" >&2; exit 1; }
done

python3 - "$WORK/elisa-demo.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["target"].startswith("wasm32"), manifest
assert [item["name"] for item in manifest["exports"]] == ["add_wasm", "wasm_usize", "wasm_i64", "wasm_target_marker", "wasm_text_length", "wasm_echo_text", "wasm_arena_allocation_probe"], manifest
assert manifest["exports"][2]["wasm_type"] == "i64", manifest
assert manifest["exports"][4]["parameters"][0]["binding"] == "string", manifest
assert manifest["memory"]["heap_base_export"] == "__heap_base", manifest
assert manifest["module"] == "elisa-demo", manifest
assert manifest["files"]["types_esm"] == "elisa-demo.d.mts", manifest
PY

node --input-type=module - "$WORK/elisa-demo.mjs" <<'NODE'
const load = (await import(process.argv[2])).default;
const wasm = await load();
if (wasm.add_wasm(40, 2) !== 42) throw new Error("i32 export failed");
if (wasm.wasm_usize(0xffffffff) !== 0xffffffff) throw new Error("usize export failed");
const value = 9007199254740993n;
if (wasm.wasm_i64(value) !== value) throw new Error("i64 export failed");
if (wasm.wasm_target_marker() !== 7) throw new Error("WASM static target branch failed");
if (wasm.wasm_text_length("Hei, WASM!") !== 10) throw new Error("automatic cstr input failed");
if (wasm.wasm_echo_text("Hei, Elisa 🌍") !== "Hei, Elisa 🌍") throw new Error("automatic cstr output failed");
for (let iteration = 0; iteration < 100; iteration++) {
  if (wasm.wasm_arena_allocation_probe() !== 42) throw new Error("Elisa arena allocation failed");
}
if (!(wasm.memory instanceof WebAssembly.Memory)) throw new Error("memory facade missing");
const heapBase = Number(wasm.raw.__heap_base.value);
const bytes = wasm.writeBytes(Uint8Array.of(3, 1, 4, 1, 5));
if (bytes.pointer < heapBase) throw new Error("host allocation overlaps module data");
if (wasm.readBytes(bytes.pointer, bytes.length).join(",") !== "3,1,4,1,5") throw new Error("byte bridge failed");
wasm.free(bytes.pointer);
const stringPointer = wasm.writeString("memory bridge ✓");
if (wasm.readString(stringPointer) !== "memory bridge ✓") throw new Error("string bridge failed");
wasm.free(stringPointer);
const reuseSize = wasm.memory.buffer.byteLength;
const reusable = wasm.alloc(reuseSize);
const afterFirstGrowth = wasm.memory.buffer.byteLength;
wasm.free(reusable);
const reused = wasm.alloc(reuseSize);
if (wasm.memory.buffer.byteLength !== afterFirstGrowth) throw new Error("allocator did not reuse freed capacity");
wasm.free(reused);
const customMemory = new WebAssembly.Memory({ initial: 16, maximum: 32768 });
const custom = await load(undefined, { memory: customMemory, env: { strlen: () => 77 } });
if (custom.memory !== customMemory) throw new Error("custom memory was not retained");
if (custom.wasm_text_length("override") !== 77) throw new Error("custom env import did not win");
console.log("wasm_smoke ok");
NODE

node --input-type=module - "$WORK/missing-import.mjs" <<'NODE'
const load = (await import(process.argv[2])).default;
try {
  await load();
  throw new Error("missing host import was accepted");
} catch (error) {
  if (!String(error).includes("env.host_magic (function)")) throw error;
}
const wasm = await load(undefined, { imports: { env: { host_magic: (value) => value + 2 } } });
if (wasm.call_host_magic_wasm(40) !== 42) throw new Error("custom module import failed");
NODE
