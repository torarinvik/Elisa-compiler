#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$ROOT/test/parity/run_timeout.sh"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-catch-local-scope.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT

for optimization in 0 2; do
    for fixture in catch_error_union_local_scope catch_error_union_payload_local_scope catch_error_union_payload_error_binder catch_error_union_statement_arms; do
        if ! "$STAGE1" -emit exe "-O$optimization" -o "$WORK/native" \
            "$ROOT/test/fixtures/backend/$fixture.elisa" >"$WORK/compile.log" 2>&1; then
            cat "$WORK/compile.log" >&2
            echo "catch local scope smoke FAIL: compile $fixture at O$optimization" >&2
            exit 1
        fi
        if ! elisa_run_timeout 10 "$WORK/native" >"$WORK/run.log" 2>&1; then
            cat "$WORK/run.log" >&2
            echo "catch local scope smoke FAIL: $fixture at O$optimization" >&2
            exit 1
        fi
    done
done

echo "catch error-union local scope and payload binders OK at O0/O2"
