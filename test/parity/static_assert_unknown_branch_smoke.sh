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

wasm_report="$(sed 's/UNRESOLVED_TARGET_FLAG/ELISA_TARGET_OS_WASI/' "$ROOT/test/repro/static_assert_unknown_branch.elisa" | ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown "$RPT")"
grep -q 'static assert failed: unknown condition assert' <<< "$wasm_report" || { printf 'Wasm branch was not selected:\n%s\n' "$wasm_report" >&2; exit 1; }
grep -q 'static error: unknown condition static error' <<< "$wasm_report" || { printf 'Wasm static call was not evaluated:\n%s\n' "$wasm_report" >&2; exit 1; }
printf 'Static-assert unknown-branch smoke OK\n'
