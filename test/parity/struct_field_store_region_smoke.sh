#!/usr/bin/env bash
# A struct holding darrays stored into a field reached through a `mutable T&` parameter
# (`game.desk <- start(seed)`) must be built in the CALLER's region: the storing function
# takes the caller's region as a hidden parameter and frees no region of its own. A dangling
# read does not reliably fail at run time (a freed block keeps its bytes unless reused), so
# the IR is checked first; the fixture then runs and must exit 0.
#
# Usage: test/parity/struct_field_store_region_smoke.sh   (ELISAC overrides bin/elisac-stage1)
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISAC="${ELISAC:-$REPO_ROOT/bin/elisac-stage1}"
FIXTURE="$REPO_ROOT/test/repro/struct_field_store_through_ref.elisa"
work="$(mktemp -d "${TMPDIR:-/tmp}/struct-field-store-region.XXXXXX")"
trap 'rm -rf "$work"' EXIT

fail() { echo "struct field store region smoke FAIL: $1" >&2; exit 1; }
"$ELISAC" -emit llvm -o "$work/fixture.ll" "$FIXTURE" > /dev/null 2>&1 || fail "fixture does not compile to IR"
for function in reset_direct reset_through_named_deal; do
  body="$(awk "/^define .*@$function\\(/,/^}/" "$work/fixture.ll")"
  [ -n "$body" ] || fail "@$function not emitted"
  grep -q "^define .*@$function(ptr %0, ptr %1)" <<< "$body" || fail "@$function does not take the caller's region: $(head -1 <<< "$body")"
  ! grep -q 'arena_free' <<< "$body" || fail "@$function frees a region of its own"
done
"$ELISAC" -emit obj -o "$work/fixture.o" "$FIXTURE" > /dev/null 2>&1 || fail "fixture does not compile"
cc "$work/fixture.o" "$REPO_ROOT/build/runtime/elisacore_runtime.o" -o "$work/fixture" || fail "fixture does not link"
"$work/fixture" || fail "fixture exited $?"
echo "struct field store region smoke OK: storing functions take the caller's region, fixture exits 0"
