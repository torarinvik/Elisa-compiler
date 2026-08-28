#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"

if [[ ! -x "$ROOT/bin/elisac-stage1" || ! -x "$CLANG" || ! -f "$ROOT/build/runtime/elisacore_runtime.o" ]]; then
    echo "threaded region ownership smoke SKIP (stage1/clang/runtime unavailable)"
    exit 0
fi

bash "$ROOT/scripts/elisac_stage1.sh" -emit obj -o "$WORK/threaded.o" \
    "$ROOT/test/repro/region_threaded_nested_temporary.elisa" >/dev/null
"$CLANG" -fno-builtin -o "$WORK/threaded" "$WORK/threaded.o" \
    "$ROOT/build/runtime/elisacore_runtime.o" "$ROOT/scripts/pymodule_runtime_fallback.c"

set +e
"$WORK/threaded"
result=$?
set -e
if [[ "$result" -ne 42 ]]; then
    echo "threaded region ownership smoke FAIL: exit $result, want 42" >&2
    exit 1
fi

echo "threaded region ownership smoke OK"
