#!/usr/bin/env bash
# The WASM export scanner must exclude effects while retaining nested type tokens.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
bash "$ROOT/scripts/elisac_stage1.sh" -emit exe -O0 -o "$WORK/span" "$ROOT/test/repro/wasm_export_return_span.elisa" >"$WORK/build.log" 2>&1 || { cat "$WORK/build.log" >&2; exit 1; }
check() {
    local signature="$1" expected="$2" actual
    set +e
    printf '%s\n' "$signature" | "$WORK/span"
    actual=$?
    set -e
    if [[ "$actual" != "$expected" ]]; then
        printf 'WASM return span: expected %s tokens, got %s for %s\n' "$expected" "$actual" "$signature" >&2
        exit 1
    fi
}
check 'export fn f() -> i32 can[Global{Read,Write}] = f' 1
check 'export fn f() -> i32 = f' 1
check 'export fn f() -> array[i32,2] can[Global.Read] = f' 6
check 'export fn f() -> can[i32] = f' 4
echo 'WASM export return span smoke OK'
