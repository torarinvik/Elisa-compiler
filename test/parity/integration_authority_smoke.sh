#!/usr/bin/env bash
# Inline grants stay expression-local; runtime inclusion never grants authority.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:?Set ELISACORE_BIN to the fresh Stage0 compiler}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/integration-authority.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT INT TERM HUP
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
for mode in bare runtime; do
    for fixture in reference_authority_inline_grant.pos reference_authority_inline_sibling.neg reference_authority_wrong_inline_grant.neg function_global_collision.neg global_function_collision.neg; do
        source="$ROOT/test/repro/$fixture.elisa"
        probe="$WORK/probe.elisa"
        if [[ "$mode" == runtime ]]; then
            printf 'include "%s/elisacore_std/elisacore_runtime.elisa"\n' "$ROOT" > "$probe"
            cat "$source" >> "$probe"
        else
            cp "$source" "$probe"
        fi
        for compiler in "$STAGE0" "$STAGE1"; do
            status=0
            "$compiler" -emit obj -O0 -o "$WORK/probe.o" "$probe" > "$WORK/check.log" 2>&1 || status=$?
            if [[ "$fixture" == *.pos ]]; then
                [[ "$status" == 0 ]] || { cat "$WORK/check.log" >&2; exit 1; }
            else
                [[ "$status" != 0 ]] || { echo "Unexpected acceptance: $mode $fixture $compiler" >&2; exit 1; }
                if [[ "$fixture" == *collision* ]]; then
                    grep -qi 'duplicate' "$WORK/check.log"
                else
                    grep -Eq 'forges a reference|forging a reference' "$WORK/check.log" || { cat "$WORK/check.log" >&2; exit 1; }
                fi
            fi
        done
    done
done
echo 'integration authority smoke OK: inline isolation and value namespace collisions'
