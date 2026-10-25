#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$REPO_ROOT/test/repro/errorset_shadow_static_import_branch.elisa")"
if grep -q 'shadows the declared error set' <<< "$report"; then
  printf 'ErrorSet shadow smoke failed; inactive ErrorSet import was treated as visible:\n%s\n' "$report" >&2
  exit 1
fi

unknown_report="$(ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown "$RPT" < "$REPO_ROOT/test/repro/errorset_shadow_unknown_static_import.elisa")"
if grep -q 'shadows the declared error set' <<< "$unknown_report"; then
  printf 'ErrorSet shadow smoke failed; unresolved static import was treated as a definite shadow:\n%s\n' "$unknown_report" >&2
  exit 1
fi

printf 'ErrorSet static-import shadow smoke OK\n'
