#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

out=$(printf 'def use() -> i64:\n    x: i64 = 42i64\n    y: f64 = 1.5f64\n    return x\n' | "$RPT")
echo "$out" | grep -Fq 'numeric literal suffix "i64" is discouraged' || { echo "missing i64 suffix warning: $out" >&2; exit 1; }
echo "$out" | grep -Fq 'numeric literal suffix "f64" is discouraged' || { echo "missing f64 suffix warning: $out" >&2; exit 1; }

plain=$(printf 'def use() -> i64:\n    x: i64 = 42\n    y: f64 = 1.5\n    return x\n' | "$RPT")
if echo "$plain" | grep -Fq 'numeric literal suffix'; then
    echo "unsuffixed literal produced suffix warning: $plain" >&2
    exit 1
fi

echo "numeric suffix smoke OK: explicit suffixes warn and contextual literals stay silent"
