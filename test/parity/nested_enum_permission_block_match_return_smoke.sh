#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/nested-enum-match-return.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
FIXTURE="$ROOT/test/repro/nested_enum_permission_block_match_return.elisa"
"$STAGE1" -emit exe -O0 -o "$WORK/regression" "$FIXTURE"
"$WORK/regression"
echo "nested enum permission-block match return smoke OK"
