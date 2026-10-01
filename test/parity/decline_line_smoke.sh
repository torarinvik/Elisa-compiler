#!/usr/bin/env bash
# A backend decline names the function and the line it declined at. That line was the
# line of the driver-EXPANDED unit, so with the runtime included `bad` declined "@8796"
# for a construct on line 8 of the user's file. It must be the line in the declaring file,
# the one stage0 reports for the same construct (8 here; stage0 rejects the float `&` as
# a type error, stage1's backend declines it). The no-include twin pins that a unit with
# nothing spliced in is unchanged (line 6).
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="${ELISAC_STAGE1:-$ROOT/bin/elisac-stage1}"
DIR="$ROOT/test/fixtures/backend/decline_line"
TMP="$(mktemp -d "$HOME/.decline_line.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
fail=0
check() {
    local name="$1" want="$2"
    "$BIN" -emit obj "$DIR/$name.elisa" -o "$TMP/$name.o" >"$TMP/$name.log" 2>&1
    local rc=$?
    if [ $rc -eq 0 ] || [ -s "$TMP/$name.o" ]; then
        echo "FAIL $name: expected a decline (rc=$rc)"; fail=1; return; fi
    if ! grep -v 'warning:' "$TMP/$name.log" | grep -qF "declined 1: $want (binary expression)"; then
        echo "FAIL $name: want 'declined 1: $want', got:"; grep -v 'warning:' "$TMP/$name.log" | head -2; fail=1; fi
}
check included_runtime "bad@8"
check no_include "bad@6"
[ $fail -eq 0 ] && echo "decline-line OK (2 cases report the declaring file's line)" || exit 1
