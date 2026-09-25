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

echo "atomic invalid-order smoke OK: invalid load/store/fence/CAS orders fail closed at O0/O2"
