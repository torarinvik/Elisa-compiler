#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
if [ ! -x "$ELISACORE_BIN" ] || [ ! -x "$LLVM_CONFIG" ]; then
    echo "easm_memory_provenance_smoke SKIP: stage0 compiler or llvm-config not found"
    exit 0
fi
if ! "$ROOT/test/parity/easm_project_driver_smoke.sh" >/dev/null 2>&1; then
    echo "easm_memory_provenance_smoke FAILED: project driver could not be built"
    exit 1
fi
mkdir -p "$ROOT/build/provenance_raw" "$ROOT/build/provenance_lea" "$ROOT/build/provenance_typed"
cp "$ROOT/test/fixtures/easm/provenance_raw_copy.easm" "$ROOT/build/provenance_raw/input.easm"
cp "$ROOT/test/fixtures/easm/provenance_raw_lea.easm" "$ROOT/build/provenance_lea/input.easm"
cp "$ROOT/test/fixtures/easm/provenance_typed_copy.easm" "$ROOT/build/provenance_typed/input.easm"
raw=$(python3 "$ROOT/scripts/easm_project_driver.py" "$ROOT/build/provenance_raw" --driver "$ROOT/build/easm_project_driver" --mode report)
lea=$(python3 "$ROOT/scripts/easm_project_driver.py" "$ROOT/build/provenance_lea" --driver "$ROOT/build/easm_project_driver" --mode report)
typed=$(python3 "$ROOT/scripts/easm_project_driver.py" "$ROOT/build/provenance_typed" --driver "$ROOT/build/easm_project_driver" --mode report)
case "$raw" in
    *"Issue raw-memory-base"*) : ;;
    *) echo "easm_memory_provenance_smoke FAILED: copied raw carrier was accepted"; printf '%s\n' "$raw"; exit 1 ;;
esac
case "$lea" in
    *"Issue raw-memory-base"*) : ;;
    *) echo "easm_memory_provenance_smoke FAILED: lea-derived raw carrier was accepted"; printf '%s\n' "$lea"; exit 1 ;;
esac
case "$typed" in
    *"Issue raw-memory-base"*) echo "easm_memory_provenance_smoke FAILED: typed carrier was rejected as raw"; printf '%s\n' "$typed"; exit 1 ;;
    *) echo "easm_memory_provenance_smoke OK" ;;
esac
