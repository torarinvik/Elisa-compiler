#!/usr/bin/env bash
# A same-named struct in a sibling module must not capture a visible refined alias;
# a struct in its own module must still reject a primitive return.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
POSITIVE="$ROOT/test/repro/refined_alias_return_after_raise.elisa"
BACKEND="$ROOT/test/repro/module_alias_struct_collision_error_return.elisa"
NEGATIVE="$ROOT/test/repro/refined_alias_return_struct_shadow.neg.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-refined-alias-scope.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[[ -x "$STAGE0" ]] || { echo "refined alias scope smoke: missing stage0: $STAGE0" >&2; exit 2; }
[[ -x "$STAGE1" ]] || { echo "refined alias scope smoke: missing stage1: $STAGE1" >&2; exit 2; }

"$STAGE0" -emit llvm -O0 -o "$WORK/stage0-positive.ll" "$POSITIVE"
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1-positive.ll" "$POSITIVE"
! rg -q '!elisa\.declined' "$WORK/stage1-positive.ll"

"$STAGE0" -emit llvm -O0 -o "$WORK/stage0-backend.ll" "$BACKEND"
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1-backend.ll" "$BACKEND"
! rg -q '!elisa\.declined' "$WORK/stage1-backend.ll"

for compiler in "$STAGE0" "$STAGE1"; do
    log="$WORK/negative-$(basename "$compiler").log"
    if "$compiler" -emit llvm -O0 -o "$WORK/negative.ll" "$NEGATIVE" >"$log" 2>&1; then
        echo "refined alias scope smoke: $(basename "$compiler") accepted a primitive for the local struct" >&2
        exit 1
    fi
    rg -Fq 'return type expects ' "$log" && rg -Fq 'got int' "$log" || {
        echo "refined alias scope smoke: $(basename "$compiler") rejected for the wrong reason" >&2
        sed -n '1,80p' "$log" >&2
        exit 1
    }
done

echo "refined alias scope smoke OK: sibling names stay isolated and local struct walls remain active"
