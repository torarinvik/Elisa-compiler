#!/usr/bin/env bash
# A module-qualified generic error call must preserve both its owner and its
# callback value when specialized with affine contexts from a private module.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
SOURCE="$ROOT/test/repro/generic_affine_context_callback.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-generic-module-error-callback.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

"$STAGE0" -emit llvm -O0 -o "$WORK/stage0.ll" "$SOURCE" >/dev/null
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$SOURCE" >/dev/null
for output in "$WORK/stage0.ll" "$WORK/stage1.ll"; do
    ! rg -q '!elisa\.declined' "$output"
done

"$STAGE1" -emit exe -O0 -o "$WORK/probe" "$SOURCE" >/dev/null
set +e
"$WORK/probe"
status=$?
set -e
[[ "$status" -eq 37 ]] || { echo "generic module error callback returned $status, expected 37" >&2; exit 1; }

echo "generic module error callback smoke OK: qualified generic error call retains its module and affine callback arguments"
