#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

POSITIVE_FIXTURE="$REPO_ROOT/test/repro/errorset_param_shadow_same_module.elisa"
positive_report="$("$RPT" < "$POSITIVE_FIXTURE")"
positive_warning_count="$(grep -c 'shadows the declared error set' <<< "$positive_report" || true)"
if [[ "$positive_warning_count" -ne 2 ]]; then
  printf 'errorset shadow smoke failed; expected same-module and nested-module warnings, got %s:\n%s\n' "$positive_warning_count" "$positive_report" >&2
  exit 1
fi

FIXTURE="$REPO_ROOT/test/repro/errorset_param_shadow_sibling_module.elisa"
report="$("$RPT" < "$FIXTURE")"
if grep -q 'shadows the declared error set' <<< "$report"; then
  printf 'errorset sibling-module shadow smoke failed; an invisible error set triggered a warning:\n%s\n' "$report" >&2
  exit 1
fi

printf 'errorset sibling-module shadow smoke OK\n'
