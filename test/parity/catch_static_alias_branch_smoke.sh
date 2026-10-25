#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$ROOT/test/repro/catch_static_alias_branch.elisa")"
diagnostic_count="$(grep -c 'non-exhaustive catch over Fault; missing Fault.Missing' <<< "$report" || true)"
if [[ "$diagnostic_count" != 8 ]]; then
  printf 'Catch static-alias smoke failed; expected selected-provider catches and the ancestor-relative ErrorSet path to report their missing variants, while unresolved aliases and qualified family misses stay unknown:\n%s\n' "$report" >&2
  exit 1
fi
if grep -q 'WrongOnly' <<< "$report"; then
  printf 'Catch static-alias smoke selected the inactive provider:\n%s\n' "$report" >&2
  exit 1
fi
if grep -q 'RootOnly' <<< "$report"; then
  printf 'Catch relative-family smoke fell through a declared empty family to the root Provider::Fault:\n%s\n' "$report" >&2
  exit 1
fi
if grep -q 'SubsetFault.Excluded' <<< "$report"; then
  printf 'Catch line-zero subset smoke required a variant excluded by the callee:\n%s\n' "$report" >&2
  exit 1
fi
branch_error_count="$(grep -c 'non-exhaustive catch over BranchFault; missing BranchFault.Missing' <<< "$report" || true)"
if [[ "$branch_error_count" != 1 ]]; then
  printf 'Catch static ErrorSet smoke failed to keep the active family variant set:\n%s\n' "$report" >&2
  exit 1
fi
if grep -q 'BranchFault.InactiveOnly' <<< "$report"; then
  printf 'Catch static ErrorSet smoke included a variant from the inactive declaration:\n%s\n' "$report" >&2
  exit 1
fi
if grep -q 'BranchSubsetFault' <<< "$report"; then
  printf 'Catch subset smoke counted duplicate or inactive static-branch ErrorSet variants:\n%s\n' "$report" >&2
  exit 1
fi
foreign_enum_count="$(grep -c 'non-exhaustive catch over ForeignEnum; missing ForeignEnum.OutOfRange' <<< "$report" || true)"
if [[ "$foreign_enum_count" != 1 ]]; then
  printf 'Catch synthetic ForeignEnum smoke failed when its first producer is inactive and a later producer is active:\n%s\n' "$report" >&2
  exit 1
fi
all_inactive_foreign_enum_report="$("$RPT" < "$ROOT/test/repro/catch_foreign_enum_all_inactive.elisa")"
if grep -q 'non-exhaustive catch over ForeignEnum' <<< "$all_inactive_foreign_enum_report"; then
  printf 'Catch synthetic ForeignEnum smoke retained a family whose producers are all inactive:\n%s\n' "$all_inactive_foreign_enum_report" >&2
  exit 1
fi
unknown_foreign_enum_report="$("$RPT" < "$ROOT/test/repro/catch_foreign_enum_unknown_origin.elisa")"
if grep -q 'non-exhaustive catch over ForeignEnum' <<< "$unknown_foreign_enum_report"; then
  printf 'Catch synthetic ForeignEnum smoke guessed a family from an unresolved producer branch:\n%s\n' "$unknown_foreign_enum_report" >&2
  exit 1
fi
printf 'Catch static-alias smoke OK\n'
