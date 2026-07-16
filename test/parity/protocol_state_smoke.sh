#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

mismatch=$(printf 'extern join(thread: Thread[i64, Joinable]) -> i64\n\ndef bad(thread: Thread[i64, Pending]) -> i64:\n    return join(move thread)\n' | "$RPT")
printf '%s\n' "$mismatch" | grep -q '^D 1$'
printf '%s\n' "$mismatch" | grep -q "expects Joinable, got Pending"

matching=$(printf 'extern join(thread: Thread[i64, Joinable]) -> i64\n\ndef ok(thread: Thread[i64, Joinable]) -> i64:\n    return join(move thread)\n' | "$RPT")
printf '%s\n' "$matching" | grep -q '^D 0$'

echo "protocol state smoke OK" >&2
