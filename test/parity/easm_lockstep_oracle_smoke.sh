#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LLVM_MC="${LLVM_MC:-/opt/homebrew/opt/llvm/bin/llvm-mc}"
CLANG="${CLANG:-$(command -v clang || true)}"
if [ ! -x "$LLVM_MC" ] || [ -z "$CLANG" ]; then
    echo "easm_lockstep_oracle_smoke SKIP: llvm-mc or clang not found"
    exit 0
fi
equiv=$(python3 "$ROOT/scripts/easm_lockstep_oracle.py" "$ROOT/test/fixtures/easm/lockstep_memory_equiv.easm" --llvm-mc "$LLVM_MC" --clang "$CLANG")
python3 -c 'import json,sys; assert json.loads(sys.argv[1])["results"][0]["status"] == "proved"' "$equiv" || { echo "easm_lockstep_oracle_smoke FAILED: memory-equivalent bodies were not proved"; echo "$equiv"; exit 1; }
if python3 "$ROOT/scripts/easm_lockstep_oracle.py" "$ROOT/test/fixtures/easm/lockstep_memory_diverged.easm" --llvm-mc "$LLVM_MC" --clang "$CLANG" >/tmp/easm_lockstep_oracle_diverged.json; then
    echo "easm_lockstep_oracle_smoke FAILED: divergent memory bodies were accepted"
    exit 1
fi
python3 -c 'import json; assert json.load(open("/tmp/easm_lockstep_oracle_diverged.json"))["results"][0]["status"] == "diverged"'
branch=$(python3 "$ROOT/scripts/easm_lockstep_oracle.py" "$ROOT/test/fixtures/easm/lockstep_branch_equiv.easm" --llvm-mc "$LLVM_MC" --clang "$CLANG")
python3 -c 'import json,sys; assert json.loads(sys.argv[1])["results"][0]["status"] == "proved"' "$branch" || { echo "easm_lockstep_oracle_smoke FAILED: conditional equivalent bodies were not proved"; echo "$branch"; exit 1; }
if python3 "$ROOT/scripts/easm_lockstep_oracle.py" "$ROOT/test/fixtures/easm/lockstep_branch_diverged.easm" --llvm-mc "$LLVM_MC" --clang "$CLANG" >/tmp/easm_lockstep_oracle_branch_diverged.json; then
    echo "easm_lockstep_oracle_smoke FAILED: divergent conditional bodies were accepted"
    exit 1
fi
python3 -c 'import json; assert json.load(open("/tmp/easm_lockstep_oracle_branch_diverged.json"))["results"][0]["status"] == "diverged"'
echo "easm_lockstep_oracle_smoke OK"
