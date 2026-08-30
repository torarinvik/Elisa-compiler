#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
if [ ! -x "$ELISACORE_BIN" ] || [ ! -x "$LLVM_CONFIG" ]; then
    echo "easm_frame_provenance_smoke SKIP: stage0 compiler or llvm-config not found"
    exit 0
fi
if ! "$ROOT/test/parity/easm_project_driver_smoke.sh" >/dev/null 2>&1; then
    echo "easm_frame_provenance_smoke FAILED: project driver could not be built"
    exit 1
fi
mkdir -p "$ROOT/build/frame_bad" "$ROOT/build/frame_good"
cp "$ROOT/test/fixtures/easm/frame_propagated_bad.easm" "$ROOT/build/frame_bad/input.easm"
cp "$ROOT/test/fixtures/easm/frame_propagated_good.easm" "$ROOT/build/frame_good/input.easm"
bad=$(python3 "$ROOT/scripts/easm_project_driver.py" "$ROOT/build/frame_bad" --driver "$ROOT/build/easm_project_driver" --mode report)
good=$(python3 "$ROOT/scripts/easm_project_driver.py" "$ROOT/build/frame_good" --driver "$ROOT/build/easm_project_driver" --mode report)
case "$bad" in
    *"Issue frame-write-outside-changes"*) : ;;
    *) echo "easm_frame_provenance_smoke FAILED: propagated frame violation was accepted"; printf '%s\n' "$bad"; exit 1 ;;
esac
case "$good" in
    *"Issue frame-write-outside-changes"*) echo "easm_frame_provenance_smoke FAILED: authorized propagated write was rejected"; printf '%s\n' "$good"; exit 1 ;;
    *) echo "easm_frame_provenance_smoke OK" ;;
esac
