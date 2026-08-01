#!/usr/bin/env bash
# THE ONE BLOCKER to defaulting the semantic gate ON: a stage1-COMPILED semantic layer
# miscompiles, and the resulting analyzer corrupts memory.
#
# NOT wired into run_all.sh — it FAILS today by design. It is the executable form of the
# bug so a future fix is verified rather than assumed, and so the regression cannot be
# forgotten. Wire it into run_all.sh in the same commit that fixes the miscompile.
#
#   ELISA_STAGE1_SEMANTIC_GATE=1, identical source through both drivers:
#     stage0-built driver (bin/elisac-stage1, the seed)  -> exit 0   ACCEPTS
#     stage1-built driver (gen2)                          -> exit 139 SIGSEGV
#
#   lldb puts the fault in `arena_dict_find_index__u64__unknown` — a dict probe whose
#   generic instantiation carries an UNRESOLVED value type (`__unknown` where `sview`
#   belongs). SymbolTable.name_primary is `mutable dict[u64, sview]`.
#
# Everything the ANALYSIS needs is already done: with the gate on, the corpus is at
# baseline (49 match / 0 mismatch / 3 declined), scope_binding_smoke is 79/79, and the
# compiler's own source has ZERO error-severity findings. Only this miscompile blocks the
# default.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
SEED="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
GEN2="$ROOT/build/self_host_gen2/elisac-stage1-gen2"

[ -x "$SEED" ] || { echo "semantic_gate_selfhost SKIP: no seed at $SEED"; exit 0; }
[ -x "$GEN2" ] || { echo "semantic_gate_selfhost SKIP: no gen2 (run scripts/self_host_gen2.sh)"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

# The smallest input that reproduces: a function, and a CALL to it. A program that never
# looks a name up (no call) exits 0 even under the broken build, so the call is essential.
cat > "$WORK/prog.elisa" <<'ELISAEOF'
def f(n: i64) -> i64:
    return n + 1

def main() -> i64:
    return f(0)
ELISAEOF

run_driver() {
    { printf '%s\n' "$WORK/out.o"; cat "$WORK/prog.elisa"; } \
        | ELISA_STAGE1_SEMANTIC_GATE=1 "$1" >/dev/null 2>&1
    echo $?
}

seed_exit="$(run_driver "$SEED")"
gen2_exit="$(run_driver "$GEN2")"

if [ "$seed_exit" -ne 0 ]; then
    echo "semantic_gate_selfhost FAILED: the STAGE0-built driver rejected a valid program (exit $seed_exit)"
    echo "  the check itself is broken, not stage1 — fix this before reading the gen2 result"
    exit 1
fi

if [ "$gen2_exit" -ne 0 ]; then
    echo "semantic_gate_selfhost FAILED (EXPECTED TODAY): stage1-built gen2 gave $gen2_exit, stage0-built gave 0"
    [ "$gen2_exit" -eq 139 ] && echo "  (139 = SIGSEGV — memory corruption, not a diagnostic)"
    [ "$gen2_exit" -eq 124 ] && echo "  (124 = TIMED OUT — a hang, not a wrong answer)"
    echo "  the semantic layer computes differently when STAGE1 compiles it; see"
    echo "  the memory note 'Semantic layer over-reporting' for the causal chain and dead ends"
    exit 1
fi

echo "semantic_gate_selfhost OK: gen2 analyses identically to the stage0-built driver"
echo "  -> the miscompile is FIXED; wire this into run_all.sh and default the gate ON"
echo "     (src/driver/elisac.elisa: semantic_gate_enabled)"
