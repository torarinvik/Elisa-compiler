#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$ROOT/test/parity/run_timeout.sh"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-str-print.XXXXXX")"
source "$ROOT/test/parity/control_artifacts.sh"
elisa_control_artifacts "$WORK"
status=0
elisa_run_timeout 30 "$STAGE1" -emit check "$ROOT/test/parity/str_print_missing_protocol_control.elisa" >"$WORK/missing-Str.log" 2>&1 || status=$?
if [[ "$status" -ne 1 ]] || ! grep -q 'does not satisfy required interface fact' "$WORK/missing-Str.log"; then
    cat "$WORK/missing-Str.log" >&2
    echo "Str print control failed: a missing Str implementation must produce a semantic rejection" >&2
    exit 1
fi
cat >"$WORK/expected" <<'EXPECTED'
A
-12345
-432360
751804663071387784
-1234567
-1234
-12
18446744073709551615
4000000000
60000
240
123456
234567
1.25
2.5
true
false
text
first custom
second custom
EXPECTED
for level in O0 O2 O3; do
    if ! elisa_run_timeout 300 "$STAGE1" -emit exe "-$level" -o "$WORK/control-$level" "$ROOT/test/parity/str_print_type_identity_control.elisa" >"$WORK/build-$level.log" 2>&1; then
        cat "$WORK/build-$level.log" >&2
        exit 1
    fi
    elisa_run_timeout 30 "$WORK/control-$level" >"$WORK/actual-$level" 2>"$WORK/run-$level.log"
    if ! cmp -s "$WORK/expected" "$WORK/actual-$level"; then
        echo "Str print type identity failed at $level: complete stdout differs" >&2
        diff -u "$WORK/expected" "$WORK/actual-$level" >&2 || true
        exit 1
    fi
done
echo "Str print type identity OK at O0/O2/O3: scalar types and custom implementations"
