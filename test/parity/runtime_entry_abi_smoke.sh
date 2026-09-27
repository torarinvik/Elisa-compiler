#!/usr/bin/env bash
# The runtime object's entry points must keep the names and arities programs link against.
#
# stage1 compiles the runtime AND pre-declares some of its entry points while doing so
# (codegen_runtime_decl). When the definition's LLVM type differs from that declaration,
# the library reconciliation cannot rebind the handle and LLVM renames the definition
# `name.N`: the object then exports `_ctx_packed_store_alloc_fixed_tagged_variant_sparse_result.9`
# and every program referencing the plain name fails to link. The cause was 26 functions
# taking an explicit `Arena` that region inference also gave a hidden arena slot, which
# stage0's `funcHasArenaParam` rule forbids (codegen_abi_regions: params_manage_arena).
#
# Checks: (1) no `.N`-renamed definition outside the allowlist below; (2) when stage0 is
# available, every function both compilers define has the same parameter count; (3) the
# rule's consequence: without a hidden slot, an Arena-taking function growing a reference
# parameter outside `in a:` has no region to grow into. stage0 rejects it; stage1 used to
# grow into its own auto region and free it on return (UAF), and now declines.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
SRC="$ROOT/elisacore_std/native_runtime_support.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-runtime-abi.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

ELISA_STAGE1_RUNTIME_STD=1 "$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$SRC"

# Top-level overloads are still named by LLVM's collision rename rather than stage0's
# `__ovl__print__dstr__print` / `cast__A__to__B__Lx_Cy` mangling: a known symbol-parity
# gap, not a declaration collision. Anything else suffixed is a new collision.
ALLOWED_SUFFIXED='^(__cast__\.1|__cast__\.1\.12|print\.1|printr\.1)$'
renamed="$(grep -oE '^define [^@]*@"?[A-Za-z_][A-Za-z0-9_:]*(\.[0-9]+)+"?\(' "$WORK/stage1.ll" \
    | sed -E 's/^define [^@]*@"?([^"(]*)"?\($/\1/' | grep -vE "$ALLOWED_SUFFIXED" || true)"
[[ -z "$renamed" ]] || {
    echo "runtime entry ABI smoke FAILED: renamed runtime definitions (declaration type collision?):" >&2
    printf '  %s\n' $renamed >&2
    exit 1
}

NEG="$ROOT/test/repro/arena_param_growth_outside_in.elisa"
POS="$ROOT/test/repro/arena_param_growth_in_block.elisa"
if "$STAGE1" -emit obj -o "$WORK/neg.o" "$NEG" > "$WORK/neg.log" 2>&1; then
    echo 'runtime entry ABI smoke FAILED: Arena-param growth outside `in a:` was accepted' >&2
    exit 1
fi
[[ ! -e "$WORK/neg.o" ]] || { echo 'runtime entry ABI smoke FAILED: rejection left an artifact' >&2; exit 1; }
for fn in mixed2 plain_arena; do
    grep -q "$fn@[0-9]* (reference parameter grown outside \`in <arena>:\`" "$WORK/neg.log" \
        || { cat "$WORK/neg.log" >&2; echo "runtime entry ABI smoke FAILED: $fn not declined for growth outside in" >&2; exit 1; }
done
"$STAGE1" -emit llvm -O0 -o "$WORK/pos1.ll" "$POS"

if [[ ! -x "$STAGE0" ]]; then
    echo "runtime entry ABI smoke: SKIP arity parity (stage0 not found at $STAGE0)" >&2
    echo 'runtime entry ABI smoke OK (rename check only)'
    exit 0
fi
ELISA_ALLOW_STALE_STAGE0=1 "$STAGE0" -emit llvm -O0 -o "$WORK/stage0.ll" "$SRC"
ELISA_ALLOW_STALE_STAGE0=1 "$STAGE0" -emit llvm -O0 -o "$WORK/pos0.ll" "$POS"

# Known, deliberate-or-scoped arity residue (stage1 one higher):
#   ctx_fstr_alloc          returns dstr: stage1 adds a caller-region slot the body never
#                           uses (it allocates with alloc_perm); stage0 does not.
#   arena_dict_reserve__i64 `-> void error[...]`: stage1 passes an error out-pointer even
#                           for a void result; stage0 omits it. Consistent inside stage1.
python3 - "$WORK/stage0.ll" "$WORK/stage1.ll" "$WORK/pos0.ll" "$WORK/pos1.ll" <<'PY'
import re, sys
ALLOWED = {"ctx_fstr_alloc", "arena_dict_reserve__i64"}
def arities(path):
    table = {}
    for line in open(path):
        m = re.match(r'define [^@]*@("?[^(" ]+"?)\((.*)\)\s*(#\d+)?\s*\{', line)
        if not m:
            continue
        args = m.group(2).strip()
        table[m.group(1).strip('"')] = 0 if args == "" else len(re.split(r',(?![^{]*\})', args))
    return table
s0, s1 = arities(sys.argv[1]), arities(sys.argv[2])
common = set(s0) & set(s1)
bad = sorted(k for k in common if s0[k] != s1[k] and k not in ALLOWED)
if len(common) < 400:
    sys.exit(f"runtime entry ABI smoke FAILED: only {len(common)} common definitions; the IR parse is broken")
if bad:
    for k in bad:
        print(f"  {k}: stage0={s0[k]} stage1={s1[k]}", file=sys.stderr)
    sys.exit(f"runtime entry ABI smoke FAILED: {len(bad)} runtime arity mismatches vs stage0")
p0, p1 = arities(sys.argv[3]), arities(sys.argv[4])
pbad = sorted(k for k in set(p0) & set(p1) if p0[k] != p1[k])
if len(set(p0) & set(p1)) < 4 or pbad:
    sys.exit(f"runtime entry ABI smoke FAILED: in-block growth fixture arity mismatches vs stage0: {pbad or 'too few common functions'}")
print(f"runtime entry ABI smoke OK: {len(common)} common definitions, arities match stage0 (allowlisted: {len(ALLOWED)})")
PY
