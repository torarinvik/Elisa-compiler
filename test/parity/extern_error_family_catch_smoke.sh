#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac-stage0}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
SOURCE="$ROOT/test/repro/extern_error_family_catch.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-extern-error-catch.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "extern error-family catch smoke: missing Stage0 compiler: $STAGE0" >&2; exit 2; }
[[ -x "$STAGE1" ]] || { echo "extern error-family catch smoke: missing Stage1 compiler: $STAGE1" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

if ! "$STAGE0" -emit obj -O0 -o "$WORK/stage0.o" "$SOURCE" >"$WORK/stage0.log" 2>&1; then
    echo "extern error-family catch smoke: Stage0 failed to compile" >&2
    cat "$WORK/stage0.log" >&2
    exit 1
fi
if ! env -u ELISACORE_BIN -u ELISA_CORE -u REPO_ROOT \
    ELISA_STAGE1_BIN="$STAGE1" ELISA_RUNTIME_OBJ=none \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit obj -O0 -o "$WORK/stage1.o" "$SOURCE" >"$WORK/stage1.log" 2>&1; then
    echo "extern error-family catch smoke: Stage1 failed to compile" >&2
    cat "$WORK/stage1.log" >&2
    exit 1
fi

echo "extern error-family catch smoke OK: both stages lower catches over a payload-free extern error family"
