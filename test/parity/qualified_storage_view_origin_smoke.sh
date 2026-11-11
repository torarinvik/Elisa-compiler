#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fixture="$REPO_ROOT/test/fixtures/diagnostics/storage_owned_return_module_scope.pos.elisa"
expected='view "source" cannot be used: storage dependency facts were invalidated by darray push of doc'

qualified="$(sed 's/= read(doc, /= Tracks::read(doc, /' "$fixture")"
extension="$(sed '/^        def grow(doc:/i\
extend Tracks:\
    public:
' <<< "$qualified")"
named="$(sed 's/Tracks::read(doc, 0, component)/Tracks::read(component: component, doc: doc, slot: 0)/' <<< "$qualified")"
for program in "$qualified" "$extension" "$named"; do
    report="$("$RPT" <<< "$program")"
    grep -Fxq 'P 0' <<< "$report"
    grep -Fxq 'D 1' <<< "$report"
    grep -Fq "$expected" <<< "$report"
done

for program in "$qualified" "$named"; do
    live="$(sed 's/changed <- changed + grow(doc, cleaned)/changed <- changed + 1/' <<< "$program")"
    report="$("$RPT" <<< "$live")"
    grep -Fxq 'P 0' <<< "$report"
    grep -Fxq 'D 0' <<< "$report"
done
printf 'qualified storage view origin smoke OK\n'
