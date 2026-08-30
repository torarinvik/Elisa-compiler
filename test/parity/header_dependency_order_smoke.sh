#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
FIXTURE="$ROOT/test/repro/header_dependency_order.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

"$STAGE0" -emit header -o "$WORK/stage0.h" "$FIXTURE"
"$STAGE1" -emit header -o "$WORK/stage1.h" "$FIXTURE"
cmp "$WORK/stage0.h" "$WORK/stage1.h"

echo "header dependency-order parity OK"
