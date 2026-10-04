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

# Timestamps alone miss a stale product after switching branches or restoring a checkout:
# the current files can all be older than a binary built from a different revision. Go embeds
# its VCS revision in ordinary `go build` products; require that identity to match this source
# checkout and refuse products built from a dirty tree, whose exact input cannot be recovered
# from the binary. This check is only for a product that sits beside its own source tree.
REPO="$(git -C "$SRC" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$REPO" ]; then
    if ! command -v go >/dev/null 2>&1; then
        echo "cannot verify stage0 build revision: Go is unavailable (binary: $BIN)" >&2
        exit 2
    fi
    BUILD_INFO="$(go version -m "$BIN" 2>/dev/null || true)"
    BUILT_REVISION="$(printf '%s\n' "$BUILD_INFO" | awk '$1 == "build" && $2 ~ /^vcs[.]revision=/ { sub(/^vcs[.]revision=/, "", $2); print $2; exit }')"
    BUILT_MODIFIED="$(printf '%s\n' "$BUILD_INFO" | awk '$1 == "build" && $2 ~ /^vcs[.]modified=/ { sub(/^vcs[.]modified=/, "", $2); print $2; exit }')"
    CURRENT_REVISION="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)"
    if [ -z "$BUILT_REVISION" ] || [ -z "$CURRENT_REVISION" ]; then
        echo "cannot verify stage0 build revision for $BIN; rebuild with Go VCS build information" >&2
        exit 2
    fi
    if [ "$BUILT_REVISION" != "$CURRENT_REVISION" ] || [ "$BUILT_MODIFIED" != false ]; then
        echo "stage0 oracle binary has different source provenance: built revision ${BUILT_REVISION:-unknown} (modified=${BUILT_MODIFIED:-unknown}), current revision $CURRENT_REVISION" >&2
        echo "run: (cd $(dirname "$SRC") && go build -o bin/elisac ./src)" >&2
        echo "set ELISA_ALLOW_STALE_STAGE0=1 only when intentionally testing an older oracle" >&2
        exit 2
    fi
    DIRTY_SOURCE="$(git -C "$REPO" status --porcelain --untracked-files=all -- compiler/src compiler/go.mod compiler/go.sum 2>/dev/null || true)"
    if [ -n "$DIRTY_SOURCE" ]; then
        echo "stage0 source tree has uncommitted changes; rebuild after committing or explicitly allow the stale oracle" >&2
        exit 2
    fi
fi

newer="$(find "$SRC" -name '*.go' -newer "$BIN" -print -quit 2>/dev/null)"
[ -n "$newer" ] || exit 0

echo "stage0 oracle binary is stale: $newer is newer than $BIN" >&2
echo "run: (cd $(dirname "$SRC") && go build -o bin/elisac ./src)" >&2
echo "set ELISA_ALLOW_STALE_STAGE0=1 only when intentionally testing an older oracle" >&2
exit 2
