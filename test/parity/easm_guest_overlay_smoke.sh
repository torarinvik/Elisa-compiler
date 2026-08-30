#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
if [ ! -x "$ELISACORE_BIN" ] || [ ! -x "$LLVM_CONFIG" ]; then
    echo "easm_guest_overlay_smoke SKIP: stage0 compiler or llvm-config not found"
    exit 0
fi
if ! "$ROOT/test/parity/easm_project_driver_smoke.sh" >/dev/null 2>&1; then
    echo "easm_guest_overlay_smoke FAILED: project driver could not be built"
    exit 1
fi
mkdir -p "$ROOT/build/overlay_weak" "$ROOT/build/overlay_strong"
cp "$ROOT/test/fixtures/easm/overlay_weak_guard.easm" "$ROOT/build/overlay_weak/input.easm"
cp "$ROOT/test/fixtures/easm/overlay_strong_guard.easm" "$ROOT/build/overlay_strong/input.easm"
weak=$(python3 "$ROOT/scripts/easm_project_driver.py" "$ROOT/build/overlay_weak" --driver "$ROOT/build/easm_project_driver" --mode report)
strong=$(python3 "$ROOT/scripts/easm_project_driver.py" "$ROOT/build/overlay_strong" --driver "$ROOT/build/easm_project_driver" --mode report)
case "$weak" in
    *"Issue overlay-field-needs-size-guard"*) : ;;
    *) echo "easm_guest_overlay_smoke FAILED: weak size guard was accepted"; printf '%s\n' "$weak"; exit 1 ;;
esac
case "$strong" in
    *"Issue overlay-field-needs-size-guard"*) echo "easm_guest_overlay_smoke FAILED: strong size guard was rejected"; printf '%s\n' "$strong"; exit 1 ;;
    *) echo "easm_guest_overlay_smoke OK" ;;
esac
