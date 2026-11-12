#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_static_alias_unknown.elisa"

report="$("$RPT" < "$FIXTURE")"
grep -q 'L99 cannot propagate CandidateFault' <<< "$report" || {
  printf 'definite alias must outrank the unresolved branch:\n%s\n' "$report" >&2
  exit 1
}
if grep -q 'L96 cannot propagate' <<< "$report"; then
  printf 'unresolved alias must not select a family:\n%s\n' "$report" >&2
  exit 1
fi

# Replacing the definite registration with another unresolved branch makes the
# winner unknown; the checker must not infer either error family.
ambiguous="$(sed 's/^using CandidateProvider as Stable$/static if UNKNOWN_PROVIDER_CHOICE:\
    using CandidateProvider as Stable/' "$FIXTURE" | "$RPT")"
if grep -q 'cannot propagate CandidateFault' <<< "$(grep 'L10[01] ' <<< "$ambiguous" || true)"; then
  printf 'competing unresolved aliases must not select a family:\n%s\n' "$ambiguous" >&2
  exit 1
fi

# A possible registration in an earlier branch may win before the selected
# branch. Reversing the two declarations must therefore suppress inference.
reversed="$(python3 - "$FIXTURE" <<'PYFIXTURE' | "$RPT"
from pathlib import Path
import sys
source = Path(sys.argv[1]).read_text()
earlier = 'static if true:\n    using CandidateProvider as Earlier\nstatic if UNKNOWN_PROVIDER_CHOICE:\n    using OtherProvider as Earlier'
later = 'static if UNKNOWN_PROVIDER_CHOICE:\n    using OtherProvider as Earlier\nstatic if true:\n    using CandidateProvider as Earlier'
if earlier not in source:
    raise SystemExit('expected branch declarations missing from fixture')
print(source.replace(earlier, later), end='')
PYFIXTURE
)"
if grep -q 'L102 cannot propagate' <<< "$reversed"; then
  printf 'earlier unresolved branch must prevent family inference:\n%s\n' "$reversed" >&2
  exit 1
fi

echo 'errorset wrapper unresolved-alias shadow smoke OK'
