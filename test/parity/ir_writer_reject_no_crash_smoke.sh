#!/usr/bin/env bash
# The unsigned maximum becomes a negative decoded integer in the compact AST.
# The writer must refuse by name without indexing into an empty encoding.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-ir-reject.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE1" ]] || { echo "IR writer rejection smoke FAIL: stage1 unavailable" >&2; exit 1; }

cat >"$WORK/unsigned_max.elisa" <<'ELISA'
def unsigned_max() -> u64:
    return 18446744073709551615u64
ELISA

# A refused report clears an earlier output rather than leaving stale data behind.
printf 'stale bundle' >"$WORK/unsigned_max.elisair"
set +e
"$STAGE1" -emit ir -O0 -o "$WORK/unsigned_max.elisair" "$WORK/unsigned_max.elisa" >"$WORK/log" 2>&1
status=$?
set -e

[[ "$status" -ne 0 ]] || { echo "IR writer rejection smoke FAIL: unsupported input was accepted"; exit 1; }
[[ "$status" -lt 128 ]] || { echo "IR writer rejection smoke FAIL: compiler terminated by signal (status $status)"; exit 1; }
[[ ! -s "$WORK/unsigned_max.elisair" ]] || { echo "IR writer rejection smoke FAIL: output contains stale or partial data"; exit 1; }
rg -qF -- "-emit ir cannot represent this construct yet: integer literal outside the IR writer's decimal domain" "$WORK/log" || {
    echo "IR writer rejection smoke FAIL: expected refusal was not diagnosed"
    sed 's/^/    /' "$WORK/log" | head -10
    exit 1
}

echo "IR writer rejection smoke OK: unsupported integer AST refused without a crash"
