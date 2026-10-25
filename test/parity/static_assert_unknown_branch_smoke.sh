#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"

report="$(ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown "$RPT" < "$ROOT/test/repro/static_assert_unknown_branch.elisa")"
if grep -Eq 'unknown condition assert|unknown condition static error|static assert failed' <<< "$report"; then
  printf 'Static-assert unknown-branch smoke failed; an unresolved assertion was evaluated:\n%s\n' "$report" >&2
  exit 1
fi

printf 'Static-assert unknown-branch smoke OK\n'
