#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "affine-owner smoke FAIL: $1" >&2; exit 1; }

address=$(printf 'affine struct Handle:\n    raw: mutable uintptr\ndef bad(handle: Handle) -> void:\n    borrow: Handle& = &handle\n    _ = borrow\n' | "$RPT")
echo "$address" | grep -Fq 'cannot take address of linear value' || fail "address of affine owner accepted: $address"

global=$(printf 'affine struct Handle:\n    raw: mutable uintptr\nglobal current: Handle = zeroed\n' | "$RPT")
echo "$global" | grep -Fq 'global "current" cannot store linear handle values of type Handle' || fail "affine global accepted: $global"

plain=$(printf 'struct Value:\n    raw: mutable uintptr\ndef ok(value: Value) -> void:\n    borrow: Value& = &value\n    _ = borrow\n' | "$RPT")
echo "$plain" | grep -Fq 'linear value' && fail "ordinary struct address rejected: $plain"

containing=$(printf 'struct Holder:\n    thread: mutable Thread[i64, Joinable]\ndef bad_param(holder: Holder&) -> void:\n    pass\ndef bad_local(holder: Holder) -> void:\n    alias: Holder& = &holder\n    _ = alias\n' | "$RPT")
echo "$containing" | grep -Fq 'references to values containing linear handles are not supported; got Holder&' || fail "reference to affine-containing struct accepted: $containing"
echo "$containing" | grep -Fq 'cannot take address of linear value' || fail "address of affine-containing struct accepted: $containing"

aggregate_global=$(printf 'struct Holder:\n    thread: mutable Thread[i64, Joinable]\nglobal current_thread: Thread[i64, Joinable] = zeroed\nglobal current_holder: Holder = zeroed\n' | "$RPT")
echo "$aggregate_global" | grep -Fq 'global "current_thread" cannot store linear handle values of type Thread' || fail "direct affine global accepted: $aggregate_global"
echo "$aggregate_global" | grep -Fq 'global "current_holder" cannot store linear handle values of type Holder' || fail "affine-containing global accepted: $aggregate_global"

echo "affine-owner smoke OK: user affine refs/globals rejected; ordinary structs unaffected"
