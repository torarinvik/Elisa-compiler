#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

optional=$(printf 'def maybe(flag: bool) -> int?:\n    return 7 if flag else null\ndef bad(flag: bool) -> int:\n    return try maybe(flag)\n' | "$RPT")
printf '%s\n' "$optional" | grep -q 'try without else requires an error union'

scalar=$(printf 'def bad() -> int:\n    value: int = try 7\n    return value\n' | "$RPT")
printf '%s\n' "$scalar" | grep -q 'try requires a fallible expression'

recovered=$(printf 'def maybe(flag: bool) -> int?:\n    return 7 if flag else null\ndef ok(flag: bool) -> int:\n    return try maybe(flag) else 0\n' | "$RPT")
printf '%s\n' "$recovered" | grep -q '^D 0$'

echo "try fallibility smoke OK" >&2
