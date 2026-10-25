#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$REPO_ROOT/test/repro/unknown_type_in_inactive_static_scopes.elisa")"
expected_types=(ActiveAliasTarget ActiveParameterType ActiveLocalType InactiveOnlyAlias NestedActiveAliasTarget InactiveNominalStruct InactiveNominalEnum)
for type_name in "${expected_types[@]}"; do
  if [[ "$(grep -c "unknown type \"$type_name\"" <<< "$report" || true)" != 1 ]]; then
    printf 'unknown-type static-scope smoke failed; expected one active diagnostic for %s:\n%s\n' \
      "$type_name" "$report" >&2
    exit 1
  fi
done

if grep -Eq 'unknown type "(RegisteredStruct|RegisteredEnum)"' <<< "$report"; then
  printf 'unknown-type static-scope smoke failed; a registered nominal type was reported unknown:\n%s\n' \
    "$report" >&2
  exit 1
fi

if grep -Eq 'unknown type "(Inactive(AliasTarget|ParameterType|LocalType)|NestedInactiveAliasTarget)"' <<< "$report"; then
  printf 'unknown-type static-scope smoke failed; an inactive static body was checked:\n%s\n' "$report" >&2
  exit 1
fi

if grep -Eq 'unknown type "(PossibleCycleRoot|PossibleCycleBranch)"' <<< "$report"; then
  printf 'unknown-type static-scope smoke failed; an unresolved alias branch lost a possible declaration:\n%s\n' "$report" >&2
  exit 1
fi

printf 'unknown-type static-scope smoke OK\n'
