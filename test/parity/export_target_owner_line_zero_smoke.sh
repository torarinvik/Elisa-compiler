#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
FIXTURE="$ROOT/test/repro/export_target_owner_line_zero.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-export-target-owner.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0" || exit $?
bash "$ROOT/scripts/assert_stage1_fresh.sh"
python3 "$ROOT/test/proofs/check_export_target_owner_identity.py"

cat > "$WORK/main.c" <<'EOF'
#include <stdint.h>

extern int64_t public_first(void);
extern int64_t public_second(void);

int main(void) {
    return public_first() != 11 || public_second() != 22;
}
EOF

"$STAGE0" -emit obj -O0 -o "$WORK/stage0.o" "$FIXTURE"
cc "$WORK/main.c" "$WORK/stage0.o" -o "$WORK/stage0"
"$WORK/stage0"
for optimization in 0 2; do
	output="$WORK/stage1-O$optimization"
	"$STAGE1" -emit obj "-O$optimization" -o "$output.o" "$FIXTURE"
	cc "$WORK/main.c" "$output.o" -o "$output"
	"$output"
done

echo "export target owner-offset parity OK: line-zero aliases call their declared targets"
