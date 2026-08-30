#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
STAGE0="${ELISA_STAGE0_BIN:-$HOME/.elisac/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"

if [[ ! -x "$STAGE0" || ! -x "$STAGE1" || ! -x "$CLANG" || ! -f "$RUNTIME_OBJ" ]]; then
    echo "fn-typed extern struct-ref smoke SKIP (stage0/stage1/clang/runtime unavailable)"
    exit 0
fi

SOURCE="$ROOT/test/repro/extern_fn_struct_ref.elisa"
"$STAGE0" -emit obj -o "$WORK/stage0.o" "$SOURCE"
"$STAGE1" -emit obj -o "$WORK/stage1.o" "$SOURCE"

# The callbacks are not invoked here; these stubs prove that both generated objects expose
# the same pointer-shaped C ABI and that the calls were emitted rather than declined.
printf '%s\n' \
    'int register_callback(void *handler, int count) { return handler != 0 && count == 1 ? 0 : 1; }' \
    'int register_callback_pair(void *handler) { return handler != 0 ? 0 : 1; }' \
    | "$CLANG" -x c -c -o "$WORK/stub.o" -
"$CLANG" -o "$WORK/stage0" "$WORK/stage0.o" "$WORK/stub.o" "$RUNTIME_OBJ"
"$CLANG" -o "$WORK/stage1" "$WORK/stage1.o" "$WORK/stub.o" "$RUNTIME_OBJ"

set +e
"$WORK/stage0"
stage0_result=$?
"$WORK/stage1"
stage1_result=$?
set -e
[[ "$stage0_result" -eq 42 && "$stage1_result" -eq 42 ]]

echo "fn-typed extern struct-ref smoke OK (stage0/stage1)"
