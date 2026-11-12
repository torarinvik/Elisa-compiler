#!/usr/bin/env bash
# Enclosing namespace members are visible to descendants, not siblings.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
report="$(cat <<'CASE' | "$RPT"
module FamilyOwner:
    public:
        error ParentFamily:
            Tag
    module Child:
        def good() -> i64 error[ParentFamily]:
            raise ParentFamily.Tag
module Unrelated:
    def bad() -> i64:
        ParentFamily.Tag
        return 0
CASE
)"
if grep -q 'L7 undefined identifier "ParentFamily"' <<< "$report"; then
    printf 'enclosing family was not resolved:\n%s\n' "$report" >&2
    exit 1
fi
grep -q 'L10 undefined identifier "ParentFamily"' <<< "$report" || {
    printf 'sibling unexpectedly resolved the family:\n%s\n' "$report" >&2
    exit 1
}
echo 'enclosing module member lookup smoke OK'
