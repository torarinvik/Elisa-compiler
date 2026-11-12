#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fixture="$REPO_ROOT/test/repro/error_union_static_import_branches.elisa"
report="$(ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown "$RPT" < "$fixture")"
unhandled_count="$(grep -c 'error union result must be handled' <<< "$report" || true)"
overload_line="$(awk '/^        choose\(1\)/ {print NR}' "$fixture")"
raw_module_line="$(awk '/^    RootCollision::load\(\)/ {print NR}' "$fixture")"
if [[ "$unhandled_count" != 2 ]] || ! grep -qF "L$overload_line error union result must be handled" <<< "$report" || ! grep -qF "L$raw_module_line error union result must be handled" <<< "$report"; then
  printf 'error-union static-branch smoke failed; expected the active overload and the root module call to require handling:\n%s\n' "$report" >&2
  exit 1
fi

native_report="$(env -u ELISA_STAGE1_TRIPLE -u ELISA_STAGE1_WASM "$RPT" < "$fixture")"
raw_module_line="$(awk '/^    RootCollision::load\(\)/ {print NR}' "$fixture")"
if ! grep -qF "L$raw_module_line error union result must be handled" <<< "$native_report"; then
  printf 'error-union static-branch smoke failed; the native target should select the raw module:\n%s\n' "$native_report" >&2
  exit 1
fi

printf 'error-union static-import smoke OK\n'
