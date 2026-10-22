#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
export ELISA_STAGE1_BIN="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
export ELISA_RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
source "$ROOT/test/parity/build_parse_report.sh"

complete=$("$RPT" < "$ROOT/test/repro/catch_module_qualified_exhaustive.elisa")
grep -q '^D 0$' <<< "$complete"

incomplete=$("$RPT" < "$ROOT/test/repro/catch_module_qualified_incomplete.elisa")
grep -q '^D 1$' <<< "$incomplete"
grep -q 'non-exhaustive catch over Fault; missing Fault.Extra' <<< "$incomplete"

subset=$("$RPT" < "$ROOT/test/repro/catch_module_qualified_subset.elisa")
grep -q '^D 1$' <<< "$subset"
grep -q 'catch arm "Local::Fault.Forbidden" does not match the caught call' <<< "$subset"

qualified_family=$("$RPT" < "$ROOT/test/repro/catch_qualified_error_family_path.elisa")
grep -q '^D 1$' <<< "$qualified_family"
grep -q 'non-exhaustive catch over Fault; missing Fault.ProviderOnly' <<< "$qualified_family"

nested=$("$RPT" < "$ROOT/test/repro/catch_nested_module_qualified.elisa")
grep -q '^D 1$' <<< "$nested"
grep -q 'non-exhaustive catch over Fault; missing Fault.Missing' <<< "$nested"

multi_family=$("$RPT" < "$ROOT/test/repro/catch_multi_family_incomplete.elisa")
grep -q '^D 1$' <<< "$multi_family"
grep -q 'non-exhaustive catch over SecondFault; missing SecondFault.Busy' <<< "$multi_family"

extra_prefix=$("$RPT" < "$ROOT/test/repro/catch_extra_module_prefix.elisa")
grep -q '^D 2$' <<< "$extra_prefix"
grep -q 'catch arm "Wrong::Other::Fault.Broken" does not match the caught call' <<< "$extra_prefix"
grep -q 'non-exhaustive catch over Fault; missing Fault.Broken' <<< "$extra_prefix"

echo "catch module-qualified variants smoke OK" >&2
