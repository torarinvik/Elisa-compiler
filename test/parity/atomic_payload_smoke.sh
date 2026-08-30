#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "atomic-payload smoke FAIL: $1" >&2; exit 1; }

out=$(printf 'struct Pair:\n    left: i64\n    right: i64\ndef bad(slot: atomic[Pair]) -> void:\n    pass\n' | "$RPT")
echo "$out" | grep -Fq 'atomic payload type must satisfy atomic_safe(T), got Pair' || fail "aggregate payload accepted: $out"

out=$(printf 'def bad(slot: atomic[Thread[i64, Joinable]]) -> void:\n    pass\n' | "$RPT")
echo "$out" | grep -Fq 'atomic payload type must satisfy atomic_safe(T), got Thread' || fail "affine payload accepted: $out"

for scalar in i64 f64 bool u8\&; do
    out=$(printf 'def ok(slot: atomic[%s]) -> void:\n    pass\n' "$scalar" | "$RPT")
    echo "$out" | grep -Fq 'atomic payload type must satisfy atomic_safe' && fail "safe scalar payload rejected ($scalar): $out"
done

out=$(printf 'def bad(thread: Thread[i64]) -> void:\n    pass\n' | "$RPT")
echo "$out" | grep -Fq 'type "Thread" expects 2 type arguments, got 1' || fail "protocol arity mismatch accepted: $out"
out=$(printf 'def ok(thread: Thread[i64, Joinable], task: Task[i64, Pending]) -> void:\n    pass\n' | "$RPT")
echo "$out" | grep -Fq 'expects 2 type arguments' && fail "valid protocol carrier rejected: $out"

bool_rmw=$(printf 'enum MemoryOrder:\n    AcqRel\nextern fetch_or(slot: atomic[bool]&, value: bool, order: MemoryOrder) -> bool\ndef bad(slot: mutable atomic[bool]) -> bool:\n    slot_ref: atomic[bool]& = (&slot).cast[atomic[bool]&]\n    return fetch_or(slot_ref, true, MemoryOrder.AcqRel)\n' | "$RPT")
echo "$bool_rmw" | grep -Fq 'argument to "fetch_or" requires atomic_numeric(T), got atomic[bool]' || fail "bool atomic RMW accepted: $bool_rmw"
ref_rmw=$(printf 'enum MemoryOrder:\n    AcqRel\nextern fetch_xor(slot: atomic[u8&]&, value: u8&, order: MemoryOrder) -> u8&\ndef bad(slot: mutable atomic[u8&], value: u8&) -> u8&:\n    slot_ref: atomic[u8&]& = (&slot).cast[atomic[u8&]&]\n    return fetch_xor(slot_ref, value, MemoryOrder.AcqRel)\n' | "$RPT")
echo "$ref_rmw" | grep -Fq 'argument to "fetch_xor" requires atomic_numeric(T), got atomic[u8&]' || fail "pointer atomic RMW accepted: $ref_rmw"

echo "atomic-payload smoke OK: aggregate payloads rejected; numeric, bool, and pointer payloads accepted"
