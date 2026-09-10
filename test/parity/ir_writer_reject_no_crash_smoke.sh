#!/usr/bin/env bash
# A partial parser source currently contains an integer AST shape that the v2 IR
# writer cannot faithfully encode. It must refuse by name, never bounds-trap while
# constructing the diagnostic bundle.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-ir-reject.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE1" ]] || { echo "IR writer rejection smoke SKIP: stage1 unavailable"; exit 0; }

set +e
"$STAGE1" -emit ir -O0 -o "$WORK/parser-core.elisair" "$ROOT/src/parser/parser_core.elisa" >"$WORK/log" 2>&1
status=$?
set -e

[[ "$status" -ne 0 ]] || { echo "IR writer rejection smoke FAIL: unsupported input was accepted"; exit 1; }
[[ "$status" -lt 128 ]] || { echo "IR writer rejection smoke FAIL: compiler terminated by signal (status $status)"; exit 1; }
rg -q -- "-emit ir cannot represent this construct yet:" "$WORK/log" || {
    echo "IR writer rejection smoke FAIL: expected refusal was not diagnosed"
    sed 's/^/    /' "$WORK/log" | head -10
    exit 1
}

echo "IR writer rejection smoke OK: unsupported integer AST refused without a crash"
