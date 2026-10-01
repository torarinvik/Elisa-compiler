#!/usr/bin/env bash
# LMUT CALL ALIASING: an `lmut` argument named again by another argument of the same call.
#
#   rebind ok: bool, parser = parser.parse_named(captures, parser.source)   # receiver + field
#
# stage0 rejects every such call ("aliases another argument of the same call") at the later
# argument's span. stage1 checked only direct calls, without a column, and never treated a
# method receiver as an argument (hc1p). Direct calls now carry the span (resolve_expr.elisa);
# method calls are checked by src/semantic/check_lmut_method_aliasing.elisa.
#
#   1. rejected/*.elisa: both reject, no object, identical path-stripped errors;
#   2. accepted/*.elisa: both accept with a non-empty object.
#
# Not covered: `parser.eat((parser.source))` -- stage0 reports at the `(`; stage1's AST has
# no Paren there, so it reports at the field.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
DIR="$ROOT/test/repro/lmut_call_aliasing"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}"

stage0="${ELISACORE_BIN:-$ELISA_CORE/compiler/bin/elisac}"
if [[ -z "${ELISACORE_BIN:-}" ]]; then
    mkdir -p "$(dirname "$stage0")"
    ( cd "$ELISA_CORE/compiler" && go build -o "$stage0" ./src ) || { echo "lmut-call-aliasing FAIL: cannot build stage0" >&2; exit 2; }
fi
[[ -x "$stage0" ]] || { echo "lmut-call-aliasing FAIL: missing stage0 at $stage0" >&2; exit 2; }
stage1=(bash "$ROOT/scripts/elisac_stage1.sh")

# stage0 writes a ZERO-BYTE object for a source under /private/tmp; keep outputs under /tmp.
work="$(mktemp -d /tmp/lmut_call_aliasing.XXXXXX)"
trap 'rm -rf "$work"' EXIT INT TERM HUP
failed=0
count=0
fail() { echo "  FAIL $1"; failed=$((failed + 1)); }

errors_of() {   # log -> error lines with the source path stripped
    grep -v 'warning:' "$1" | sed -E 's#^.*\.elisa:##'
}

check_rejected() {
    local fixture="$1" name; name="$(basename "$fixture")"
    count=$((count + 1))
    rm -f "$work/s0.o" "$work/s1.o"
    "$stage0" -emit obj -o "$work/s0.o" "$fixture" > "$work/s0.log" 2>&1; local r0=$?
    "${stage1[@]}" -emit obj -o "$work/s1.o" "$fixture" > "$work/s1.log" 2>&1; local r1=$?
    [[ $r0 -ne 0 && ! -s "$work/s0.o" ]] || { fail "$name: stage0 accepted (rc=$r0)"; return; }
    [[ $r1 -ne 0 && ! -s "$work/s1.o" ]] || { fail "$name: stage1 accepted (rc=$r1)"; return; }
    if ! diff <(errors_of "$work/s0.log") <(errors_of "$work/s1.log") > "$work/diff"; then
        fail "$name: diagnostics differ (< stage0, > stage1)"; sed 's/^/      /' "$work/diff"
    fi
}

check_accepted() {
    local fixture="$1" name; name="$(basename "$fixture")"
    count=$((count + 1))
    rm -f "$work/s0.o" "$work/s1.o"
    "$stage0" -emit obj -o "$work/s0.o" "$fixture" > "$work/s0.log" 2>&1; local r0=$?
    "${stage1[@]}" -emit obj -o "$work/s1.o" "$fixture" > "$work/s1.log" 2>&1; local r1=$?
    [[ $r0 -eq 0 && -s "$work/s0.o" ]] || { fail "$name: stage0 rejected (rc=$r0)"; errors_of "$work/s0.log" | head -3; }
    [[ $r1 -eq 0 && -s "$work/s1.o" ]] || { fail "$name: stage1 rejected (rc=$r1)"; errors_of "$work/s1.log" | head -3; }
}

for fixture in "$DIR"/rejected/*.elisa; do
    check_rejected "$fixture"
done
for fixture in "$DIR"/accepted/*.elisa; do
    check_accepted "$fixture"
done

if [[ $failed -ne 0 ]]; then
    echo "lmut-call-aliasing: $failed of $count FAILED"
    exit 1
fi
echo "lmut-call-aliasing OK ($count fixtures agree with stage0)"
