#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
python3 "$ROOT/test/proofs/check_lambda_arrow_body_source_region.py"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$ROOT/test/parity/run_timeout.sh"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-lambda-body-source.XXXXXX")"
cleanup() {
    rm -rf -- "$WORK"
}
trap cleanup EXIT

run_fixture() {
    local optimization="$1" fixture="$2" expected="$3"
    local label="$(basename "$fixture" .elisa)"
    local log="$WORK/$label-O$optimization.log"
    if ! "$STAGE1" -emit exe "-O$optimization" -o "$WORK/native" "$ROOT/$fixture" >"$log" 2>&1; then
        cat "$log" >&2
        echo "lambda body source region smoke FAIL: compile $label at O$optimization" >&2
        return 1
    fi

    local got
    if elisa_run_timeout 10 "$WORK/native" >"$WORK/run.log" 2>&1; then
        got=0
    else
        got=$?
    fi
    if [[ "$got" != "$expected" ]]; then
        cat "$WORK/run.log" >&2
        echo "lambda body source region smoke FAIL: $label at O$optimization exited $got, expected $expected" >&2
        return 1
    fi
}

for optimization in 0 2; do
    run_fixture "$optimization" test/fixtures/backend/lambda_body_source/plain_arrow.elisa 17
    run_fixture "$optimization" test/fixtures/backend/lambda_body_source/plain_block.elisa 17
    run_fixture "$optimization" test/fixtures/backend/lambda_body_source/fallible_arrow.elisa 14
    run_fixture "$optimization" test/fixtures/backend/lambda_body_source/fallible_block.elisa 14
done

echo "lambda arrow and block body source region smoke OK at O0/O2"
