#!/usr/bin/env bash
# Runtime parity for pointer-sized Elisa int and fixed-width C int.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
FIXTURE="$ROOT/test/repro/int_width_abi.elisa"
WASM_LD="${WASM_LD:-$(command -v wasm-ld || true)}"
[[ -x "$WASM_LD" ]] || WASM_LD="${ELISA_LLVM_BIN_DIR:-/opt/homebrew/opt/llvm/bin}/wasm-ld"

# Use the actual shipped declarations, so this test catches incorrect ABI annotations
# as well as a backend that fails to sign-extend an i32 C return into an Elisa int.
python3 - "$ROOT" "$WORK/ffi.elisa" <<'PY'
from pathlib import Path
import re, sys
root=Path(sys.argv[1])
prelude=(root/'elisacore_std/elisacore_runtime_prelude.elisa').read_text()
driver=(root/'src/driver/elisac.elisa').read_text()
decls=[]
for text,name in [(prelude,'strcmp'),(prelude,'memcmp'),(driver,'close'),(driver,'read')]:
    match=re.search(r'^extern '+name+r'\([^\n]+',text,re.M)
    assert match, name
    decls.append(match[0])
Path(sys.argv[2]).write_text('\n'.join(decls)+'''
extern ffi_left() -> u8&
extern ffi_right() -> u8&
def ffi_check() -> i32:
    a: u8& = ffi_left()
    b: u8& = ffi_right()
    comparison: int = strcmp(a, b)
    return 1 if comparison >= 0
    left_bytes: void& = a.cast[void&] can Unsafe.PointerCast
    right_bytes: void& = b.cast[void&] can Unsafe.PointerCast
    bytes_comparison: int = memcmp(left_bytes, right_bytes, 1)
    return 2 if bytes_comparison >= 0
    status: int = close(-1)
    return 3 if status != -1
    count: isize = read(-1, a, 0)
    return 4 if count != -1
    return 0
export fn ffi_check() -> i32 = ffi_check
''')
PY
cat > "$WORK/host.c" <<'C'
#include <stdint.h>
#include <stddef.h>
extern intptr_t int_identity(intptr_t);
extern size_t int_bytes(void), int_pair_bytes(void), isize_bytes(void), i32_bytes(void);
extern int64_t i64_identity(int64_t);
extern int32_t ffi_check(void);
char *ffi_left(void) { static char s[]="a"; return s; }
char *ffi_right(void) { static char s[]="z"; return s; }
int main(void) {
    if (sizeof(int)!=4 || int_bytes()!=sizeof(intptr_t) || isize_bytes()!=sizeof(intptr_t)) return 10;
    if (i32_bytes()!=4 || int_pair_bytes()!=2*sizeof(intptr_t)) return 11;
    if (int_identity(INTPTR_MIN)!=INTPTR_MIN || int_identity(INTPTR_MAX)!=INTPTR_MAX) return 12;
    if (i64_identity(INT64_C(9007199254740993))!=INT64_C(9007199254740993)) return 13;
    return ffi_check();
}
C
clang -c "$ROOT/test/parity/profile_hooks.c" -o "$WORK/hooks.o"
for stage in 0 1; do
    if [[ "$stage" == 0 ]]; then compiler=("$STAGE0"); else compiler=(bash "$ROOT/scripts/elisac_stage1.sh"); fi
    "${compiler[@]}" -emit obj -o "$WORK/types$stage.o" "$FIXTURE"
    "${compiler[@]}" -emit obj -o "$WORK/ffi$stage.o" "$WORK/ffi.elisa"
    clang "$WORK/host.c" "$WORK/types$stage.o" "$WORK/ffi$stage.o" "$WORK/hooks.o" -o "$WORK/native$stage"
    "$WORK/native$stage" > "$WORK/native$stage.out" 2> "$WORK/native$stage.err"
done
cmp "$WORK/native0.out" "$WORK/native1.out"
cmp "$WORK/native0.err" "$WORK/native1.err"

"$STAGE0" -emit obj -target-triple wasm32-unknown-unknown -o "$WORK/stage0.o" "$FIXTURE"
"$WASM_LD" --no-entry --export=int_identity --export=int_bytes --export=int_pair_bytes --export=isize_bytes --export=i32_bytes --export=i64_identity "$WORK/stage0.o" -o "$WORK/stage0.wasm"
bash "$ROOT/scripts/elisac_stage1.sh" -emit wasm -o "$WORK/stage1.wasm" "$FIXTURE"
cat > "$WORK/string-width.elisa" <<'ELISA'
extern strlen(text: cstr) -> usize
def cstr_equal(left: cstr, right: cstr) -> bool:
    return left == right
def view_equal(left: cstr, right: cstr) -> bool:
    a: sview = sview(left, 0, strlen(left).i64())
    b: sview = sview(right, 0, strlen(right).i64())
    return a == b
export fn cstr_equal(left: cstr, right: cstr) -> bool = cstr_equal
export fn view_equal(left: cstr, right: cstr) -> bool = view_equal
ELISA
bash "$ROOT/scripts/elisac_stage1.sh" -emit wasm -o "$WORK/string-width.wasm" "$WORK/string-width.elisa"
node --input-type=module - "$WORK" <<'JS'
import fs from 'node:fs';
import assert from 'node:assert/strict';
const dir=process.argv[2];
const {instance}=await WebAssembly.instantiate(fs.readFileSync(`${dir}/stage0.wasm`));
const load=(await import(`${dir}/stage1.mjs`)).default;
const stage1=await load();
for (const api of [instance.exports,stage1]) {
    assert.equal(api.int_bytes(),4);
    assert.equal(api.isize_bytes(),4);
    assert.equal(api.i32_bytes(),4);
    assert.equal(api.int_pair_bytes(),8);
    for (const n of [-2147483648,-1,0,2147483647]) assert.equal(api.int_identity(n),n);
    assert.equal(api.i64_identity(9007199254740993n),9007199254740993n);
}
const manifest=JSON.parse(fs.readFileSync(`${dir}/stage1.json`,'utf8'));
assert.equal(manifest.exports.find(x=>x.name==='int_identity').wasm_type,'i32');
assert.match(fs.readFileSync(`${dir}/stage1.d.ts`,'utf8'),/int_identity\(value: number\): number/);
const strings=await (await import(`${dir}/string-width.mjs`)).default();
for (const equal of [strings.cstr_equal,strings.view_equal]) {
    assert.equal(equal('same content','same content'),true);
    assert.equal(equal('same length','other value'),false);
    assert.equal(equal('short','longer'),false);
    assert.equal(equal('',''),true);
}
console.log('int/C ABI parity OK: native runtime, wasm32 runtime, and generated bindings');
JS
