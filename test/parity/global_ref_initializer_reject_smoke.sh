#!/usr/bin/env bash
# Stage0/Stage1 backend parity: a runtime address-of expression is not a
# constant initializer for a mutable global reference. Neither compiler may
# emit an object with LLVM's default null initializer substituted for it.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}"
source "$ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/fixtures/diagnostics/ref_global_capability.neg.elisa"

bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[ -f "$FIXTURE" ] || { echo "global ref initializer smoke: fixture missing" >&2; exit 2; }

WORK_ROOT="$ROOT/build/global-ref-initializer-smoke"
mkdir -p "$WORK_ROOT"
WORK="$(mktemp -d "$WORK_ROOT/global-ref-init.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

POSITIVE_FIXTURE="$WORK/valid_global_initializer.elisa"
cat > "$POSITIVE_FIXTURE" <<'EOF'
global mutable answer: i64 = 42

def main() -> i64:
    return answer
EOF

OPTIONAL_AGGREGATE_FIXTURE="$WORK/valid_optional_aggregate_global.elisa"
cat > "$OPTIONAL_AGGREGATE_FIXTURE" <<'EOF'
struct MaybeRefBox:
    slot: mutable i64&?
    value: i64

global mutable state: MaybeRefBox = MaybeRefBox{slot: null, value: 42}

def main() -> i64:
    return state.value
EOF

run_reject_case() {
    local stage="$1" fixture="$2" global_name="$3" reason="$4"
    local object="$WORK/$stage-$global_name.o" log="$WORK/$stage-$global_name.log" status
    if [[ "$stage" == "stage0" ]]; then
        set +e
        "$ELISACORE_BIN" -emit obj -o "$object" "$fixture" >"$log" 2>&1
        status=$?
        set -e
    else
        set +e
        ELISA_STAGE1_BIN="$STAGE1" ELISACORE_BIN="$ELISACORE_BIN" \
            "$ROOT/scripts/elisac_stage1.sh" -o "$object" "$fixture" >"$log" 2>&1
        status=$?
        set -e
    fi
    if [[ "$status" -eq 0 || -e "$object" ]]; then
        echo "global ref initializer smoke FAILED: $stage accepted or emitted an object" >&2
        sed -n '1,40p' "$log" >&2
        return 1
    fi
    if [[ "$stage" == "stage1" ]] && ! rg -Fq "global initializer $global_name" "$log"; then
        echo "global initializer smoke FAILED: stage1 did not report the rejected global '$global_name'" >&2
        sed -n '1,40p' "$log" >&2
        return 1
    fi
    echo "  $stage rejects $reason"
}

run_reject_case stage0 "$FIXTURE" g "non-constant global reference initializer"
run_reject_case stage1 "$FIXTURE" g "non-constant global reference initializer"

TYPE_MISMATCH_FIXTURE="$WORK/optional_payload_type_mismatch.elisa"
cat > "$TYPE_MISMATCH_FIXTURE" <<'EOF'
global mutable maybe: i64? = 42

def main() -> i64:
    return 42
EOF

run_reject_case stage0 "$TYPE_MISMATCH_FIXTURE" maybe "unsupported optional global payload initializer"
run_reject_case stage1 "$TYPE_MISMATCH_FIXTURE" maybe "unsupported optional global payload initializer"

run_accept_case() {
    local stage="$1" fixture="$2" case_name="$3" description="$4"
    local object="$WORK/valid-$stage-$case_name.o" executable="$WORK/valid-$stage-$case_name" log="$WORK/valid-$stage-$case_name.log" status run_status
    if [[ "$stage" == "stage0" ]]; then
        set +e
        "$ELISACORE_BIN" -emit obj -o "$object" "$fixture" >"$log" 2>&1
        status=$?
        set -e
    else
        set +e
        ELISA_STAGE1_BIN="$STAGE1" ELISACORE_BIN="$ELISACORE_BIN" \
            "$ROOT/scripts/elisac_stage1.sh" -o "$object" "$fixture" >"$log" 2>&1
        status=$?
        set -e
    fi
    if [[ "$status" -ne 0 || ! -e "$object" ]]; then
        echo "global ref initializer smoke FAILED: $stage rejected a valid constant global" >&2
        sed -n '1,40p' "$log" >&2
        return 1
    fi
    if ! clang -o "$executable" "$object" >>"$log" 2>&1; then
        echo "global initializer smoke FAILED: could not link $stage $description" >&2
        sed -n '1,40p' "$log" >&2
        return 1
    fi
    set +e
    "$executable"
    run_status=$?
    set -e
    if [[ "$run_status" -ne 42 ]]; then
        echo "global initializer smoke FAILED: $stage $description returned $run_status, expected 42" >&2
        sed -n '1,40p' "$log" >&2
        return 1
    fi
    echo "  $stage emits and runs $description (42)"
}

run_accept_case stage0 "$POSITIVE_FIXTURE" scalar "a scalar constant global initializer"
run_accept_case stage1 "$POSITIVE_FIXTURE" scalar "a scalar constant global initializer"
run_accept_case stage0 "$OPTIONAL_AGGREGATE_FIXTURE" optional-aggregate "an aggregate global with an absent optional reference"
run_accept_case stage1 "$OPTIONAL_AGGREGATE_FIXTURE" optional-aggregate "an aggregate global with an absent optional reference"
echo "global initializer smoke OK: unsupported forms reject; supported scalar and aggregate values return 42"
