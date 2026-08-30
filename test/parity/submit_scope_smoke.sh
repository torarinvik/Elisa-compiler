#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

bad=$(printf 'def work(value: i64) -> i64:\n    return value + 1\ndef bad() -> void:\n    _ = submit work(7)\n' | "$RPT")
echo "$bad" | grep -Fq 'submit requires an active pool scope' || { echo "submit outside pool accepted: $bad" >&2; exit 1; }

good=$(printf 'def work(value: i64) -> i64:\n    return value + 1\ndef ok() -> void:\n    pool workers(1):\n        _ = submit work(7)\n' | "$RPT")
echo "$good" | grep -Fq 'P 0' || { echo "submit inside pool rejected: $good" >&2; exit 1; }

echo "submit scope smoke OK: submit requires an active pool block"
