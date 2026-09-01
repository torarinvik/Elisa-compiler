#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-/tmp/elisac-stage0-local}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/fixtures/backend/extern_view_param.elisa"

if [ ! -x "$STAGE0" ] || [ ! -x "$STAGE1" ]; then
    echo "extern_view_abi_smoke SKIP: local stage0/stage1 compiler is unavailable"
    exit 0
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/structpy-tree}"
export ELISA_CORE

"$STAGE0" -emit llvm -o "$WORK/stage0.ll" "$FIXTURE"
"$STAGE1" -emit llvm -o "$WORK/stage1.ll" "$FIXTURE"

for ir in "$WORK/stage0.ll" "$WORK/stage1.ll"; do
    rg -q 'declare void @consume\(%DynArrayView\)' "$ir"
    rg -q 'define i64 @f\(%DynArrayView' "$ir"
    rg -q 'call void @consume\(%DynArrayView' "$ir"
done

echo "extern_view_abi_smoke OK: view[T] extern parameters lower by value in both compilers"
