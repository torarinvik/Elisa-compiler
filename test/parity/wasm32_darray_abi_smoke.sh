#!/usr/bin/env bash
# wasm32 darray layout, field-width, and runtime parity against stage0.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../nw-core/toolchain/elisac-stage0}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/repro/wasm32_darray_header_ops.elisa"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
LLVM_BIN_DIR="${ELISA_LLVM_BIN_DIR:-$(dirname -- "$LLVM_CONFIG")}"
CLANG="${ELISA_CLANG:-$LLVM_BIN_DIR/clang}"

if [[ ! -x "$STAGE0" || ! -x "$STAGE1" ]]; then
    echo "wasm32_darray_abi SKIP: stage0 or stage1 compiler is unavailable"
    exit 0
fi
if [[ ! -x "$CLANG" ]]; then CLANG="$(command -v clang || true)"; fi
if [[ -z "$CLANG" || ! -x "$CLANG" ]] || ! command -v node >/dev/null 2>&1 || ! command -v wasm-ld >/dev/null 2>&1; then
    echo "wasm32_darray_abi SKIP: clang, Node.js, or wasm-ld is unavailable"
    exit 0
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-wasm32-darray.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

"$STAGE0" -emit llvm -O0 -target-triple wasm32-unknown-wasi \
    -o "$WORK/stage0.ll" "$FIXTURE"
ELISACORE_BIN="$STAGE0" ELISA_STAGE1_BIN="$STAGE1" \
    "$ROOT/scripts/elisac_stage1.sh" -emit llvm -O0 \
    -target-triple wasm32-unknown-wasi -o "$WORK/stage1.ll" "$FIXTURE"

# The checked-index path must compare two i32 values, and every darray aggregate
# must carry the same pointer-sized header as stage0.
grep -Eq 'define .*@checked_at\(\{ ptr, i32, i32 \}' "$WORK/stage1.ll"
grep -Eq 'icmp ult i32 .*%safe.index.count' "$WORK/stage1.ll"
grep -Eq 'define .*@mutate\(' "$WORK/stage1.ll"

# clang's LLVM reader/verifier catches malformed operand widths and intrinsic signatures
# that a compiler's textual-IR writer can otherwise serialize without complaint.
"$CLANG" --target=wasm32-unknown-wasi -c "$WORK/stage0.ll" -o "$WORK/stage0-ir.o"
"$CLANG" --target=wasm32-unknown-wasi -c "$WORK/stage1.ll" -o "$WORK/stage1-ir.o"

# Run both generated modules. The stage0 runtime's POSIX arena backend asks the host
# for mmap/munmap; this deterministic bump allocator keeps allocations above __heap_base.
ELISA_WASM_NO_CACHE=1 python3 "$ROOT/scripts/wasm_build.py" \
    --root "$ROOT" --compiler "$STAGE0" --source "$FIXTURE" \
    --output "$WORK/stage0.wasm" --target wasm32-unknown-wasi
ELISACORE_BIN="$STAGE0" ELISA_STAGE1_BIN="$STAGE1" \
    "$ROOT/scripts/elisac_stage1.sh" -emit wasm \
    -o "$WORK/stage1.wasm" "$FIXTURE"

node --input-type=module - "$WORK/stage0.mjs" "$WORK/stage1.mjs" <<'NODE'
for (const path of process.argv.slice(2)) {
  let wasm;
  let bump = 0;
  const env = {
    mmap(_address, length) {
      if (!wasm) throw new Error("mmap called before the module was initialized");
      const rawBase = wasm.raw.__heap_base;
      const heapBase = Number(rawBase instanceof WebAssembly.Global ? rawBase.value : rawBase);
      if (!bump) bump = Math.ceil(heapBase / 65536) * 65536;
      const pointer = bump;
      bump += Number(length);
      const neededPages = Math.ceil(bump / 65536);
      const currentPages = wasm.memory.buffer.byteLength / 65536;
      if (neededPages > currentPages) wasm.memory.grow(neededPages - currentPages);
      return pointer;
    },
    munmap() { return 0; },
    elisa_profile_region_layout_negotiate: () => 0,
    elisa_profile_region_layout_v1: () => {},
    elisa_profile_allocation_negotiate: () => 0,
    elisa_profile_allocation_event_v1: () => {},
  };
  const load = (await import(path)).default;
  wasm = await load(undefined, { imports: { env } });
  const actual = wasm.wasm_darray_header_ops();
  if (actual !== 292) throw new Error(`${path}: got ${actual}, expected stage0 result 292`);
}
console.log("wasm32 darray ABI and behavior parity OK (stage0 == stage1 == 292)");
NODE
