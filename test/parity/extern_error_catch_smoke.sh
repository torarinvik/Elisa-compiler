#!/usr/bin/env bash
# Extern-declared, fieldless error families must retain their error-set metadata
# and lower catch-arm tags identically in Stage0 and Stage1.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac-stage0}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
SOURCE="$ROOT/test/repro/extern_error_catch.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-extern-catch.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

cd "$ROOT"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
"$STAGE0" -emit obj -O0 -o "$WORK/stage0.o" "$SOURCE" >"$WORK/stage0.log" 2>&1 || {
    cat "$WORK/stage0.log" >&2
    exit 1
}
ELISA_STAGE1_BIN="$STAGE1" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit obj -O0 -o "$WORK/stage1.o" "$SOURCE" >"$WORK/stage1.log" 2>&1 || {
        cat "$WORK/stage1.log" >&2
        exit 1
    }

cat >"$WORK/driver.c" <<'EOF'
#include <stdint.h>

#if defined(STAGE0)
extern int64_t load(uint8_t flag) __asm__("___ovl__load__bool__load");
#else
extern int64_t load(uint8_t flag);
#endif
int32_t read_value(int64_t *out, uint8_t flag) {
    if (flag) { *out = 40; return 0; }
    return 1;
}
int main(void) { return load(1) == 40 && load(0) == 1 ? 0 : 1; }
EOF

source "$ROOT/test/parity/native_optional_hook_objects.sh"
elisa_native_optional_hook_objects "$WORK" "$ROOT"
cc -std=c17 -DSTAGE0 "$WORK/driver.c" "$WORK/stage0.o" "${ELISA_OPTIONAL_HOOK_OBJECTS[@]}" -o "$WORK/stage0"
cc -std=c17 "$WORK/driver.c" "$WORK/stage1.o" "${ELISA_OPTIONAL_HOOK_OBJECTS[@]}" -o "$WORK/stage1"
"$WORK/stage0"
"$WORK/stage1"
echo "extern fieldless error catch parity OK"
