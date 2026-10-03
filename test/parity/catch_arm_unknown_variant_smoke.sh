#!/usr/bin/env bash
# A catch arm naming no declared error variant (a stale family after a rename, or a
# family qualified with the wrong module) is reported at the catch instead of making
# the backend decline the unit as an opaque "control expression".
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

prefix=$'module Io:\n    public:\n        error IoError:\n            Missing\n            Busy\n        def open(flag: bool) -> i64 error[IoError]:\n            raise IoError.Missing if flag\n            return 1\nerror OtherError:\n    Gone\ndef load(flag: bool) -> i64:\n    got: i64 = catch Io::open(flag):\n        value: value\n'

ok=$(printf '%s%s' "$prefix" $'        Io::IoError.Missing: 0\n        error failure: 2\n    return got\n' | "$RPT")
grep -q '^D 0$' <<< "$ok"

stale=$(printf '%s%s' "$prefix" $'        Io::IoFault.Missing: 0\n        error failure: 2\n    return got\n' | "$RPT")
grep -q 'catch arm "Io::IoFault.Missing" does not match' <<< "$stale"

wrong_module=$(printf '%s%s' "$prefix" $'        Io::OtherError.Gone: 0\n        error failure: 2\n    return got\n' | "$RPT")
grep -q 'catch arm "Io::OtherError.Gone" does not match' <<< "$wrong_module"

missing_variant=$(printf '%s%s' "$prefix" $'        Io::IoError.Lost: 0\n        error failure: 2\n    return got\n' | "$RPT")
grep -q 'catch arm "Io::IoError.Lost" does not match' <<< "$missing_variant"

echo "catch arm unknown variant smoke OK" >&2
