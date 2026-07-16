#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

integer_bad=$(printf 'def classify(value: int) -> int:\n    match value:\n        "local":\n            return 1\n        _:\n            return 0\n    return 0\n' | "$RPT")
printf '%s\n' "$integer_bad" | grep -q 'top-level integer match arm must use an integer literal or _'

string_bad=$(printf 'enum Token:\n    Region\ndef classify(text: StringView) -> int:\n    match text:\n        Token.Region:\n            return 1\n        _:\n            return 0\n' | "$RPT")
printf '%s\n' "$string_bad" | grep -q 'top-level string match arm must use a string literal or _'

valid=$(printf 'def classify(value: int, text: StringView) -> int:\n    match value:\n        1:\n            pass\n        _:\n            pass\n    match text:\n        "local":\n            return 1\n        _:\n            return 0\n' | "$RPT")
printf '%s\n' "$valid" | grep -q '^D 0$'

echo "scalar match arm smoke OK" >&2
