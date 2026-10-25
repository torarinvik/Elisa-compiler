#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_errorset_shadow_candidate_order.py" --source-only

FIXTURE="$REPO_ROOT/test/repro/errorset_param_local_type_shadows_import.elisa"
report="$("$RPT" < "$FIXTURE")"
if grep -q 'shadows the declared error set' <<< "$report"; then
  printf 'errorset local-type shadow smoke failed; imported Provider.Fault must not win over Consumer.Fault:\n%s\n' "$report" >&2
  exit 1
fi

ALIAS_FIXTURE="$REPO_ROOT/test/repro/errorset_param_local_alias_shadows_import.elisa"
alias_report="$("$RPT" < "$ALIAS_FIXTURE")"
if grep -q 'shadows the declared error set' <<< "$alias_report"; then
  printf 'errorset local-alias shadow smoke failed; imported Provider.Fault must not win over Consumer.Fault:\n%s\n' "$alias_report" >&2
  exit 1
fi

ERRORSET_ALIAS_FIXTURE="$REPO_ROOT/test/repro/errorset_param_alias_to_imported_errorset.elisa"
errorset_alias_report="$("$RPT" < "$ERRORSET_ALIAS_FIXTURE")"
errorset_alias_warnings="$(grep -c 'shadows the declared error set' <<< "$errorset_alias_report" || true)"
if [[ "$errorset_alias_warnings" != 1 ]]; then
  printf 'errorset alias identity smoke failed; alias to Provider.Fault should still identify the ErrorSet:\n%s\n' "$errorset_alias_report" >&2
  exit 1
fi

LOCAL_ERRORSET_FIXTURE="$REPO_ROOT/test/repro/errorset_param_local_errorset_shadows_import.elisa"
local_errorset_report="$("$RPT" < "$LOCAL_ERRORSET_FIXTURE")"
local_errorset_warnings="$(grep -c 'shadows the declared error set' <<< "$local_errorset_report" || true)"
if [[ "$local_errorset_warnings" != 1 ]]; then
  printf 'errorset local-declaration precedence smoke failed; Consumer.Fault should beat imported Provider.Fault:\n%s\n' "$local_errorset_report" >&2
  exit 1
fi

SIBLING_ALIAS_FIXTURE="$REPO_ROOT/test/repro/errorset_param_local_alias_to_sibling_import.elisa"
sibling_alias_report="$("$RPT" < "$SIBLING_ALIAS_FIXTURE")"
sibling_alias_warnings="$(grep -c 'shadows the declared error set' <<< "$sibling_alias_report" || true)"
if [[ "$sibling_alias_warnings" != 1 ]]; then
  printf 'errorset sibling-import alias smoke failed; LocalFault should retain AliasFault ErrorSet identity:\n%s\n' "$sibling_alias_report" >&2
  exit 1
fi

printf 'errorset local-type shadow smoke OK\n'
