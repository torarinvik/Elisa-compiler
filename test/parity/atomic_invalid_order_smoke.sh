#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-atomic-invalid-order.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE1" ]] || { echo "atomic invalid-order smoke: missing Stage1 compiler: $STAGE1" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

for optimization in 0 2; do
for fixture in \
    "$ROOT/test/repro/atomic_invalid_load_order.elisa" \
    "$ROOT/test/repro/atomic_invalid_store_order.elisa" \
    "$ROOT/test/repro/atomic_invalid_fence_order.elisa" \
    "$ROOT/test/repro/atomic_invalid_compare_exchange_order.elisa"; do
    name="$(basename -- "$fixture" .elisa)"
    output="$WORK/$name-O$optimization.o"
    log="$WORK/$name-O$optimization.log"
    if ELISA_STAGE1_RUNTIME_STD=1 "$STAGE1" -emit obj "-O$optimization" -o "$output" "$fixture" >"$log" 2>&1; then
        echo "atomic invalid-order smoke: accepted $name at O$optimization" >&2
        exit 1
    fi
    [[ ! -e "$output" ]] || { echo "atomic invalid-order smoke: emitted an object for $name at O$optimization" >&2; exit 1; }
    grep -qi 'declin\|unsupported\|invalid' "$log" || {
        echo "atomic invalid-order smoke: refusal had no actionable diagnostic for $name at O$optimization" >&2
        cat "$log" >&2
        exit 1
    }
done
done

# AtomicSlot is an internal storage type behind AtomicCell. Keep the raw operation
# surface fenced after the runtime slot rename; compiling the included stdlib is not
# the same as granting user code the runtime-std exemption.
for optimization in 0 2; do
    output="$WORK/atomic_slot_raw_access-O$optimization.o"
    log="$WORK/atomic_slot_raw_access-O$optimization.log"
    if "$STAGE1" -emit obj "-O$optimization" -o "$output" "$ROOT/test/repro/atomic_slot_raw_access.elisa" >"$log" 2>&1; then
        echo "atomic invalid-order smoke: accepted public AtomicSlot access at O$optimization" >&2
        exit 1
    fi
    [[ ! -e "$output" ]] || { echo "atomic invalid-order smoke: emitted an object for raw AtomicSlot access at O$optimization" >&2; exit 1; }
    grep -q 'raw concurrency surface removed: `load` is legacy raw atomic surface' "$log" || {
        echo "atomic invalid-order smoke: raw AtomicSlot refusal had no expected diagnostic at O$optimization" >&2
        cat "$log" >&2
        exit 1
    }
done

for optimization in 0 2; do
    output="$WORK/atomic_same_named_slot_user_function-O$optimization"
    log="$WORK/atomic_same_named_slot_user_function-O$optimization.log"
    if ! "$STAGE1" -emit exe "-O$optimization" -o "$output" "$ROOT/test/repro/atomic_same_named_slot_user_function.elisa" >"$log" 2>&1; then
        echo "atomic invalid-order smoke: failed to compile the same-named user load at O$optimization" >&2
        cat "$log" >&2
        exit 1
    fi
    set +e
    "$output"
    result=$?
    set -e
    [[ "$result" -eq 42 ]] || {
        echo "atomic invalid-order smoke: same-named user load returned $result at O$optimization, expected 42" >&2
        exit 1
    }
done

for optimization in 0 2; do
    output="$WORK/atomic_same_named_i32_load-O$optimization"
    log="$WORK/atomic_same_named_i32_load-O$optimization.log"
    if ! "$STAGE1" -emit exe "-O$optimization" -o "$output" "$ROOT/test/repro/atomic_same_named_i32_load.elisa" >"$log" 2>&1; then
        echo "atomic invalid-order smoke: failed to compile the i32 overload at O$optimization" >&2
        cat "$log" >&2
        exit 1
    fi
    set +e
    "$output"
    result=$?
    set -e
    [[ "$result" -eq 42 ]] || { echo "atomic invalid-order smoke: i32 overload returned $result at O$optimization, expected 42" >&2; exit 1; }
done

# Keep this declaration-only helper at O0: the O2 pipeline correctly removes it as an
# unreferenced internal function, which would make an IR-presence assertion meaningless.
ir="$WORK/atomic_typed_order_parameter-O0.ll"
log="$WORK/atomic_typed_order_parameter-O0.log"
if ! ELISA_STAGE1_RUNTIME_STD=1 "$STAGE1" -emit llvm -O0 -o "$ir" "$ROOT/test/repro/atomic_typed_order_parameter.elisa" >"$log" 2>&1; then
    echo "atomic invalid-order smoke: failed to lower a typed MemoryOrder parameter" >&2
    cat "$log" >&2
    exit 1
fi
grep -Eq 'load atomic i64, .* seq_cst' "$ir" || {
    echo "atomic invalid-order smoke: typed MemoryOrder parameter did not retain atomic lowering" >&2
    exit 1
}

echo "atomic order smoke OK: invalid literals and public AtomicSlot access fail closed, same-named and i32 user overloads preserve their bodies at O0/O2, and typed MemoryOrder parameters remain atomic"
