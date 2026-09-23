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

run_reject_case() {
    local stage="$1"
    local object="$WORK/$stage.o" log="$WORK/$stage.log" status
    if [[ "$stage" == "stage0" ]]; then
        set +e
        "$ELISACORE_BIN" -emit obj -o "$object" "$FIXTURE" >"$log" 2>&1
        status=$?
        set -e
    else
        set +e
        ELISA_STAGE1_BIN="$STAGE1" ELISACORE_BIN="$ELISACORE_BIN" \
            "$ROOT/scripts/elisac_stage1.sh" -o "$object" "$FIXTURE" >"$log" 2>&1
        status=$?
        set -e
    fi
    if [[ "$status" -eq 0 || -e "$object" ]]; then
        echo "global ref initializer smoke FAILED: $stage accepted or emitted an object" >&2
        sed -n '1,40p' "$log" >&2
        return 1
    fi
    if [[ "$stage" == "stage1" ]] && ! rg -Fq "global initializer g" "$log"; then
        echo "global ref initializer smoke FAILED: stage1 did not report the rejected global" >&2
        sed -n '1,40p' "$log" >&2
        return 1
    fi
    echo "  $stage rejects non-constant global reference initializer"
}

run_reject_case stage0
run_reject_case stage1

run_accept_case() {
    local stage="$1"
    local object="$WORK/valid-$stage.o" log="$WORK/valid-$stage.log" status
    if [[ "$stage" == "stage0" ]]; then
        set +e
        "$ELISACORE_BIN" -emit obj -o "$object" "$POSITIVE_FIXTURE" >"$log" 2>&1
        status=$?
        set -e
    else
        set +e
        ELISA_STAGE1_BIN="$STAGE1" ELISACORE_BIN="$ELISACORE_BIN" \
            "$ROOT/scripts/elisac_stage1.sh" -o "$object" "$POSITIVE_FIXTURE" >"$log" 2>&1
        status=$?
        set -e
    fi
    if [[ "$status" -ne 0 || ! -e "$object" ]]; then
        echo "global ref initializer smoke FAILED: $stage rejected a valid constant global" >&2
        sed -n '1,40p' "$log" >&2
        return 1
    fi
    echo "  $stage accepts a valid constant global initializer"
}

run_accept_case stage0
run_accept_case stage1
echo "global ref initializer smoke OK: unsupported references reject; supported constants emit"
