#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

narrow=$(printf 'struct Box:\n    value: int\ndef only_nonnull(box: Box&) -> int:\n    return box.value\ndef bad() -> int:\n    wider: fn(Box&?) -> int = only_nonnull\n    return wider(null)\n' | "$RPT")
printf '%s\n' "$narrow" | grep -q 'expects a callback that accepts nullable arguments'

broad=$(printf 'struct Box:\n    value: int\ndef allow_null(box: Box&?) -> int:\n    if box == null:\n        return 0\n    return box.value\ndef ok(box: Box&) -> int:\n    narrower: fn(Box&) -> int = allow_null\n    return narrower(box)\n' | "$RPT")
printf '%s\n' "$broad" | grep -q '^D 0$'

echo "function variance smoke OK" >&2
