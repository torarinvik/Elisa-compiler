#!/usr/bin/env bash
# A field-function alias is lexical metadata. A shadowing block must remove its alias without
# removing an outer alias, and a stale inner alias must never make an otherwise invalid labelled
# call compile against the wrong function signature.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
VALID="$ROOT/test/fixtures/fn_field_alias_scope_preserve.elisa"
REJECT="$ROOT/test/fixtures/fn_field_alias_scope_leak.elisa"

[[ -x "$STAGE1" ]] || { echo "fn-field alias scope smoke SKIP: no stage1 at $STAGE1" >&2; exit 0; }

compile_and_run() {
    local compiler="$1" tag="$2" source="$3" expected="$4"
    local object="$WORK/$tag.o" binary="$WORK/$tag"
    "$compiler" -emit obj -O0 -o "$object" "$source" >"$WORK/$tag.log" 2>&1
    clang -Wl,-dead_strip -o "$binary" "$object" "${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
    set +e
    "$binary"
    local actual=$?
    set -e
    [[ "$actual" -eq "$expected" ]] || {
        echo "fn-field alias scope smoke FAIL: $tag returned $actual, expected $expected" >&2
        exit 1
    }
}

compile_and_run "$STAGE1" stage1-valid "$VALID" 23
if [[ -x "$STAGE0" ]]; then
    compile_and_run "$STAGE0" stage0-valid "$VALID" 23
fi

for compiler_tag in stage1 stage0; do
    compiler="$STAGE1"
    [[ "$compiler_tag" == stage0 && -x "$STAGE0" ]] && compiler="$STAGE0"
    [[ "$compiler_tag" == stage0 && ! -x "$STAGE0" ]] && continue
    if "$compiler" -emit obj -O0 -o "$WORK/$compiler_tag-reject.o" "$REJECT" >"$WORK/$compiler_tag-reject.log" 2>&1; then
        echo "fn-field alias scope smoke FAIL: $compiler_tag accepted stale alias" >&2
        exit 1
    fi
done

echo "fn-field alias scope smoke OK: lexical aliases are restored and preserved correctly"
