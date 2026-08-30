#!/usr/bin/env bash
# The stage1-COMPILED semantic layer must analyse IDENTICALLY to the stage0-compiled one.
#
# This was the one blocker to running the analyzer by default, and it is CLOSED: the gate is
# now ON unless ELISA_STAGE1_NO_SEMANTIC_GATE=1. The check stays because the property it
# guards is not self-evident — every generation of the bootstrap skips or runs the check
# together, so a fixpoint cannot see a divergence in the checker itself. Only running the
# SAME source through a stage0-built driver and a stage1-built one can.
#
#   identical source through both drivers, both with the gate active:
#     stage0-built driver (bin/elisac-stage1, the seed)  -> exit 0
#     stage1-built driver (gen2)                          -> exit 0
#
# What it took to get here (each hid the next):
#   * `d <- d.put(k, v)` stored the helper's RETURN VALUE over the dict header;
#   * the deep packed pattern's probe ladder read the next level's handle without first
#     branching on the current level's tag, so a direct call `f(x)` walked an Ident's payload
#     as a node handle;
#   * `for b in sview(literal, 0, -1)` compared the index UNSIGNED, so the std's
#     NUL-terminated sentinel read as 2^64-1;
#   * `scope` was an UNGUARDED contextual block keyword, so `scope.push(x)` parsed as a
#     `scope:` block — Semantic.mark_mutable_locals' parameter is named `scope`, and that one
#     bug produced 319 E10 false positives on the compiler's own source;
#   * string literals reached LLVM with their escapes undecoded.
#
# The FAST oracle for any future divergence is parse_report built by BOTH compilers, diffed
# per file (<1s each, no gen2 needed) — it is what localised all of the above:
#   REPO_ROOT=$PWD ELISACORE_BIN="../../Go projects/structpy-tree/compiler/bin/elisac" bash test/parity/build_parse_report.sh
#   bash scripts/elisac_stage1.sh -o /tmp/pr.o test/breadth/parse_report.elisa
#   clang -Wl,-dead_strip -o /tmp/pr_s1 /tmp/pr.o build/runtime/elisacore_runtime.o
#   ./build/parse_report < F.elisa ; /tmp/pr_s1 < F.elisa
# Currently 505 of 507 sources agree; the two that differ are the same severity-2 warning
# (a missed `pointer cast requires can[Unsafe]`), which does not gate acceptance.
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
        | "$1" >/dev/null 2>&1
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
    echo "semantic_gate_selfhost FAILED: stage1-built gen2 gave $gen2_exit, stage0-built gave 0"
    [ "$gen2_exit" -eq 139 ] && echo "  (139 = SIGSEGV — memory corruption, not a diagnostic)"
    [ "$gen2_exit" -eq 124 ] && echo "  (124 = TIMED OUT — a hang, not a wrong answer)"
    echo "  the semantic layer computes differently when STAGE1 compiles it — a REGRESSION."
    echo "  Localise it with the parse_report oracle in the header comment, not by bisecting gen2."
    exit 1
fi

echo "semantic_gate_selfhost OK: gen2 analyses identically to the stage0-built driver"
