#!/usr/bin/env bash
# Standing product gate: stage1 product binary compiles a fixed fixture to a
# native object that links and runs with exit 42 — without invoking stage0.
#
# Seed (once, allowed): scripts/elisac_stage1.sh --seed
# After seed, this smoke unsets ELISACORE_BIN and refuses a Go bootstrap path.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRATCH_DIR="${STAGE1_PRODUCT_SCRATCH:-$ROOT/build/stage1_product_smoke}"
mkdir -p "$SCRATCH_DIR"
BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WRAPPER="$ROOT/scripts/elisac_stage1.sh"
RUNTIME="$ROOT/build/runtime/elisacore_runtime.o"

if [[ ! -x "$BIN" ]]; then
  echo "stage1_product_smoke FAIL: missing product binary $BIN (run scripts/elisac_stage1.sh --seed once)" >&2
  exit 1
fi
if [[ ! -x "$WRAPPER" ]]; then
  echo "stage1_product_smoke FAIL: missing $WRAPPER" >&2
  exit 1
fi
if [[ ! -f "$RUNTIME" ]]; then
  echo "stage1_product_smoke FAIL: missing runtime object $RUNTIME" >&2
  exit 1
fi

# Isolate from stage0: no ELISACORE_BIN, no ~/.elisac on PATH for the compile step.
unset ELISACORE_BIN || true
export ELISA_STAGE1_BIN="$BIN"
export PATH="/usr/bin:/bin:/opt/homebrew/bin:/opt/homebrew/opt/llvm/bin"

fixture="$SCRATCH_DIR/fixture.elisa"
obj="$SCRATCH_DIR/fixture.o"
prog="$SCRATCH_DIR/fixture_prog"
cat >"$fixture" <<'EOF'
def main() -> i64:
    return 42
EOF

bash "$WRAPPER" -o "$obj" "$fixture"
[[ -f "$obj" && -s "$obj" ]] || { echo "stage1_product_smoke FAIL: no object"; exit 1; }

# The complete runtime object intentionally contains platform callback/varargs
# bridges whose foreign implementations are only needed by programs that use
# those APIs. Dead-strip unused runtime sections so a scalar fixture does not
# require every optional host bridge at link time.
clang -Wl,-dead_strip -o "$prog" "$obj" "$RUNTIME"
got="$("$prog"; echo $?)"
# prog exit is in $?, capture carefully
set +e
"$prog"
got=$?
set -e
if [[ "$got" -ne 42 ]]; then
  echo "stage1_product_smoke FAIL: exit $got want 42" >&2
  exit 1
fi

# Prove we did not invoke stage0 Go elisac during the compile: product binary path.
if ! file "$BIN" | grep -q 'Mach-O\|ELF'; then
  echo "stage1_product_smoke FAIL: product binary not a native executable" >&2
  exit 1
fi

echo "stage1_product_smoke OK: product $BIN compiled fixture → exit 42 (no stage0)"
