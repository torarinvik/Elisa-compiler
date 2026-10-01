#!/usr/bin/env bash
# PARAMETER-STORE ESCAPE THROUGH A LOCAL: a value carrying this frame's storage reaches
# parameter-owned storage via a local container, its elements, or an sview/struct local.
#
#   names: mutable darray[sview] = []; names.push("lit")
#   copies: darray[sview] = [n for n in names]      # derived: inherits names' LOCAL region
#   diags.push(D{name: copies[0]})                  # stage0: stored into "__rg_diags"
#
# stage0's element-provenance rule (region_local_container_elements.go): a push merges the
# pushed value's state; a comprehension over a local container, or a call result that received
# one, takes that container's local region whatever its elements; a ternary merges branches.
# stage1 accepted all of these (fp1n/psn/psn2/sfn/su5/su5n); it now mirrors the rule in
# src/semantic/check_handler_capture_escape.elisa.
#
#   1. every test/repro/param_store_escape/rejected/*.elisa is rejected by BOTH compilers with
#      no object written, and stage1's error lines (path stripped) equal stage0's exactly;
#   2. every accepted/*.elisa is accepted by both and both write a non-empty object.
#
# accepted/assignStore.elisa (`diags[0] <- D{name: names[0]}`) is a real escape stage0 accepts;
# it pins parity, not soundness.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
DIR="$ROOT/test/repro/param_store_escape"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}"

stage0="${ELISACORE_BIN:-$ELISA_CORE/compiler/bin/elisac}"
if [[ -z "${ELISACORE_BIN:-}" ]]; then
    mkdir -p "$(dirname "$stage0")"
    ( cd "$ELISA_CORE/compiler" && go build -o "$stage0" ./src ) || { echo "param-store-escape FAIL: cannot build stage0" >&2; exit 2; }
fi
[[ -x "$stage0" ]] || { echo "param-store-escape FAIL: missing stage0 at $stage0" >&2; exit 2; }
stage1=(bash "$ROOT/scripts/elisac_stage1.sh")

# stage0 writes a ZERO-BYTE object for a source under /private/tmp; keep outputs under /tmp.
work="$(mktemp -d /tmp/param_store_escape.XXXXXX)"
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
    echo "param-store-escape: $failed of $count FAILED"
    exit 1
fi
echo "param-store-escape OK ($count fixtures agree with stage0)"
