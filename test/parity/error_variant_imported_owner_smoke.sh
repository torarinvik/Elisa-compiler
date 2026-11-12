#!/usr/bin/env bash
# A program-wide selective import selects its error-set owner even when another
# module declares an error set with the same leaf name.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fixture="$REPO_ROOT/test/repro/backend_bare_variant_visibility.elisa"
report="$("$RPT" < "$fixture")"
if grep -Eq 'L(18|26|47|98) enum "Expected" has no variant "Other"' <<< "$report"; then
    printf 'selected imported error-set variant was rejected:\n%s\n' "$report" >&2
    exit 1
fi
wrong="$(sed 's/raise Expected.Other(37)/raise Expected.Missing(37)/' "$fixture" | "$RPT")"
grep -q 'L18 enum "Expected" has no variant "Missing"' <<< "$wrong" || {
    printf 'unknown imported error-set variant was not rejected:\n%s\n' "$wrong" >&2
    exit 1
}
wildcard_missing="$(sed 's/raise Expected.Other(53)/raise Expected.Missing(53)/' "$fixture" | "$RPT")"
grep -q 'L98 enum "Expected" has no variant "Missing"' <<< "$wildcard_missing" || {
    printf 'unknown wildcard-imported variant was not rejected:\n%s\n' "$wildcard_missing" >&2
    exit 1
}
lexical="$(cat <<'CASE' | "$RPT"
module Outer:
    error E:
        A
    module Child:
        def f() -> i64 error[E]:
            raise E.Missing
module Other:
    public:
        error E:
            Missing
from Other import E
CASE
)"
grep -q 'enum "E" has no variant "Missing"' <<< "$lexical" || {
    printf 'enclosing enum did not outrank imported enum:\n%s\n' "$lexical" >&2
    exit 1
}
wildcard="$(cat <<'CASE' | "$RPT"
module Other:
    public:
        error E:
            OtherTag
module Client:
    module Inner:
        public:
            error E:
                LocalTag
    using Inner
    def f() -> i64 error[E]:
        raise E.LocalTag
from Other import E
CASE
)"
if grep -q 'enum "E" has no variant "LocalTag"' <<< "$wildcard"; then
    printf 'local wildcard enum did not outrank global import:\n%s\n' "$wildcard" >&2
    exit 1
fi
if grep -Eq 'L(36|58) raise cannot propagate' <<< "$report"; then
    printf 'error-set alias rejected its resolved family:\n%s\n' "$report" >&2
    exit 1
fi
wrong_alias="$(sed 's/raise SetProvider::Expected.Other(97)/raise Fault.BareTag(97)/' "$fixture" | "$RPT")"
grep -q 'L36 raise cannot propagate tag "Fault.BareTag"' <<< "$wrong_alias" || {
    printf 'error-set alias accepted an unrelated family:\n%s\n' "$wrong_alias" >&2
    exit 1
}
echo 'imported error variant owner smoke OK'
