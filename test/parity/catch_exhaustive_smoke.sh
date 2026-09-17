#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

prefix=$'error FileError:\n    NotFound\n    Busy\nextern read_value(flag: bool) -> i64 error[FileError]\ndef load(flag: bool) -> i64:\n    return catch read_value(flag):\n        value:\n            value\n'

missing=$(printf '%s%s' "$prefix" $'        NotFound:\n            1\n' | "$RPT")
# Older stage0 products quoted the family and bare missing variant.  The current
# diagnostic contract prints the fully-qualified names without quotes.  Accept
# both spellings while keeping the semantic assertion exact: this case must
# report the one missing FileError.Busy arm.
grep -Eq 'non-exhaustive catch over ("FileError"|FileError); missing (error "Busy"|FileError\.Busy)' <<< "$missing"

complete=$(printf '%s%s' "$prefix" $'        NotFound:\n            1\n        Busy:\n            2\n' | "$RPT")
grep -q '^D 0$' <<< "$complete"

qualified=$(printf '%s%s' "$prefix" $'        FileError.NotFound:\n            1\n        FileError.Busy:\n            2\n' | "$RPT")
grep -q '^D 0$' <<< "$qualified"

fallback=$(printf '%s%s' "$prefix" $'        error e:\n            0\n' | "$RPT")
grep -q '^D 0$' <<< "$fallback"

echo "catch exhaustiveness smoke OK" >&2
