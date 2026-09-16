#!/usr/bin/env bash
# Refuse a stage0 ORACLE binary older than the Go sources it claims to have been built from.
#
# stage0 is what every parity check compares against. Edit it, forget `go build`, and the
# checks keep answering from the previous oracle -- a green suite that proves nothing about
# the change, and worse than the stage1 version of this mistake because the oracle defines
# what "correct" means here.
#
#   bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0" || exit $?
#
# ELISA_ALLOW_STALE_STAGE0=1 opts out, for bisecting the oracle. A missing binary is the
# caller's own guard to report. So is a binary outside a `compiler/bin/` of its own tree:
# that one was named deliberately and is not ours to judge.
set -uo pipefail

BIN="${1:-${ELISACORE_BIN:-}}"
[ "${ELISA_ALLOW_STALE_STAGE0:-0}" = 1 ] && exit 0
[ -n "$BIN" ] || exit 0

# ELISACORE_BIN may be the oracle MEMO (tools/s0cache), which keys on the real binary's
# content hash and so is never itself stale -- check what it wraps.
case "$(basename "$BIN")" in
    s0cache) BIN="${ELISA_S0_REAL:-}"; [ -n "$BIN" ] || exit 0 ;;
esac
[ -x "$BIN" ] || exit 0

SRC="$(cd -- "$(dirname -- "$BIN")/../src" 2>/dev/null && pwd || true)"
[ -n "$SRC" ] && [ -d "$SRC" ] || exit 0

newer="$(find "$SRC" -name '*.go' -newer "$BIN" -print -quit 2>/dev/null)"
[ -n "$newer" ] || exit 0

echo "stage0 oracle binary is stale: $newer is newer than $BIN" >&2
echo "run: (cd $(dirname "$SRC") && go build -o bin/elisac ./src)" >&2
echo "set ELISA_ALLOW_STALE_STAGE0=1 only when intentionally testing an older oracle" >&2
exit 2
