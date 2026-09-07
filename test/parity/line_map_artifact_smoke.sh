#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURE="$ROOT/test/parity/line_map_artifact_fixture.elisa"
BUILD="$(mktemp -d "${TMPDIR:-/tmp}/elisa-line-map.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

ELISA_STAGE1_LINE_MAP_OUTPUT="$BUILD/source-map.txt" \
    "$ROOT/scripts/elisac_stage1.sh" -emit obj -o "$BUILD/program.o" "$FIXTURE" \
    >"$BUILD/compiler.out" 2>"$BUILD/compiler.err"

test -s "$BUILD/source-map.txt"
grep -q ":1:.*line_map_artifact_fixture\.elisa$" "$BUILD/source-map.txt"
grep -q ":1:.*line_map_artifact_helper\.elisa$" "$BUILD/source-map.txt"
test -s "$BUILD/program.o"
echo "line_map_artifact_smoke: ok"
