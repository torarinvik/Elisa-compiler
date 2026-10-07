#!/usr/bin/env bash
# BORROW EXCLUSIVITY: the audit probes in test/fixtures/borrow_exclusivity/, each with its
# expected stage1 outcome in its first line:
#
#   # expect: reject          stage1 refuses it and writes no object;
#   # expect: run N           it builds at -O0 and at -O2 -fnoalias and both exit N (an
#                             accepted program whose meaning `noalias` must not change);
#   # expect: accept ...      it builds (p29: Unsafe.PointerCast is out of scope).
#
# An optional `# message: TEXT` line requires TEXT in the rejection (the rewrite hint every
# new exclusivity diagnostic carries). The rules live in
# src/semantic/check_call_argument_exclusivity*.elisa; expected.tsv records the history.
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
DIR="$ROOT/test/fixtures/borrow_exclusivity"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
[[ -x "$STAGE1" ]] || { echo "borrow-exclusivity FAIL: missing stage1 at $STAGE1" >&2; exit 2; }

work="$(mktemp -d "${TMPDIR:-/tmp}/borrow_exclusivity.XXXXXX")"
trap 'rm -rf "$work"' EXIT INT TERM HUP
ulimit -c 0 || true
failed=0
count=0
fail() { echo "  FAIL $1"; failed=$((failed + 1)); }

for fixture in "$DIR"/p*.elisa; do
    name="$(basename "$fixture" .elisa)"
    expect="$(sed -n '1s/^# expect: *//p' "$fixture")"
    message="$(sed -n 's/^# message: *//p' "$fixture" | head -1)"
    count=$((count + 1))
    rm -f "$work/o0" "$work/o2"
    "$STAGE1" -emit exe -O0 -o "$work/o0" "$fixture" > "$work/log" 2>&1; rc=$?
    case "$expect" in
        reject)
            if [[ $rc -eq 0 || -s "$work/o0" ]]; then fail "$name: accepted, expected a rejection"; continue; fi
            if [[ -n "$message" ]] && ! grep -qF -- "$message" "$work/log"; then
                fail "$name: rejection lacks \"$message\""; grep -v 'warning:' "$work/log" | head -3 | sed 's/^/      /'
            fi ;;
        run\ *)
            want="${expect#run }"
            if [[ $rc -ne 0 ]]; then fail "$name: rejected, expected exit $want"; grep -v 'warning:' "$work/log" | head -3 | sed 's/^/      /'; continue; fi
            "$STAGE1" -emit exe -O2 -fnoalias -o "$work/o2" "$fixture" > "$work/log2" 2>&1 || { fail "$name: -O2 -fnoalias build failed"; continue; }
            "$work/o0"; got0=$?
            "$work/o2"; got2=$?
            [[ "$got0" == "$want" && "$got2" == "$want" ]] || fail "$name: exit -O0=$got0 -O2-fnoalias=$got2, expected $want" ;;
        accept*)
            [[ $rc -eq 0 ]] || { fail "$name: rejected, expected acceptance"; grep -v 'warning:' "$work/log" | head -3 | sed 's/^/      /'; } ;;
        *)
            fail "$name: no '# expect:' header" ;;
    esac
done

if [[ $failed -ne 0 ]]; then
    echo "borrow-exclusivity FAIL: $failed of $count probe(s)"
    exit 1
fi
echo "borrow-exclusivity OK: $count probes"
