#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

prefix=$'error FileError:\n    NotFound\n    Busy\nextern read_value(flag: bool) -> i64 error[FileError]\ndef load(flag: bool) -> i64:\n    return catch read_value(flag):\n        value:\n            value\n'

missing=$(printf '%s%s' "$prefix" $'        NotFound:\n            1\n' | "$RPT")
printf '%s\n' "$missing" | grep -q "non-exhaustive catch over \"FileError\"; missing error \"Busy\""

complete=$(printf '%s%s' "$prefix" $'        NotFound:\n            1\n        Busy:\n            2\n' | "$RPT")
printf '%s\n' "$complete" | grep -q '^D 0$'

qualified=$(printf '%s%s' "$prefix" $'        FileError.NotFound:\n            1\n        FileError.Busy:\n            2\n' | "$RPT")
printf '%s\n' "$qualified" | grep -q '^D 0$'

fallback=$(printf '%s%s' "$prefix" $'        error e:\n            0\n' | "$RPT")
printf '%s\n' "$fallback" | grep -q '^D 0$'

echo "catch exhaustiveness smoke OK" >&2
