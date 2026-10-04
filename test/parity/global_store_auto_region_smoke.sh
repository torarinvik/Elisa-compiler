#!/usr/bin/env bash
# Values stored into module globals (and everything reachable from them) must not be
# allocated in the storing function's auto region, which is freed at return.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
[[ -x "$STAGE1" ]] || { echo "global-store auto-region smoke: missing stage1 compiler: $STAGE1" >&2; exit 2; }
cd "$ROOT"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-global-store.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
for opt in 0 2; do
    "$STAGE1" -emit exe "-O$opt" -o "$WORK/p$opt" "$ROOT/test/parity/fixtures/global_store_auto_region.elisa" >"$WORK/log" 2>&1 || { cat "$WORK/log" >&2; echo "global-store auto-region smoke FAIL: compile O$opt" >&2; exit 1; }
    rc=0; "$WORK/p$opt" || rc=$?
    [[ "$rc" -eq 42 ]] || { echo "global-store auto-region smoke FAIL: O$opt exit $rc, want 42 (globals read freed memory)" >&2; exit 1; }
done
echo "global-store auto-region smoke OK"
