#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

without_using=$(printf 'module math:\n    def inc(value: int) -> int:\n        return value + 1\n\ndef run() -> int:\n    return inc(41)\n' | "$RPT")
printf '%s\n' "$without_using" | grep -q "undefined identifier \"inc\""

with_using=$(printf 'module math:\n    def inc(value: int) -> int:\n        return value + 1\n\nusing math\n\ndef run() -> int:\n    return inc(41)\n' | "$RPT")
printf '%s\n' "$with_using" | grep -q '^D 0$'

inside_owner=$(printf 'module math:\n    def inc(value: int) -> int:\n        return value + 1\n    def twice(value: int) -> int:\n        return inc(inc(value))\n' | "$RPT")
printf '%s\n' "$inside_owner" | grep -q '^D 0$'

echo "namespace visibility smoke OK" >&2
