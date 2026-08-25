#!/usr/bin/env bash
# End-to-end WASM product smoke: Elisa source -> wasm-ld -> generated ESM facade -> Node.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="${ELISA_STAGE1_WRAPPER:-$ROOT/scripts/elisac_stage1.sh}"

[[ -x "$WRAPPER" ]] || { echo "wasm_smoke SKIP: no stage1 wrapper at $WRAPPER"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "wasm_smoke SKIP: no python3"; exit 0; }
command -v node >/dev/null 2>&1 || { echo "wasm_smoke SKIP: no node"; exit 0; }
command -v wasm-ld >/dev/null 2>&1 || { echo "wasm_smoke SKIP: no wasm-ld"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

"$WRAPPER" -emit wasm -o "$WORK/demo.wasm" "$ROOT/test/repro/wasm_minimal.elisa"
for artifact in demo.wasm demo.mjs demo.d.ts demo.json; do
    [[ -s "$WORK/$artifact" ]] || { echo "wasm_smoke FAIL: missing $artifact" >&2; exit 1; }
done

python3 - "$WORK/demo.json" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
assert manifest["target"].startswith("wasm32"), manifest
assert [item["name"] for item in manifest["exports"]] == ["add_wasm", "wasm_usize", "wasm_i64", "wasm_target_marker"], manifest
assert manifest["exports"][2]["wasm_type"] == "i64", manifest
PY

node --input-type=module - "$WORK/demo.mjs" <<'NODE'
const load = (await import(process.argv[2])).default;
const wasm = await load();
if (wasm.add_wasm(40, 2) !== 42) throw new Error("i32 export failed");
if (wasm.wasm_usize(0xffffffff) !== 0xffffffff) throw new Error("usize export failed");
const value = 9007199254740993n;
if (wasm.wasm_i64(value) !== value) throw new Error("i64 export failed");
if (wasm.wasm_target_marker() !== 7) throw new Error("WASM static target branch failed");
if (!(wasm.memory instanceof WebAssembly.Memory)) throw new Error("memory facade missing");
console.log("wasm_smoke ok");
NODE
