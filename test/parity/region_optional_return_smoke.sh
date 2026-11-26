#!/usr/bin/env bash
# An Optional container returned out of a `region` block dangles: the block frees the region on
# exit. Every spelling must be rejected:
#   return failure(code)                       direct call
#   found = get failure(code) else return null `get` unwrap
#   found: darray[u8]? = failure(code)         Optional local
#   if failure(code) is found: return found    condition binder
# Without the region block the same function is sound, and it must run and return the byte.
#
# Usage: test/parity/region_optional_return_smoke.sh   (ELISAC overrides bin/elisac-stage1)
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISAC="${ELISAC:-$REPO_ROOT/bin/elisac-stage1}"
work="$(mktemp -d "${TMPDIR:-/tmp}/region-optional-return.XXXXXX")"
trap 'rm -rf "$work"' EXIT
fail() { echo "region optional return smoke FAIL: $1" >&2; exit 1; }

# program NAME OPENER BODY: OPENER is "region scope:" or "if true:".
program() {
  printf 'def failure(code: u8) -> darray[u8]? can[Memory.Allocate]:\n    out: mutable darray[u8] = []\n    out.push(code)\n    return out\n\n' > "$work/$1.elisa"
  printf 'def verify(code: u8) -> darray[u8]? can[Memory.Allocate, Memory.Release]:\n    %s\n%s    return null\n\n' "$2" "$3" >> "$work/$1.elisa"
  printf 'def main() -> i32 can[Memory.Allocate, Memory.Release]:\n    if verify(5) is r:\n        return r.count.i32() * 10 + r[0].i32()\n    return 99\n' >> "$work/$1.elisa"
}
spellings=(
  "direct|        return failure(code)\n"
  "get_else|        found = get failure(code) else return null\n        return found\n"
  "optional_local|        found: darray[u8]? = failure(code)\n        return found\n"
  "condition_binder|        if failure(code) is found:\n            return found\n"
)
for entry in "${spellings[@]}"; do
  name="${entry%%|*}"; body="$(printf "${entry#*|}")"$'\n'
  program "$name" "region scope:" "$body"
  if "$ELISAC" -emit obj -o "$work/$name.o" "$work/$name.elisa" > "$work/$name.log" 2>&1; then
    fail "$name: returning out of the region block was accepted"
  fi
  grep -q 'escapes via return' "$work/$name.log" || fail "$name: wrong rejection: $(grep -v warning "$work/$name.log" | head -1)"
done
program plain "if true:" "$(printf '        if failure(code) is found:\n            return found\n')"$'\n'
"$ELISAC" -emit obj -o "$work/plain.o" "$work/plain.elisa" > "$work/plain.log" 2>&1 || fail "region-free form rejected: $(grep -v warning "$work/plain.log" | head -1)"
cc "$work/plain.o" "$REPO_ROOT/build/runtime/elisacore_runtime.o" -o "$work/plain" || fail "region-free form does not link"
set +e; "$work/plain"; status=$?; set -e
[ "$status" -eq 15 ] || fail "region-free form returned $status, want 15"
echo "region optional return smoke OK: 4 escaping spellings rejected, region-free form returns the byte"
