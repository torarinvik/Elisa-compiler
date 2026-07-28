#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
if [ ! -x "$ELISACORE_BIN" ] || [ ! -x "$LLVM_CONFIG" ]; then
    echo "easm_preserve_smoke SKIP: stage0 compiler or llvm-config not found"
    exit 0
fi
if ! "$ROOT/test/parity/easm_project_driver_smoke.sh" >/dev/null 2>&1; then
    echo "easm_preserve_smoke FAILED: project driver could not be built"
    exit 1
fi
mkdir -p "$ROOT/build/preserve_bad" "$ROOT/build/preserve_good"
cp "$ROOT/test/fixtures/easm/preserve_bad.easm" "$ROOT/build/preserve_bad/input.easm"
cp "$ROOT/test/fixtures/easm/preserve_good.easm" "$ROOT/build/preserve_good/input.easm"
bad=$(python3 "$ROOT/scripts/easm_project_driver.py" "$ROOT/build/preserve_bad" --driver "$ROOT/build/easm_project_driver" --mode report)
good=$(python3 "$ROOT/scripts/easm_project_driver.py" "$ROOT/build/preserve_good" --driver "$ROOT/build/easm_project_driver" --mode report)
case "$bad" in
    *"Issue callee-saved-preservation-unproven"*) : ;;
    *) echo "easm_preserve_smoke FAILED: unproven preservation was accepted"; printf '%s\n' "$bad"; exit 1 ;;
esac
case "$good" in
    *"Issue callee-saved-preservation-unproven"*) echo "easm_preserve_smoke FAILED: save/restore preservation was rejected"; printf '%s\n' "$good"; exit 1 ;;
    *) echo "easm_preserve_smoke OK" ;;
esac
