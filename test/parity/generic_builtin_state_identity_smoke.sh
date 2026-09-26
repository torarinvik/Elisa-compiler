#!/usr/bin/env bash
# State markers have no runtime representation, but distinct generic identities.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-state-identity.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
for level in 0 2; do
    "$STAGE1" -emit obj "-O$level" -o "$WORK/state.o" "$ROOT/test/repro/generic_builtin_state_identity.elisa"
    "${ELISA_CLANG:-clang}" -o "$WORK/state" "$WORK/state.o"
    set +e
    "$WORK/state"
    status=$?
    set -e
    [[ "$status" == 42 ]] || { echo "state identity: runtime=$status, expected 42" >&2; exit 1; }
    output="$WORK/storage-O$level.ll"
    if "$STAGE1" -emit llvm "-O$level" -o "$output" "$ROOT/test/repro/generic_builtin_state_runtime_storage.elisa" > "$WORK/storage.log" 2>&1; then
        echo 'state identity: accepted runtime storage of Held' >&2
        exit 1
    fi
    [[ ! -e "$output" ]] || { echo 'state identity: rejection left LLVM output' >&2; exit 1; }
    rg -q 'cannot initialize|backend declined|could not produce|unmodeled' "$WORK/storage.log" || { cat "$WORK/storage.log" >&2; exit 1; }
done
"$STAGE1" -emit llvm -O0 -o "$WORK/state.ll" "$ROOT/test/repro/generic_builtin_state_identity.elisa"
for state in Local Frozen Joinable Pending Held; do
    rg -q "^%Token__$state = type \\{ i64 \\}" "$WORK/state.ll"
    rg -q "^define .*@identity__Token_$state\\(" "$WORK/state.ll"
done
! rg -q 'Token__unknown|identity__Token_unknown' "$WORK/state.ll"
echo 'builtin state identity smoke OK: five distinct types and specializations; runtime=42 at O0/O2'
