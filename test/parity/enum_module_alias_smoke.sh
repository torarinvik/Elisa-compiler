#!/usr/bin/env bash
# Module alias constructors and patterns must use the declaring enum's identity.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-enum-alias.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
compilers=("$STAGE1")
[[ ! -x "$STAGE0" ]] || compilers+=("$STAGE0")
for compiler in "${compilers[@]}"; do
    for level in 0 2; do
        for repro in enum_module_alias_payload enum_module_alias_reference enum_module_alias_nested enum_module_nested_direct enum_module_nested_deep; do
            "$compiler" -emit obj "-O$level" -o "$WORK/valid.o" "$ROOT/test/repro/$repro.elisa"
            "${ELISA_CLANG:-clang}" -fno-builtin -o "$WORK/valid" "$WORK/valid.o" "$RUNTIME" "$ROOT/scripts/pymodule_runtime_fallback.c" "$ROOT/test/parity/profile_hooks.c"
            set +e
            "$WORK/valid"
            status=$?
            set -e
            [[ "$status" == 42 ]] || { echo "$repro returned $status at O$level ($compiler)" >&2; exit 1; }
            "$compiler" -emit llvm "-O$level" -o "$WORK/valid.ll" "$ROOT/test/repro/$repro.elisa"
            "${ELISA_OPT:-/opt/homebrew/opt/llvm/bin/opt}" -passes=verify -disable-output "$WORK/valid.ll"
        done
        for negative in enum_module_alias_wrong_owner enum_module_nested_wrong_owner; do
            for mode in llvm obj; do
                output="$WORK/wrong-owner.$mode"
                if "$compiler" -emit "$mode" "-O$level" -o "$output" "$ROOT/test/repro/$negative.elisa" > "$WORK/wrong-owner.log" 2>&1; then
                    echo 'accepted enum from the wrong declaring module' >&2
                    exit 1
                fi
                [[ ! -e "$output" ]] || { echo 'wrong-owner rejection left an artifact' >&2; exit 1; }
                rg -q 'return type expects|backend declined' "$WORK/wrong-owner.log" || { cat "$WORK/wrong-owner.log" >&2; exit 1; }
            done
        done
    done
done
echo 'enum module alias smoke OK: declaration-specific payload tags, direct/alias construction, null variants, patterns and live reference extraction at O0/O2'
