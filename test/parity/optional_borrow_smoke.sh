#!/usr/bin/env bash
# Optional borrows (`T&?`): growth through a narrowed optional borrow parameter lands in the
# caller's region (the fixture runs and must exit 0), and the reversed suffix `T?&` is
# rejected with a message that names the `&?` spelling.
#
# Usage: test/parity/optional_borrow_smoke.sh   (ELISAC overrides bin/elisac-stage1)
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISAC="${ELISAC:-$REPO_ROOT/bin/elisac-stage1}"
FIXTURE="$REPO_ROOT/test/repro/optional_borrow_growth.elisa"
work="$(mktemp -d "${TMPDIR:-/tmp}/optional-borrow.XXXXXX")"
trap 'rm -rf "$work"' EXIT

fail() { echo "optional borrow smoke FAIL: $1" >&2; exit 1; }
"$ELISAC" -emit obj -o "$work/fixture.o" "$FIXTURE" > /dev/null 2>&1 || fail "fixture does not compile"
cc "$work/fixture.o" "$REPO_ROOT/build/runtime/elisacore_runtime.o" -o "$work/fixture" || fail "fixture does not link"
"$work/fixture" || fail "fixture exited $?"
printf 'def count(edges: darray[usize]?&) -> usize:\n    0\n' > "$work/order.elisa"
if "$ELISAC" -emit obj -o "$work/order.o" "$work/order.elisa" > "$work/order.log" 2>&1; then
  fail "\`T?&\` was accepted"
fi
grep -q 'write `&?` for an optional borrow' "$work/order.log" || fail "\`T?&\` error does not name \`&?\`: $(head -1 "$work/order.log")"
echo "optional borrow smoke OK: growth lands in the caller's region, \`T?&\` names \`&?\`"
