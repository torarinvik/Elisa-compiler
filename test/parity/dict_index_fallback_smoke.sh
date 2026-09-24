#!/usr/bin/env bash
# Dictionary `get index else fallback`: Stage0/Stage1 compiled and runtime parity.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
SOURCE="$ROOT/test/repro/dict_index_fallback.elisa"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-dict-index-fallback.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0" || exit $?
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
cd "$ROOT"
"$STAGE0" -emit obj -O0 -o "$WORK/stage0.o" "$SOURCE" >"$WORK/stage0.log" 2>&1 || {
    cat "$WORK/stage0.log" >&2
    exit 1
}
env -u ELISACORE_BIN -u ELISA_CORE -u REPO_ROOT \
    ELISA_STAGE1_BIN="$STAGE1" ELISA_RUNTIME_OBJ="$RUNTIME" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit obj -O0 -o "$WORK/stage1.o" "$SOURCE" >"$WORK/stage1.log" 2>&1 || {
        cat "$WORK/stage1.log" >&2
        exit 1
    }

cat >"$WORK/driver.c" <<'EOF'
#include <stdint.h>

extern int64_t dict_lookup_fallback(void);

int main(void) { return dict_lookup_fallback() == 49 ? 0 : 1; }
EOF

source "$ROOT/test/parity/native_optional_hook_objects.sh"
elisa_native_optional_hook_objects "$WORK" "$ROOT"
cc -std=c17 "$WORK/driver.c" "$WORK/stage0.o" "${ELISA_OPTIONAL_HOOK_OBJECTS[@]}" -o "$WORK/stage0"
cc -std=c17 "$WORK/driver.c" "$WORK/stage1.o" "${ELISA_OPTIONAL_HOOK_OBJECTS[@]}" -o "$WORK/stage1"
"$WORK/stage0"
"$WORK/stage1"
echo "dictionary checked-index fallback parity OK: hit and miss both match Stage0"
