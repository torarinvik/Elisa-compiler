#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

ordinary=$(printf 'enum Expr:\n    Block(items: tail int)\n' | "$RPT")
printf '%s\n' "$ordinary" | grep -q 'tail payloads are only supported for packed enums'

packed=$(printf 'packed enum Expr:\n    Block(items: tail int)\n' | "$RPT")
printf '%s\n' "$packed" | grep -q '^D 0$'

echo "enum tail payload smoke OK" >&2
