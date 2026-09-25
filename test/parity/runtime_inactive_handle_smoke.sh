#!/usr/bin/env bash
# Disabled trace and packed-store hooks must still occupy Runtime slots with valid
# LLVMValueRef handles. Exercise each feature combination through native emission.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[ -x "$STAGE1" ] || { echo "runtime_inactive_handle_smoke FAIL: no stage1 compiler at $STAGE1" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cat > "$WORK/trace.elisa" <<'EOF'
def helper(x: i64) -> i64:
    return x + 1

def main() -> i64:
    return helper(41)
EOF

run_probe() {
    local label="$1"
    shift
    local output="$WORK/$label"
    "$STAGE1" -emit exe "$@" -o "$output"
    set +e
    "$output" >"$WORK/$label.stdout" 2>"$WORK/$label.stderr"
    local status=$?
    set -e
    if [ "$status" -ne 42 ]; then
        echo "runtime_inactive_handle_smoke FAIL: $label returned $status, want 42" >&2
        cat "$WORK/$label.stderr" >&2
        exit 1
    fi
}

for level in O0 O2; do
    run_probe "trace-$level" "-$level" -ftrace "$WORK/trace.elisa"
    run_probe "packed-index-$level" "-$level" "$ROOT/test/breadth/packed_profile_fixture.elisa"
    run_probe "packed-aos-$level" "-$level" "$ROOT/test/breadth/packed_aos_fixture.elisa"
done

echo "runtime_inactive_handle_smoke OK: trace, packed index, and packed AoS at O0/O2"
