#!/usr/bin/env bash
# Common driver and executable checks for real standard-library cases.
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/platform.sh"
source "$ROOT/test/parity/run_timeout.sh"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
[[ -x "$STAGE0" && -x "$STAGE1" ]] || { echo "real std runtime smoke requires both compilers" >&2; exit 1; }
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
mkdir -p "$ROOT/build"
WORK="$(mktemp -d "$ROOT/build/real-std-runtime.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
clang -c "$ROOT/test/parity/profile_hooks.c" -o "$WORK/profile_hooks.o"

real_std_pass=0
real_std_total=0

real_std_runtime_case() {
    local include="$1" name="$2" body="$3" expected="$4"
    shift 4
    real_std_total=$((real_std_total + 1))
    local source_file="$WORK/$name.elisa" output="$WORK/$name"
    printf 'include "%s"\n\n%s\n' "$ROOT/elisacore_std/$include" "$body" >"$source_file"
    local compiler stage=0 rc passed=1
    for compiler in "$STAGE0" "$STAGE1"; do
        if ! "$compiler" -emit obj -o "$output.o" "$source_file" >"$output.log" 2>&1; then
            printf '  FAIL %s: Stage%s compile failed\n' "$name" "$stage" >&2
            tail -20 "$output.log" >&2
            passed=0
        elif ! clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$output" "$output.o" "$@" >"$output.log" 2>&1; then
            printf '  FAIL %s: Stage%s link failed\n' "$name" "$stage" >&2
            cat "$output.log" >&2
            passed=0
        else
            rc=0
            elisa_run_timeout 15 "$output" || rc=$?
            if [[ "$rc" -ne "$expected" ]]; then
                printf '  FAIL %s: Stage%s exit %s, want %s\n' "$name" "$stage" "$rc" "$expected" >&2
                passed=0
            fi
        fi
        stage=$((stage + 1))
    done
    real_std_pass=$((real_std_pass + passed))
}

real_std_runtime_summary() {
    if [[ "$real_std_pass" -eq "$real_std_total" ]]; then
        echo "$1 OK: $real_std_pass/$real_std_total cases compiled and ran on both stages"
    else
        echo "$1 FAILED: $real_std_pass/$real_std_total" >&2
        return 1
    fi
}
