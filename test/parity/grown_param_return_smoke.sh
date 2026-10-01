#!/usr/bin/env bash
# GROWN-PARAMETER RETURN: a by-ref (or lmut) region-less parameter that is grown in the body
# (`p.f.push(x)`, `buf.push(x)`, `p.f <- p.f.push(x)`) gets stage0's implicit region
# `__rg_<param>`; returning any borrow rooted at it -- the param, a field, a slice, an
# `as_sview()`, or a local alias -- with a region-less return type is rejected at the
# returned expression. A `view` return of `param[a:b]` with exactly one grown param is
# auto-stamped and accepted (bufslice). Growth inside `in X:` / `region:` does not count.
# Ported into src/semantic/check_region_tied_return.elisa (mw1/mw2).
#
#   1. rejected/*.elisa: both reject, no object, identical path-stripped errors;
#   2. accepted/*.elisa: both accept with a non-empty object.
#
# Not covered (stage1 deliberately stricter, pinned by sview_region_tie_smoke): returning a
# field borrow of an UNgrown by-ref param, which stage0 accepts. Also not covered: a
# conditional alias (`v = p.name if c else "x"`), which stage0 rejects under its separate
# scope-owned-region rule.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
DIR="$ROOT/test/repro/grown_param_return"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}"

stage0="${ELISACORE_BIN:-$ELISA_CORE/compiler/bin/elisac}"
if [[ -z "${ELISACORE_BIN:-}" ]]; then
    mkdir -p "$(dirname "$stage0")"
    ( cd "$ELISA_CORE/compiler" && go build -o "$stage0" ./src ) || { echo "grown-param-return FAIL: cannot build stage0" >&2; exit 2; }
fi
[[ -x "$stage0" ]] || { echo "grown-param-return FAIL: missing stage0 at $stage0" >&2; exit 2; }
stage1=(bash "$ROOT/scripts/elisac_stage1.sh")

# stage0 writes a ZERO-BYTE object for a source under /private/tmp; keep outputs under /tmp.
work="$(mktemp -d /tmp/grown_param_return.XXXXXX)"
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
    echo "grown-param-return: $failed of $count FAILED"
    exit 1
fi
echo "grown-param-return OK ($count fixtures agree with stage0)"
