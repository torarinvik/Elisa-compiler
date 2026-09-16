#!/usr/bin/env bash
# Refuse a stage1 product older than the sources it claims to have been built from.
#
# scripts/elisac_stage1.sh already does this for every check that drives the compiler
# through the WRAPPER. Most parity checks invoke `bin/elisac-stage1` directly, so they used
# to measure whatever binary happened to be on disk: edit the compiler, forget to reseed,
# and the gate passes -- against the OLD product, proving nothing about the change under
# test. This is the same guard, callable from those checks.
#
#   bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
#
# ELISA_ALLOW_STALE_STAGE1=1 opts out, for deliberately profiling or bisecting an older
# build. A missing binary is NOT this script's business: the caller's own availability guard
# reports that, with its own name in the message.
set -uo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${1:-${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}}"

[ "${ELISA_ALLOW_STALE_STAGE1:-0}" = 1 ] && exit 0
[ -x "$BIN" ] || exit 0

# A binary under bin/ is the PRODUCT of this tree. One elsewhere was named deliberately
# (a snapshot, a bisect build, another worktree) and is not this tree's to judge.
case "$BIN" in
    "$ROOT/bin/"*) ;;
    *) exit 0 ;;
esac

newer="$(find "$ROOT/src" "$ROOT/elisacore_std" -type f \( -name '*.elisa' -o -name '*.elisai' \) -newer "$BIN" -print -quit 2>/dev/null)"
[ -n "$newer" ] || exit 0

echo "stage1 product binary is stale: $newer is newer than $BIN" >&2
echo "run: $ROOT/scripts/elisac_stage1.sh --seed" >&2
echo "set ELISA_ALLOW_STALE_STAGE1=1 only when intentionally testing an older product" >&2
exit 2
