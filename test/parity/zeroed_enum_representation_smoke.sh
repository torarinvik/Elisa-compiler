#!/usr/bin/env bash
# Only the payload selected by the zero discriminant must be zero-valid.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-enum-zero.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
compilers=("$STAGE1")
[[ ! -x "$STAGE0" ]] || compilers+=("$STAGE0")
for compiler in "${compilers[@]}"; do
    for level in 0 2; do
        for repro in zeroed_enum_active_view zeroed_enum_active_reference zeroed_enum_module_payload zeroed_enum_nested_payload zeroed_enum_active_return zeroed_enum_active_global; do
            for mode in llvm obj; do
                output="$WORK/$repro.$mode"
                if "$compiler" -emit "$mode" "-O$level" -o "$output" "$ROOT/test/repro/$repro.elisa" > "$WORK/reject.log" 2>&1; then
                    echo "$repro accepted by $compiler at O$level ($mode)" >&2
                    exit 1
                fi
                [[ ! -e "$output" ]] || { echo 'invalid enum rejection left an artifact' >&2; exit 1; }
                rg -q 'zeroed' "$WORK/reject.log" || { cat "$WORK/reject.log" >&2; exit 1; }
            done
        done
        "$compiler" -emit obj "-O$level" -o "$WORK/valid.o" "$ROOT/test/repro/zeroed_enum_valid_controls.elisa"
        "${ELISA_CLANG:-clang}" -o "$WORK/valid" "$WORK/valid.o"
        set +e
        "$WORK/valid"
        status=$?
        set -e
        [[ "$status" == 42 ]] || { echo "enum valid controls returned $status" >&2; exit 1; }
    done
done
echo 'zeroed enum representation smoke OK: active invalid payloads reject; inactive/scalar/constructed controls return 42 at O0/O2'
