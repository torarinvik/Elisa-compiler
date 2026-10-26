#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
CLANG="${ELISA_CLANG:-$ELISA_LLVM_BIN_DIR/clang}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$ROOT/test/parity/run_timeout.sh"
python3 "$ROOT/test/proofs/check_extern_fallible_ensure_success_only.py"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-extern-fallible-ensure.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

elisa_run_timeout 29 "$CLANG" -c "$ROOT/test/fixtures/backend/extern_fallible_ensure.c" -o "$WORK/extern.o"
elisa_run_timeout 29 "$CLANG" -c "$ROOT/test/parity/profile_hooks.c" -o "$WORK/hooks.o"

failure_source="$ROOT/test/fixtures/backend/extern_fallible_ensure_unwritten_failure.elisa"
failure_ir="$WORK/unwritten_failure.ll"
elisa_run_timeout 29 "$STAGE1" -emit llvm -O0 -o "$failure_ir" "$failure_source" >"$WORK/unwritten_failure-llvm.log" 2>&1 || {
    echo "fallible extern failure LLVM compile failed" >&2
    sed -n '1,100p' "$WORK/unwritten_failure-llvm.log" >&2
    exit 1
}
python3 "$ROOT/test/proofs/check_extern_fallible_ensure_success_only.py" --ir "$failure_ir"

for optimization in 0 2; do
    for case_name in good bad unwritten_failure; do
        source_file="$ROOT/test/fixtures/backend/extern_fallible_ensure_$case_name.elisa"
        object="$WORK/$case_name-O$optimization.o"
        executable="$WORK/$case_name-O$optimization"
        elisa_run_timeout 29 env ELISACORE_FORCE_CONTRACTS=1 "$STAGE1" -emit obj "-O$optimization" -o "$object" "$source_file" >"$WORK/$case_name-build.log" 2>&1 || {
            echo "fallible extern ensure compile failed for $case_name" >&2
            sed -n '1,100p' "$WORK/$case_name-build.log" >&2
            exit 1
        }
        elisa_run_timeout 29 "$CLANG" $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS \
            -o "$executable" "$object" "$WORK/extern.o" "$WORK/hooks.o" "$RUNTIME"
        if [[ "$case_name" == bad ]]; then
            status=0
            if elisa_run_timeout 10 "$executable" >"$WORK/$case_name.log" 2>&1; then
                status=0
            else
                status=$?
            fi
            [[ "$status" -ne 0 ]] && grep -Fq 'extern postcondition failed' "$WORK/$case_name.log" || {
                echo "successful extern with bad result did not fail its ensure" >&2
                cat "$WORK/$case_name.log" >&2
                exit 1
            }
        else
            expected=0
            [[ "$case_name" == unwritten_failure ]] && expected=7
            status=0
            if elisa_run_timeout 10 "$executable"; then
                status=0
            else
                status=$?
            fi
            [[ "$status" == "$expected" ]] || {
                echo "fallible extern $case_name returned $status, expected $expected" >&2
                exit 1
            }
        fi
    done
done

echo "extern fallible ensure smoke OK: checked O0/O2 accept good results, reject bad results, skip unwritten failure output"
