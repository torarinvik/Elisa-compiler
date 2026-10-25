#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$REPO_ROOT/test/repro/import_conflict_mutually_exclusive_static_branches.elisa")"
if grep -q 'conflicting import: "choose"' <<< "$report"; then
  printf 'mutually-exclusive import smoke failed; inactive static arm still conflicts:\n%s\n' "$report" >&2
  exit 1
fi

same_line_report="$("$RPT" < "$REPO_ROOT/test/repro/import_conflict_same_logical_line.elisa")"
if ! grep -q 'conflicting import: "choose"' <<< "$same_line_report"; then
  printf 'same-logical-line import smoke failed; distinct source modules were treated as one import:\n%s\n' "$same_line_report" >&2
  exit 1
fi

unknown_siblings_report="$(ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown "$RPT" < "$REPO_ROOT/test/repro/import_conflict_unknown_static_siblings.elisa")"
if grep -q 'conflicting import: "choose"' <<< "$unknown_siblings_report"; then
  printf 'unknown static sibling smoke failed; opposite arms of one target-dependent chain still conflict:\n%s\n' "$unknown_siblings_report" >&2
  exit 1
fi

unknown_unconditional_report="$(ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown "$RPT" < "$REPO_ROOT/test/repro/import_conflict_unknown_static_unconditional.elisa")"
if ! grep -q 'conflicting import: "choose"' <<< "$unknown_unconditional_report"; then
  printf 'unknown static unconditional control failed; a competing unconditional import was hidden:\n%s\n' "$unknown_unconditional_report" >&2
  exit 1
fi

unknown_separate_chains_report="$(ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown "$RPT" < "$REPO_ROOT/test/repro/import_conflict_unknown_static_separate_chains.elisa")"
if ! grep -q 'conflicting import: "competing"' <<< "$unknown_separate_chains_report"; then
  printf 'unknown static separate-chain control failed; competing independent chains were hidden:\n%s\n' "$unknown_separate_chains_report" >&2
  exit 1
fi

printf 'mutually-exclusive static import smoke OK\n'
