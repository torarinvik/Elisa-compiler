#!/usr/bin/env bash
# HANDLER-CAPTURE ESCAPE: a local owner's storage reaches a parameter through a filled container.
#
#   buf: darray[u8] = ...; captures: mutable darray[Prm] = []
#   rebind ok, parser = parser.parse_named(captures, buf.as_sview())   # fills captures from buf
#   for capture in captures: parser.params <- parser.params.push(capture)  # escapes buf
#
# stage0 (recordCallFilledElementStates / fillMayAdopt) rejects this with a RegionStoreEscape
# into "__rg_<param>"; stage1 accepted it and the parameter outlived the frame's buffer.
# stage1 now mirrors the rule in src/semantic/check_handler_capture_escape.elisa.
#
#   1. every test/repro/handler_capture_escape/rejected/*.elisa (and the older
#      handler_capture_local_escape.neg.elisa) is rejected by BOTH compilers with no object
#      written, and stage1's error lines (path stripped) equal stage0's exactly;
#   2. every accepted/*.elisa (and handler_capture_local_escape.pos.elisa) is accepted by both
#      and both write a non-empty object.
#
# A callee that may adopt (a void grower) still taints the filled container from a local
# owner argument, as stage0 merges every argument's element state (pr2/void2).
# Known, deliberately not covered: hc1p (stage0 lmut-alias rule).
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
DIR="$ROOT/test/repro/handler_capture_escape"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}"

stage0="${ELISACORE_BIN:-$ELISA_CORE/compiler/bin/elisac}"
if [[ -z "${ELISACORE_BIN:-}" ]]; then
    mkdir -p "$(dirname "$stage0")"
    ( cd "$ELISA_CORE/compiler" && go build -o "$stage0" ./src ) || { echo "handler-capture-escape FAIL: cannot build stage0" >&2; exit 2; }
fi
[[ -x "$stage0" ]] || { echo "handler-capture-escape FAIL: missing stage0 at $stage0" >&2; exit 2; }
stage1=(bash "$ROOT/scripts/elisac_stage1.sh")

# stage0 writes a ZERO-BYTE object for a source under /private/tmp; keep outputs under /tmp.
work="$(mktemp -d /tmp/handler_capture_escape.XXXXXX)"
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

for fixture in "$DIR"/rejected/*.elisa "$ROOT/test/repro/handler_capture_local_escape.neg.elisa"; do
    check_rejected "$fixture"
done
for fixture in "$DIR"/accepted/*.elisa "$ROOT/test/repro/handler_capture_local_escape.pos.elisa"; do
    check_accepted "$fixture"
done

if [[ $failed -ne 0 ]]; then
    echo "handler-capture-escape: $failed of $count FAILED"
    exit 1
fi
echo "handler-capture-escape OK ($count fixtures agree with stage0)"
