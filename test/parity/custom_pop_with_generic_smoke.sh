#!/usr/bin/env bash
# An imported generic name must not hide an ordinary custom pop method.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
LIMIT_KB="${BUILTIN_WORKLIST_REHOME_RSS_LIMIT_KB:-32768}"
[[ -x "$STAGE1" ]] || { echo "custom pop with generic smoke: missing stage1 compiler: $STAGE1" >&2; exit 2; }
cd "$ROOT"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-global-rehome.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
for opt in 0 2; do
    "$STAGE1" -emit exe "-O$opt" -o "$WORK/p$opt" "$ROOT/test/parity/fixtures/custom_pop_with_generic.elisa" >"$WORK/log" 2>&1 || { cat "$WORK/log" >&2; echo "custom pop with generic smoke FAIL: compile O$opt" >&2; exit 1; }
    TFLAG=-l; [[ "$(uname)" == Darwin ]] || TFLAG=-v
    rc=0; /usr/bin/time "$TFLAG" "$WORK/p$opt" 2>"$WORK/time" || rc=$?
    [[ "$rc" -eq 42 ]] || { echo "custom pop with generic smoke FAIL: O$opt exit $rc, want 42" >&2; exit 1; }
    if [[ "$(uname)" == Darwin ]]; then
        rss_kb=$(( $(awk '/maximum resident/{print $1}' "$WORK/time") / 1024 ))
    else
        rss_kb=$(awk -F: '/Maximum resident/{gsub(/ /,"",$2); print $2}' "$WORK/time")
    fi
    [[ "$rss_kb" -le "$LIMIT_KB" ]] || { echo "custom pop with generic smoke FAIL: O$opt peak RSS ${rss_kb} KB > ${LIMIT_KB} KB" >&2; exit 1; }
done
echo "custom pop with generic smoke OK"
