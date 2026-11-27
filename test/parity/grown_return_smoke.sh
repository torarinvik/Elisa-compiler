#!/usr/bin/env bash
# `return xs.push(v)` from a function declared `-> darray[E]`, with `xs` a by-value darray
# (parameter or local), and the same call as a by-value initializer (`x: darray[E] = ...`). The in-place methods yield the receiver as `mutable darray[E]&`, so
# this copies out of a reference; stage0 rejects it ("return type expects darray[u8], got
# mutable darray[u8]&"). stage1 used to pass --check and then decline in the backend. Every
# in-place method must be rejected at check time, and the threaded spelling
# (`xs <- xs.push(v)` then `return xs`) must build and run.
#
# Usage: test/parity/grown_return_smoke.sh   (ELISAC overrides bin/elisac-stage1)
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISAC="${ELISAC:-$REPO_ROOT/bin/elisac-stage1}"
work="$(mktemp -d "${TMPDIR:-/tmp}/grown-return.XXXXXX")"
trap 'rm -rf "$work"' EXIT
fail() { echo "grown return smoke FAIL: $1" >&2; exit 1; }
expected='return type expects darray[u8], got mutable darray[u8]&'
for call in "push(0)" "extend(v)" "reserve(4)" "resize(4)" "clear()" "truncate(1)"; do
  for receiver in parameter local; do
    name="${call%%(*}_$receiver"
    if [ "$receiver" = parameter ]; then
      printf 'def f(xs: mutable darray[u8], v: darray[u8]&) -> darray[u8]:\n    return xs.%s\n' "$call" > "$work/$name.elisa"
    else
      printf 'def f(v: darray[u8]&) -> darray[u8]:\n    xs: mutable darray[u8] = []\n    return xs.%s\n' "$call" > "$work/$name.elisa"
    fi
    printf '\ndef main() -> i32:\n    return 0\n' >> "$work/$name.elisa"
    if "$ELISAC" -emit obj -o "$work/$name.o" "$work/$name.elisa" > "$work/$name.log" 2>&1; then
      fail "$name: returning the grown reference was accepted"
    fi
    grep -qF "$expected" "$work/$name.log" || fail "$name: wrong rejection: $(grep -v warning "$work/$name.log" | head -1)"
  done
done
# The same reference copied into a by-value initializer: a named local, a call result (bare
# and module-qualified), and a value block whose tail is the in-place call.
initializers=(
  "named_local|    local: mutable darray[u8] = []\n    copy: darray[u8] = local.push(1)\n    return copy.count.i64()\n|copy"
  "call_result|    copy: darray[u8] = make(3).push(10)\n    return copy.count.i64()\n|copy"
  "qualified_call|    copy: darray[u8] = Bytes::build(3).push(10)\n    return copy.count.i64()\n|copy"
  "block_tail|    target: darray[u8] =\n        buffer: mutable darray[u8] = []\n        buffer.push(1)\n        buffer.resize(n)\n    return target.count.i64()\n|target"
)
for entry in "${initializers[@]}"; do
  name="${entry%%|*}"; rest="${entry#*|}"; body="${rest%|*}"; variable="${rest##*|}"
  {
    printf 'def make(n: u8) -> darray[u8] can[Memory.Allocate]:\n    out: mutable darray[u8] = []\n    out.push(n)\n    return out\n\n'
    printf 'module Bytes:\n    public:\n        def build(n: u8) -> darray[u8] can[Memory.Allocate]:\n            out: mutable darray[u8] = []\n            out.push(n)\n            return out\n\n'
    printf 'def f(n: usize) -> i64 can[Memory.Allocate, Memory.Release]:\n'
    printf "$body"
    printf '\ndef main() -> i32:\n    return 0\n'
  } > "$work/$name.elisa"
  if "$ELISAC" -emit obj -o "$work/$name.o" "$work/$name.elisa" > "$work/$name.log" 2>&1; then
    fail "$name: copying the grown reference into a value was accepted"
  fi
  grep -qF "variable \"$variable\" expects darray[u8], got mutable darray[u8]&" "$work/$name.log" || fail "$name: wrong rejection: $(grep -v warning "$work/$name.log" | head -1)"
done
cat > "$work/threaded.elisa" <<'PROGRAM'
def with_field(queue: mutable darray[u8], value: darray[u8]&) -> darray[u8] can[Memory.Allocate]:
    for index in 0..<value.count |queue, value|:
        queue <- queue.push(value[index])
    queue <- queue.push(0)
    return queue

def main() -> i32 can[Memory.Allocate, Memory.Release]:
    value: darray[u8] = [4, 5]
    empty: mutable darray[u8] = []
    out: darray[u8] = with_field(empty, value)
    return out.count.i32() * 10 + out[1].i32()
PROGRAM
"$ELISAC" -emit obj -o "$work/threaded.o" "$work/threaded.elisa" > "$work/threaded.log" 2>&1 || fail "threaded form rejected: $(grep -v warning "$work/threaded.log" | head -1)"
cc "$work/threaded.o" "$REPO_ROOT/build/runtime/elisacore_runtime.o" -o "$work/threaded" || fail "threaded form does not link"
set +e; "$work/threaded"; status=$?; set -e
[ "$status" -eq 35 ] || fail "threaded form returned $status, expected 35"
echo "grown return smoke OK: 6 in-place methods x parameter/local returns and 4 initializer shapes rejected at check time, threaded form returns 35"
