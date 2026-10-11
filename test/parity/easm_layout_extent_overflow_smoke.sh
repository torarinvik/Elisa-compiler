#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"
source "$ROOT/test/parity/control_artifacts.sh"

[[ -x "$STAGE1" ]] || { echo "easm layout extent overflow smoke: missing stage1 compiler: $STAGE1" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-easm-layout-extent.XXXXXX")"
elisa_control_artifacts "$WORK"

cat > "$WORK/malformed-required-size.easm" <<'EASM'
module malformed_required_size
target x86_64
layout Header size 16:
    0 value: u64 requires size >= 8junk
EASM
cat > "$WORK/overflow-required-size.easm" <<'EASM'
module overflow_required_size
target x86_64
layout Header size 16:
    0 value: u64 requires size >= 9223372036854775808
EASM
cat > "$WORK/overflow-field-extent.easm" <<'EASM'
module overflow_field_extent
target x86_64
layout Header size 16:
    9223372036854775804 value: u64
EASM

check_stdin_rejection() {
    local binary="$1" case_name="$2" source_file="$3" expected_code="$4"
    local output="$WORK/${case_name}.run.log"
    local status=0
    set +e
    elisa_run_timeout 20 "$binary" <"$source_file" >"$output" 2>&1
    status=$?
    set -e
    if [[ "$status" -ne 1 ]] || ! rg -Fq 'RESULT reject' "$output" || ! rg -Fq "CODE $expected_code" "$output"; then
        echo "easm layout extent overflow smoke: stdin driver did not reject $case_name with its parse diagnostic (status $status)" >&2
        cat "$output" >&2
        return 1
    fi
}

for optimization in 0 2; do
    for source_name in easm_layout_extent_overflow_smoke easm_checked_decimal_parse_smoke; do
        fixture="$WORK/${source_name}-O${optimization}"
        fixture_log="$fixture.compile.log"
        if ! elisa_run_timeout 300 "$STAGE1" -emit exe "-O${optimization}" -o "$fixture" "$ROOT/test/breadth/${source_name}.elisa" >"$fixture_log" 2>&1; then
            echo "easm layout extent overflow smoke: failed to compile $source_name at O$optimization" >&2
            cat "$fixture_log" >&2
            exit 1
        fi
        if ! elisa_run_timeout 30 "$fixture" >"$WORK/${source_name}-O${optimization}.run.log" 2>&1; then
            echo "easm layout extent overflow smoke: $source_name failed at O$optimization" >&2
            cat "$WORK/${source_name}-O${optimization}.run.log" >&2
            exit 1
        fi
    done

    stdin_driver="$WORK/easm-verify-stdin-O${optimization}"
    stdin_log="$stdin_driver.compile.log"
    if ! elisa_run_timeout 300 "$STAGE1" -emit exe "-O${optimization}" -o "$stdin_driver" "$ROOT/test/breadth/easm_verify_stdin.elisa" >"$stdin_log" 2>&1; then
        echo "easm layout extent overflow smoke: failed to compile stdin verifier at O$optimization" >&2
        cat "$stdin_log" >&2
        exit 1
    fi
    check_stdin_rejection "$stdin_driver" "malformed-required-size-O${optimization}" "$WORK/malformed-required-size.easm" "invalid-layout-required-size"
    check_stdin_rejection "$stdin_driver" "overflow-required-size-O${optimization}" "$WORK/overflow-required-size.easm" "invalid-layout-required-size"
    check_stdin_rejection "$stdin_driver" "overflow-field-extent-O${optimization}" "$WORK/overflow-field-extent.easm" "layout-field-extent-overflow"
done

echo "easm layout extent overflow smoke OK: decimal and layout extents are checked through API and stdin at O0/O2"
