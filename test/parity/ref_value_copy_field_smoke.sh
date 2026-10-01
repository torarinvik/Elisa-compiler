#!/usr/bin/env bash
# REF VALUE COPY INTO A STRUCT LITERAL FIELD (stage0 ce1n): with `r: T&` / `mutable T&` for a
# non-scalar T (struct, sview, darray, ...), `H{xs: r}` where field `xs` is declared `T` copies
# the pointee and stage0 refuses it: struct literal field "xs" expects T, got [mutable ]T&.
# Scalar pointees auto-dereference and are accepted. Ported into
# src/semantic/check_ref_value_copy.elisa (RefValueCopy form 4).
#
#   1. rejected/*.elisa: both reject, no object, identical path-stripped errors;
#   2. accepted/*.elisa: both accept with a non-empty object.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
DIR="$ROOT/test/repro/ref_value_copy_field"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}"

stage0="${ELISACORE_BIN:-$ELISA_CORE/compiler/bin/elisac}"
if [[ -z "${ELISACORE_BIN:-}" ]]; then
    mkdir -p "$(dirname "$stage0")"
    ( cd "$ELISA_CORE/compiler" && go build -o "$stage0" ./src ) || { echo "ref-value-copy-field FAIL: cannot build stage0" >&2; exit 2; }
fi
[[ -x "$stage0" ]] || { echo "ref-value-copy-field FAIL: missing stage0 at $stage0" >&2; exit 2; }
stage1=(bash "$ROOT/scripts/elisac_stage1.sh")

# stage0 writes a ZERO-BYTE object for a source under /private/tmp; keep outputs under /tmp.
work="$(mktemp -d /tmp/ref_value_copy_field.XXXXXX)"
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
    echo "ref-value-copy-field: $failed of $count FAILED"
    exit 1
fi
echo "ref-value-copy-field OK ($count fixtures agree with stage0)"
