#!/usr/bin/env bash
# A discarded `try` result is unused, but its error must still propagate.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/repro/discarded_try_propagates.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-discarded-try.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

"$STAGE0" -emit obj -O0 -o "$WORK/stage0.o" "$FIXTURE"
cc "$WORK/stage0.o" -o "$WORK/stage0"
"$STAGE1" -emit exe -O0 -o "$WORK/stage1" "$FIXTURE"

"$WORK/stage0"
"$WORK/stage1"
echo "discarded try propagation parity OK"
