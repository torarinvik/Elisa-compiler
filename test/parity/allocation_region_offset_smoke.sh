#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}"
source "$ROOT/test/parity/resolve_elisac.sh"
source "$ROOT/test/parity/build_parse_report.sh"
python3 "$ROOT/test/proofs/check_allocation_region_offset_metadata.py"
python3 "$ROOT/test/proofs/check_allocation_region_consumers.py"

fail() { echo "allocation-region-offset smoke FAIL: $1" >&2; exit 1; }
out="$(cat "$ROOT/test/repro/allocation_region_offset_line0.elisa" | "$RPT")"
grep -q '^P 0$' <<< "$out" || fail "parse error: $out"
grep -Eq '^D [1-9][0-9]*$' <<< "$out" || fail "expected local-region escape diagnostics: $out"
grep -q 'cannot return reference: region dependency facts include local region "first"' <<< "$out" || fail "first same-line allocation lost its region owner: $out"
grep -q 'cannot return reference: region dependency facts include local region "second"' <<< "$out" || fail "second same-line allocation lost its region owner: $out"
struct_field_out="$(cat "$ROOT/test/repro/region_new_struct_field_auto_read.elisa" | "$RPT")"
grep -q '^P 0$' <<< "$struct_field_out" || fail "struct-field allocation parse error: $struct_field_out"
grep -q '^D 0$' <<< "$struct_field_out" || fail "struct-field scalar control changed: $struct_field_out"
reference_field_out="$(cat "$ROOT/test/repro/allocation_region_struct_field_escape.elisa" | "$RPT")"
grep -q '^P 0$' <<< "$reference_field_out" || fail "reference struct-field allocation parse error: $reference_field_out"
grep -q 'cannot return reference: region dependency facts include local region "scratch"' <<< "$reference_field_out" || fail "region allocation hidden in a struct field lost its escape dependency: $reference_field_out"
echo "allocation-region-offset smoke OK"
