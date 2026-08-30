#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

missing=$(printf 'def run() -> void:\n    _ = fn(value):\n        return value\n' | "$RPT")
printf '%s\n' "$missing" | grep -q 'block lambda requires an explicit return type or contextual function type'

typed=$(printf 'def run() -> void:\n    _ = fn(value) -> int:\n        return 1\n' | "$RPT")
printf '%s\n' "$typed" | grep -q '^D 0$'

echo "block lambda context smoke OK" >&2
