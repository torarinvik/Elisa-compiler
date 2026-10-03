#!/usr/bin/env bash
# `@append_only` stores are enforced, not trusted: every bypass route is rejected for its own
# reason in both compilers, and the canonical store compiles and runs.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}/compiler/bin/elisac-stage0}"
DIR="$ROOT/test/repro/append_only"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-append-only.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[[ -x "$STAGE1" ]] || { echo "append-only smoke: missing Stage1: $STAGE1" >&2; exit 2; }
COMPILERS=("$STAGE1")
if [[ -x "$STAGE0" ]]; then
    bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
    COMPILERS+=("$STAGE0")
fi

failures=0
for compiler in "${COMPILERS[@]}"; do
    tag="$(basename -- "$compiler")"
    for pos in append_only_store.pos.elisa append_only_holder.pos.elisa append_only_thread_own_slot.pos.elisa; do
        if ! "$compiler" -emit llvm "$DIR/$pos" -o "$WORK/pos.ll" >"$WORK/pos.log" 2>&1; then
            echo "append-only smoke: $tag rejected $pos" >&2
            cat "$WORK/pos.log" >&2
            failures=$((failures + 1))
        fi
    done
    expects=("$DIR/EXPECT")
    [[ "$compiler" == "$STAGE1" ]] && expects+=("$DIR/EXPECT.stage1")
    while IFS=$'\t' read -r name want; do
        [[ -z "$name" || "$name" == \#* ]] && continue
        log="$WORK/$tag-$name.log"
        if "$compiler" -emit llvm "$DIR/$name" -o "$WORK/neg.ll" >"$log" 2>&1; then
            echo "append-only smoke: $tag accepted $name" >&2
            failures=$((failures + 1))
        elif ! grep -qF -- "$want" "$log"; then
            echo "append-only smoke: $tag rejected $name for another reason (want: $want)" >&2
            sed -n '1,5p' "$log" >&2
            failures=$((failures + 1))
        fi
    done < <(cat "${expects[@]}")
done
[[ $failures -eq 0 ]] || exit 1
echo "append-only store smoke: ok (${#COMPILERS[@]} compiler(s))"
