#!/usr/bin/env bash
# Integer WIDTH consistency on wasm32, validated and EXECUTED.
#
# The report: a usize range loop with a literal bound of 1024 gave "expected i64, found i32".
# Root causes found on the driver: (1) the range counter defaulted to 64 bits on every
# target — stage0 types it at the target's pointer width (i32 on wasm32) — and (2) every
# signed 64-bit `*` became `llvm.smul.with.overflow.i64`, which LLVM lowers on wasm32 to a
# `__multi3` libcall no freestanding host provides: the module VALIDATED and then failed to
# instantiate. So this smoke checks three things a compile-only test cannot see:
#   - WebAssembly.validate accepts the module (exit 3 on failure, distinct from a wrong answer);
#   - the module imports nothing but memory (a libcall import is a build defect, not a host one);
#   - the exports compute values fixed BY HAND, including signedness at 2^31 for a 32-bit usize.
# Every run builds into a fresh directory: a stale artifact cannot pass this.
set -uo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WRAPPER="$ROOT/scripts/elisac_stage1.sh"
[[ -x "$ROOT/bin/elisac-stage1" ]] || { echo "wasm_integer_width SKIP: no stage1 product"; exit 0; }
command -v node >/dev/null 2>&1 || { echo "wasm_integer_width SKIP: no node"; exit 0; }
command -v wasm-ld >/dev/null 2>&1 || [[ -x /opt/homebrew/opt/llvm/bin/wasm-ld ]] || { echo "wasm_integer_width SKIP: no wasm-ld"; exit 0; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

cat > "$WORK/run.mjs" <<'NODE'
import { readFileSync } from "node:fs";
const [mjs, wasmPath, spec] = process.argv.slice(2);
const bytes = readFileSync(wasmPath);
if (!WebAssembly.validate(bytes)) { console.error("VALIDATE FAIL: " + wasmPath); process.exit(3); }
const extra = WebAssembly.Module.imports(new WebAssembly.Module(bytes)).map(i => i.module + "." + i.name).filter(n => n !== "env.memory");
if (extra.length) { console.error("UNEXPECTED IMPORTS: " + extra.join(" ")); process.exit(4); }
const load = (await import(mjs)).default;
const wasm = await load();
let failed = 0;
for (const line of readFileSync(spec, "utf8").split("\n").filter(Boolean)) {
  const [name, argText, wantText] = line.split("|");
  const args = argText === "" ? [] : argText.split(",").map(Number);
  const got = Number(wasm[name](...args));
  if (got !== Number(wantText)) { console.error(`FAIL ${name}(${args}) = ${got}, want ${wantText}`); failed = 1; }
}
process.exit(failed);
NODE
printf 'fill_and_sum||523776\n' > "$WORK/wasm_usize_loop.spec"
cat > "$WORK/wasm_usize_variants.spec" <<'SPEC'
sum_to|16|120
sum_to|0|0
sum_to|1|0
by_literal||120
by_const||120
by_computed|7|105
zero_iter||100
one_iter||5
nested_break_continue||645
while_equiv|16|120
while_equiv|0|0
index_use||558
SPEC
cat > "$WORK/wasm_width_edges.spec" <<'SPEC'
usize_gt|2147483648,2147483647|1
usize_gt|4294967295,0|1
usize_gt|0,4294967295|0
isize_lt|-1,0|1
isize_lt|-2147483648,2147483647|1
widen_u32|4294967295|4294967295
widen_i32|-1|-1
narrow_u64|4294967295|4294967295
count_up_to|0|0
count_up_to|5|5
SPEC
# Values are pure fixtures for the runner; the i64 multiply is checked separately below,
# because BigInt arguments do not go through the numeric spec.
pass=0; fail=0
for name in wasm_usize_loop wasm_usize_variants wasm_width_edges; do
    mkdir -p "$WORK/$name"
    if ! "$WRAPPER" -emit wasm -o "$WORK/$name/$name.wasm" "$ROOT/test/repro/$name.elisa" >"$WORK/$name/build.log" 2>&1; then
        echo "  FAIL $name: build"; grep -v warning: "$WORK/$name/build.log" | head -3; fail=$((fail + 1)); continue
    fi
    if node "$WORK/run.mjs" "$WORK/$name/$name.mjs" "$WORK/$name/$name.wasm" "$WORK/$name.spec"; then pass=$((pass + 1)); else echo "  FAIL $name (rc=$?)"; fail=$((fail + 1)); fi
done
mkdir -p "$WORK/mul"
if "$WRAPPER" -emit wasm -o "$WORK/mul/wasm_i64_multiply.wasm" "$ROOT/test/repro/wasm_i64_multiply.elisa" >"$WORK/mul/build.log" 2>&1 && node --input-type=module - "$WORK/mul/wasm_i64_multiply.wasm" <<'NODE'
import { readFileSync } from "node:fs";
const bytes = readFileSync(process.argv[2]);
if (!WebAssembly.validate(bytes)) process.exit(3);
const extra = WebAssembly.Module.imports(new WebAssembly.Module(bytes)).map(i => i.module + "." + i.name).filter(n => n !== "env.memory");
if (extra.length) { console.error("UNEXPECTED IMPORTS: " + extra.join(" ")); process.exit(4); }
// The imported memory's maximum must not exceed the module's declared maximum; retry with the
// module's own figure when the first attempt names one.
async function instantiateWithMemory(maximum) {
  try { return (await WebAssembly.instantiate(bytes, { env: { memory: new WebAssembly.Memory({ initial: 16, maximum }) } })).instance; }
  catch (e) { const m = /declared maximum (\d+)/.exec(String(e)); if (!m || Number(m[1]) === maximum) throw e; return instantiateWithMemory(Number(m[1])); }
}
const instance = await instantiateWithMemory(65536);
const t = instance.exports.times;
const cases = [[6n, 7n, 42n], [-3n, 5n, -15n], [2147483648n, 2147483648n, 4611686018427387904n], [-1n, -9223372036854775807n, 9223372036854775807n]];
for (const [a, b, want] of cases) { const got = t(a, b); if (got !== want) { console.error(`FAIL times(${a},${b}) = ${got}, want ${want}`); process.exit(1); } }
// Overflow must TRAP (documented checked arithmetic), never wrap.
let trapped = false; try { t(9223372036854775807n, 2n); } catch (e) { trapped = true; }
if (!trapped) { console.error("FAIL times(MAX,2) did not trap"); process.exit(1); }
try { t(-1n, -9223372036854775808n); console.error("FAIL times(-1,MIN) did not trap"); process.exit(1); } catch (e) {}
NODE
then pass=$((pass + 1)); else echo "  FAIL wasm_i64_multiply (rc=$?)"; fail=$((fail + 1)); fi
if [[ "$fail" -ne 0 ]]; then echo "wasm_integer_width FAILED: $pass passed, $fail failed"; exit 1; fi
echo "wasm_integer_width OK: $pass modules validated, instantiated with memory only, and answered by hand-fixed values"
