#!/usr/bin/env bash
# A same-line generic sibling must not make projected storage-region ownership unknown.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_region_escape_generic_owner_identity.py"

FIXTURE="$REPO_ROOT/test/repro/region_escape_generic_owner_line_collision.elisa"
fail() { echo "region escape generic owner smoke FAIL: $1" >&2; exit 1; }

stage0_rc=0
stage0_out="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)" || stage0_rc=$?
[[ "$stage0_rc" -eq 0 ]] || fail "stage0 rejected the exact-owner fixture: $stage0_out"

stage1_out="$("$RPT" < "$FIXTURE")"
grep -q '^P 0$' <<< "$stage1_out" || fail "stage1 parse errors: $stage1_out"
grep -q '^D 0$' <<< "$stage1_out" || fail "expected no region diagnostics: $stage1_out"

echo "region escape generic owner line-collision smoke OK"
