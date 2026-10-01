#!/usr/bin/env bash
# Stage1 regression: bare enum prefers current module (test/repro/bare_enum_prefers_current_module.elisa).
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
FIXTURE="$ROOT/test/repro/bare_enum_prefers_current_module.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-bare_enum_prefers_current_module.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

"$STAGE1" -emit exe -O0 -o "$WORK/stage1" "$FIXTURE"
"$WORK/stage1"

echo "bare enum prefers current module OK"
