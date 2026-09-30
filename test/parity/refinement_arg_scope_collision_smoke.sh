#!/usr/bin/env bash
# Same-named refined functions in sibling modules must not donate argument rules
# to unqualified calls, while an explicitly qualified refined call remains checked.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
SOURCE="$ROOT/test/repro/refinement_arg_scope_collision.elisa"
REOPENED_SOURCE="$ROOT/test/repro/refinement_arg_reopened_module.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/refinement-arg-scope.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

set +e
"$STAGE0" -emit obj -O0 -o "$WORK/stage0.o" "$SOURCE" >"$WORK/stage0.log" 2>&1
stage0_status=$?
set -e
stage0_warning_count="$(grep -Fc 'on argument 1 of "is_valid"' "$WORK/stage0.log" || true)"
stage0_nested_warning_count="$(grep -Fc 'is_valid_nested"' "$WORK/stage0.log" || true)"
[[ "$stage0_warning_count" == 1 && "$stage0_nested_warning_count" == 1 ]] || {
    printf 'Expected one explicitly qualified Stage0 diagnostic at each module depth; observed is_valid=%s is_valid_nested=%s (status %s)\n' "$stage0_warning_count" "$stage0_nested_warning_count" "$stage0_status" >&2
    cat "$WORK/stage0.log" >&2
    exit 1
}

set +e
ELISACORE_BIN="$STAGE0" ELISA_STAGE1_BIN="$STAGE1" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit obj -O0 -o "$WORK/stage1.o" "$SOURCE" >"$WORK/stage1.log" 2>&1
stage1_status=$?
set -e

stage1_warning_count="$(grep -Fc 'on argument 1 of "is_valid"' "$WORK/stage1.log" || true)"
stage1_nested_warning_count="$(grep -Fc 'is_valid_nested"' "$WORK/stage1.log" || true)"
[[ "$stage1_warning_count" == 1 && "$stage1_nested_warning_count" == 1 ]] || {
    printf 'Expected one explicitly qualified Stage1 diagnostic at each module depth; observed is_valid=%s is_valid_nested=%s (status %s)\n' "$stage1_warning_count" "$stage1_nested_warning_count" "$stage1_status" >&2
    cat "$WORK/stage1.log" >&2
    exit 1
}

set +e
"$STAGE0" -emit obj -O0 -o "$WORK/stage0-reopened.o" "$REOPENED_SOURCE" >"$WORK/stage0-reopened.log" 2>&1
stage0_reopened_status=$?
set -e
stage0_reopened_count="$(grep -Fc 'on argument 1 of "accept"' "$WORK/stage0-reopened.log" || true)"
[[ "$stage0_reopened_count" == 1 ]] || {
    printf 'Expected a Stage0 refinement diagnostic across reopened module declarations (status %s)\n' "$stage0_reopened_status" >&2
    cat "$WORK/stage0-reopened.log" >&2
    exit 1
}

set +e
ELISACORE_BIN="$STAGE0" ELISA_STAGE1_BIN="$STAGE1" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit obj -O0 -o "$WORK/stage1-reopened.o" "$REOPENED_SOURCE" >"$WORK/stage1-reopened.log" 2>&1
stage1_reopened_status=$?
set -e
stage1_reopened_count="$(grep -Fc 'on argument 1 of "accept"' "$WORK/stage1-reopened.log" || true)"
[[ "$stage1_reopened_count" == 1 ]] || {
    printf 'Expected a Stage1 refinement diagnostic across reopened module declarations (status %s)\n' "$stage1_reopened_status" >&2
    cat "$WORK/stage1-reopened.log" >&2
    exit 1
}

echo "refinement argument scope smoke OK: collisions stay quiet and explicit refined targets remain diagnosed across sibling, nested, and reopened modules"
