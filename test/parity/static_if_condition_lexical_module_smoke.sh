#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/test/parity/resolve_elisac.sh"
S0="${ELISA_STAGE0_BIN:-$ELISACORE_BIN}"
S1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/static-if-lexical-module.XXXXXX")"
trap 'rc=$?; if [[ "$rc" -eq 0 ]]; then rm -rf "$WORK"; else echo "static-if lexical-module artifacts retained at $WORK" >&2; fi; exit "$rc"' EXIT

fail() { echo "static-if lexical-module smoke FAIL: $*" >&2; exit 1; }
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$S0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$S1"
python3 "$ROOT/test/proofs/check_backend_static_if_lexical_module.py"

FIXTURE="$ROOT/test/repro/static_if_condition_lexical_module.elisa"
for row in "stage0:$S0" "stage1:$S1"; do
    stage="${row%%:*}"
    compiler="${row#*:}"
    rc=0
    "$compiler" -emit llvm -o "$WORK/$stage.ll" "$FIXTURE" >"$WORK/$stage.out" 2>"$WORK/$stage.err" || rc=$?
    [[ "$rc" -eq 1 ]] || fail "$stage should reject a runtime call to the active static helper, got exit $rc"
    grep -Fq 'static function "compile_time_helper" can only be called from a static context' "$WORK/$stage.err" || fail "$stage evaluated the enclosing static-if condition in Outer::Inner instead of Outer"
done

# This executable reaches codegen without an earlier semantic rejection. The
# root-level false value must not override Outer::FEATURE when choosing a row.
BACKEND_FIXTURE="$ROOT/test/repro/static_if_backend_lexical_module.elisa"
if ! "$S1" -emit exe -O0 -o "$WORK/stage1-backend" "$BACKEND_FIXTURE" >"$WORK/stage1-backend.out" 2>"$WORK/stage1-backend.err"; then
    fail "stage1 could not compile the backend lexical-module probe: $(cat "$WORK/stage1-backend.err")"
fi
if ! "$WORK/stage1-backend"; then
    fail "stage1 selected the root FEATURE instead of Outer::FEATURE"
fi

echo 'static-if lexical-module smoke OK'
