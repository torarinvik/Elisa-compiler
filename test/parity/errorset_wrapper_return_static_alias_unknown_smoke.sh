#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_static_alias_unknown.elisa"

report="$("$RPT" < "$FIXTURE")"
diagnostics="$(grep -c 'return type expects error\[ExpectedFault\], got error\[' <<< "$report" || true)"
[[ "$diagnostics" == 8 ]] || {
  printf 'static-alias EWR smoke failed; expected eight definite family mismatches and no unresolved-alias cascade:\n%s\n' "$report" >&2
  exit 1
}
[[ "$(grep -c 'return type expects error\[ExpectedFault\], got error\[CandidateFault\]' <<< "$report" || true)" == 6 ]] || {
  printf 'static-alias EWR smoke failed; definite, earlier-branch, same-scope or nested-module prepass, earlier-registration, or alias-path winners did not select CandidateFault:\n%s\n' "$report" >&2
  exit 1
}
grep -q 'return type expects error\[ExpectedFault\], got error\[NestedFault\]' <<< "$report" || {
  printf 'static-alias EWR smoke failed; an alias spelling after the qualifier head blocked the direct module path:\n%s\n' "$report" >&2
  exit 1
}
if grep -q 'return type expects error\[ExpectedFault\], got error\[NestedGlobalFault\]' <<< "$report"; then
  printf 'static-alias EWR smoke failed; an out-of-scope alias supplied an error family:\n%s\n' "$report" >&2
  exit 1
fi
grep -q 'undefined identifier "NestedGlobal.wrap"' <<< "$report" || {
  printf 'static-alias EWR smoke failed; missing out-of-scope alias diagnostic:\n%s\n' "$report" >&2
  exit 1
}
grep -q 'return type expects error\[ExpectedFault\], got error\[LexicalPathFault\]' <<< "$report" || {
  printf 'static-alias EWR smoke failed; a lexical module prefix did not outrank the global module alias:\n%s\n' "$report" >&2
  exit 1
}

echo "errorset wrapper static-alias uncertainty smoke OK"
