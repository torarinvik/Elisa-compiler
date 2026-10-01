#!/usr/bin/env bash
# Stage1 regression: local parameter shadows foreign global (test/repro/local_param_shadows_foreign_global.elisa).
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
FIXTURE="$ROOT/test/repro/local_param_shadows_foreign_global.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-local_param_shadows_foreign_global.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

"$STAGE1" -emit exe -O0 -o "$WORK/stage1" "$FIXTURE"
"$WORK/stage1"

echo "local parameter shadows foreign global OK"
