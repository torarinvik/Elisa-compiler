#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
if [ ! -x "$ELISACORE_BIN" ] || [ ! -x "$LLVM_CONFIG" ]; then
    echo "easm_memory_direction_smoke SKIP: stage0 compiler or llvm-config not found"
    exit 0
fi
if ! "$ROOT/test/parity/easm_project_driver_smoke.sh" >/dev/null 2>&1; then
    echo "easm_memory_direction_smoke FAILED: project driver could not be built"
    exit 1
fi
mkdir -p "$ROOT/build/direction_bad" "$ROOT/build/direction_good" "$ROOT/build/register_rmw_bad" "$ROOT/build/register_zero_good" "$ROOT/build/address_register_bad" "$ROOT/build/address_index_bad" "$ROOT/build/direction_fpu_bad"
cp "$ROOT/test/fixtures/easm/direction_rmw_bad.easm" "$ROOT/build/direction_bad/input.easm"
cp "$ROOT/test/fixtures/easm/direction_rmw_good.easm" "$ROOT/build/direction_good/input.easm"
cp "$ROOT/test/fixtures/easm/register_rmw_bad.easm" "$ROOT/build/register_rmw_bad/input.easm"
cp "$ROOT/test/fixtures/easm/register_zero_good.easm" "$ROOT/build/register_zero_good/input.easm"
cp "$ROOT/test/fixtures/easm/address_register_bad.easm" "$ROOT/build/address_register_bad/input.easm"
cp "$ROOT/test/fixtures/easm/address_index_bad.easm" "$ROOT/build/address_index_bad/input.easm"
cp "$ROOT/test/fixtures/easm/direction_fpu_bad.easm" "$ROOT/build/direction_fpu_bad/input.easm"
bad=$(python3 "$ROOT/scripts/easm_project_driver.py" "$ROOT/build/direction_bad" --driver "$ROOT/build/easm_project_driver" --mode report)
good=$(python3 "$ROOT/scripts/easm_project_driver.py" "$ROOT/build/direction_good" --driver "$ROOT/build/easm_project_driver" --mode report)
register_bad=$(python3 "$ROOT/scripts/easm_project_driver.py" "$ROOT/build/register_rmw_bad" --driver "$ROOT/build/easm_project_driver" --mode report)
zero_good=$(python3 "$ROOT/scripts/easm_project_driver.py" "$ROOT/build/register_zero_good" --driver "$ROOT/build/easm_project_driver" --mode report)
address_bad=$(python3 "$ROOT/scripts/easm_project_driver.py" "$ROOT/build/address_register_bad" --driver "$ROOT/build/easm_project_driver" --mode report)
address_index_bad=$(python3 "$ROOT/scripts/easm_project_driver.py" "$ROOT/build/address_index_bad" --driver "$ROOT/build/easm_project_driver" --mode report)
fpu_bad=$(python3 "$ROOT/scripts/easm_project_driver.py" "$ROOT/build/direction_fpu_bad" --driver "$ROOT/build/easm_project_driver" --mode report)
case "$bad" in
    *"Issue memory-read-without-clobber"*) : ;;
    *) echo "easm_memory_direction_smoke FAILED: RMW read obligation was accepted"; printf '%s\n' "$bad"; exit 1 ;;
esac
case "$good" in
    *"Issue memory-read-without-clobber"*|*"Issue memory-write-without-clobber"*) echo "easm_memory_direction_smoke FAILED: broad memory contract was rejected"; printf '%s\n' "$good"; exit 1 ;;
    *) : ;;
esac
case "$register_bad" in
    *"Issue register-read-uninitialized"*) echo "easm_memory_direction_smoke OK" ;;
    *) echo "easm_memory_direction_smoke FAILED: RMW destination read was accepted"; printf '%s\n' "$register_bad"; exit 1 ;;
esac
case "$zero_good" in
    *"Issue register-read-uninitialized"*) echo "easm_memory_direction_smoke FAILED: self-zeroing idiom was rejected"; printf '%s\n' "$zero_good"; exit 1 ;;
    *) : ;;
esac
case "$address_bad" in
    *"Issue register-read-uninitialized"*) echo "easm_memory_direction_smoke OK" ;;
    *) echo "easm_memory_direction_smoke FAILED: uninitialized memory base was accepted"; printf '%s\n' "$address_bad"; exit 1 ;;
esac
case "$fpu_bad" in
    *"Issue memory-read-without-clobber"*"Issue memory-write-without-clobber"*) echo "easm_memory_direction_smoke OK" ;;
    *) echo "easm_memory_direction_smoke FAILED: FPU memory direction was not enforced"; printf '%s\n' "$fpu_bad"; exit 1 ;;
esac
case "$address_index_bad" in
    *"Issue register-read-uninitialized"*) echo "easm_memory_direction_smoke OK" ;;
    *) echo "easm_memory_direction_smoke FAILED: uninitialized indexed address registers were accepted"; printf '%s\n' "$address_index_bad"; exit 1 ;;
esac
