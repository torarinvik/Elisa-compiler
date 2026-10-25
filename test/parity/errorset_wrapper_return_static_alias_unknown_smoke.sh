#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_static_alias_unknown.elisa"

report="$("$RPT" < "$FIXTURE")"
diagnostics="$(grep -c 'cannot propagate' <<< "$report" || true)"
[[ "$diagnostics" == 9 ]] || {
  printf 'static-alias EWR smoke failed; expected nine definite family mismatches and no unresolved-alias cascade:\n%s\n' "$report" >&2
  exit 1
}
[[ "$(grep -c 'cannot propagate.*CandidateFault' <<< "$report" || true)" == 6 ]] || {
  printf 'static-alias EWR smoke failed; definite, earlier-branch, same-scope or nested-module prepass, earlier-registration, or alias-path winners did not select CandidateFault:\n%s\n' "$report" >&2
  exit 1
}
grep -q 'cannot propagate.*NestedFault' <<< "$report" || {
  printf 'static-alias EWR smoke failed; an alias spelling after the qualifier head blocked the direct module path:\n%s\n' "$report" >&2
  exit 1
}
grep -q 'cannot propagate.*NestedGlobalFault' <<< "$report" || {
  printf 'static-alias EWR smoke failed; a nested module alias was not visible to the root call:\n%s\n' "$report" >&2
  exit 1
}
grep -q 'cannot propagate.*LexicalPathFault' <<< "$report" || {
  printf 'static-alias EWR smoke failed; a lexical module prefix did not outrank the global module alias:\n%s\n' "$report" >&2
  exit 1
}

echo "errorset wrapper static-alias uncertainty smoke OK"
