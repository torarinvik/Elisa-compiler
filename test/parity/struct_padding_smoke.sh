#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

out=$(printf 'struct Padded:\n    flag: bool\n    value: i64\n    small: i16\n' | "$RPT")
echo "$out" | grep -Fq 'struct "Padded" has 8 bytes of avoidable padding' || { echo "missing padding warning: $out" >&2; exit 1; }
echo "$out" | grep -Fq 'ordering fields as "value", "small", "flag"' || { echo "wrong reorder suggestion: $out" >&2; exit 1; }

dense=$(printf 'struct Dense:\n    value: i64\n    small: i16\n    flag: bool\n' | "$RPT")
if echo "$dense" | grep -Fq 'avoidable padding'; then
    echo "dense struct produced padding warning: $dense" >&2
    exit 1
fi

echo "struct padding smoke OK: avoidable primitive padding warns with stable field order"
