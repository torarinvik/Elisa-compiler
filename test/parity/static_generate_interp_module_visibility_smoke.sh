#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "static-generate interpolation module-visibility smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/static_generate_interp_module_visibility.elisa"
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1 || true)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage0_count="$(printf '%s\n' "$stage0_output" | grep -Fc 'static generate interpolation must evaluate at compile time' || true)"
stage1_count="$(printf '%s\n' "$stage1_output" | grep -Fc 'static generate interpolation must evaluate at compile time' || true)"
[[ "$stage0_count" == 3 ]] || fail "Stage0 should diagnose two imported runtime calls and the child runtime shadow; found $stage0_count: $stage0_output"
[[ "$stage1_count" == "$stage0_count" ]] || fail "Stage1 diagnostics differ from Stage0 ($stage1_count vs $stage0_count): $stage1_output"

echo "static-generate interpolation module visibility matches Stage0"
