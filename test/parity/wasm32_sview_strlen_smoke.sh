#!/usr/bin/env bash
# Verify that stage1 declares/calls libc strlen with wasm32 size_t (i32), widens
# the byte count for sview clamping, and produces runnable wasm matching stage0.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../nw-core/toolchain/elisac-stage0}"
STAGE1_ROOT="${ELISA_STAGE1_ROOT:-$ROOT}"
STAGE1="${ELISA_STAGE1_BIN:-$STAGE1_ROOT/bin/elisac-stage1}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
LLVM_BIN_DIR="${ELISA_LLVM_BIN_DIR:-$(dirname -- "$LLVM_CONFIG")}"
CLANG="${ELISA_CLANG:-$LLVM_BIN_DIR/clang}"
FIXTURE="$ROOT/test/repro/wasm32_sview_strlen_abi.elisa"

if [[ ! -x "$CLANG" ]]; then CLANG="$(command -v clang || true)"; fi
for tool in "$STAGE0" "$STAGE1" "$CLANG"; do
    if [[ -z "$tool" || ! -x "$tool" ]]; then
        echo "wasm32_sview_strlen FAILED: missing required tool: ${tool:-clang}" >&2
        exit 2
    fi
done
for tool in node wasm-ld; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "wasm32_sview_strlen FAILED: missing required command: $tool" >&2
        exit 2
    fi
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-wasm32-sview.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

ELISACORE_BIN="$STAGE0" ELISA_STAGE1_BIN="$STAGE1" \
    "$STAGE1_ROOT/scripts/elisac_stage1.sh" -emit llvm -O0 \
    -target-triple wasm32-unknown-wasi -o "$WORK/stage1.ll" "$FIXTURE"

# The extern declaration and call must both return target-sized usize. The
# subsequent widening is intentional: sview clamp bounds are represented as i64.
grep -Eq 'declare i32 @strlen\(ptr\)' "$WORK/stage1.ll"
grep -Eq 'call i32 @strlen\(ptr' "$WORK/stage1.ll"
grep -Eq 'zext i32 %sview\.srclen\.target to i64' "$WORK/stage1.ll"

# Parse and verify stage1's generated LLVM IR with the target-compatible LLVM reader.
"$CLANG" --target=wasm32-unknown-wasi -c "$WORK/stage1.ll" -o "$WORK/stage1-ir.o"

# Emit and execute both wasm artifacts; WebAssembly validation also rejects the
# previous `.Lstrlen_bitcast_invalid` trap path when the ABI declarations differ.
ELISA_WASM_NO_CACHE=1 python3 "$ROOT/scripts/wasm_build.py" \
    --root "$ROOT" --compiler "$STAGE0" --source "$FIXTURE" \
    --output "$WORK/stage0.wasm" --target wasm32-unknown-wasi
ELISACORE_BIN="$STAGE0" ELISA_STAGE1_BIN="$STAGE1" \
    "$STAGE1_ROOT/scripts/elisac_stage1.sh" -emit wasm \
    -o "$WORK/stage1.wasm" "$FIXTURE"

node --input-type=module - "$WORK/stage0.mjs" "$WORK/stage1.mjs" <<'NODE'
for (const path of process.argv.slice(2)) {
  let wasm;
  let bump = 0;
  const env = {
    mmap(_address, length) {
      if (!wasm) throw new Error("mmap called before module initialization");
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
  const actual = wasm.wasm32_sview_strlen();
  if (Number(actual) !== 63) throw new Error(`${path}: got ${actual}, expected 63`);
}
console.log("wasm32 sview/strlen ABI and behavior parity OK (stage0 == stage1 == 63)");
NODE
