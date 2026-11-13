#!/usr/bin/env bash
# Generic interface bounds must resolve owners by source offset when #line maps several
# functions to logical line zero. The valid relay must not inherit build's or bad's rows.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_generic_interface_bound_owner_identity.py"

FIXTURE="$REPO_ROOT/test/repro/generic_interface_bound_owner_line0.elisa"
report="$("$RPT" < "$FIXTURE")"
expected='type "sview" does not satisfy required interface fact "Builder" for type argument'
count="$(grep -Fc 'does not satisfy required interface fact' <<< "$report" || true)"
[[ "$count" == 1 ]] || {
    echo "generic interface line-zero smoke: expected one failure from bad[sview], got $count" >&2
    printf '%s\n' "$report" >&2
    exit 1
}
grep -Fq "$expected" <<< "$report" || {
    echo "generic interface line-zero smoke: missing expected bound diagnostic" >&2
    printf '%s\n' "$report" >&2
    exit 1
}

qualified="$REPO_ROOT/test/differential/cases/impl_in_module.elisa"
report="$("$RPT" < "$qualified")"
grep -Fxq 'P 0' <<< "$report"
grep -Fxq 'D 0' <<< "$report"

# A same-named type from another module cannot use Studio's implementation.
report="$(sed '/^def main()/i\
module Other:\
    public:\
        struct ModulePen:\
            tag: i32\
' "$qualified" | sed 's/paint_with\[Studio::ModulePen\]/paint_with[Other::ModulePen]/' | "$RPT")"
grep -Fxq 'P 0' <<< "$report"
grep -Fxq 'D 1' <<< "$report"
grep -Fq 'does not satisfy required interface fact "Painter"' <<< "$report"

echo "generic interface line-zero smoke OK"
