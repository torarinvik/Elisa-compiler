#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

nonnull=$(printf 'struct Box:\n    value: int\n\ndef bad() -> void:\n    box: Box& = null\n' | "$RPT")
grep -q '^D 1$' <<< "$nonnull"
grep -q 'expects non-null reference, got null' <<< "$nonnull"

optional=$(printf 'struct Box:\n    value: int\n\ndef ok() -> void:\n    box: Box&? = null\n' | "$RPT")
grep -q '^D 0$' <<< "$optional"

echo "nullability smoke OK" >&2
