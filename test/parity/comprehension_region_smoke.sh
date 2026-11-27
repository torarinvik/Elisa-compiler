#!/usr/bin/env bash
# A `[x for x in ...]` comprehension allocates a darray and takes its region from its
# destination, exactly like a container literal. stage0 rejects one with no destination
# ("comprehension has no region to allocate in; ..."); stage1 used to accept the by-value
# argument and decline in the backend for `&[...]` arguments, `for` iterables, receivers and
# generic arguments. Every rejected shape must report that sentence at check time, and the
# destination-bearing shapes (typed and inferred bindings, a struct field, a `region` block,
# `out.extend([...])` in the prelude's `fill`,
# an auto-wrapped body) must build, and an allocation-free `any ... where` query
# (the same AST node) must not be reported.
#
# Usage: test/parity/comprehension_region_smoke.sh   (ELISAC overrides bin/elisac-stage1)
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISAC="${ELISAC:-$REPO_ROOT/bin/elisac-stage1}"
work="$(mktemp -d "${TMPDIR:-/tmp}/comprehension-region.XXXXXX")"
trap 'rm -rf "$work"' EXIT
fail() { echo "comprehension region smoke FAIL: $1" >&2; exit 1; }
expected='comprehension has no region to allocate in; it takes one from its destination'
prelude='struct Holder:
    items: darray[i64]

def total(values: darray[i64]&) -> i64:
    sum: mutable i64 = 0
    for v in values |sum|:
        sum <- sum + v
    return sum

def take(values: darray[i64]) -> i64:
    return values.count.i64()

def fill(out: mutable darray[i64]&) -> void:
    out.extend([x.i64() for x in 0..<3])

def any_value[T](value: T) -> i64:
    return 1

module Sums:
    public:
        def total(values: darray[i64]&) -> i64:
            return values.count.i64()
'
write() { printf '%s\ndef main() -> i32:\n%s\n' "$prelude" "$2" > "$work/$1.elisa"; }
rejected=(
  "borrowed_argument|    return total(&[x.i64() for x in 0..<3]).i32()"
  "value_argument|    return take([x.i64() for x in 0..<3]).i32()"
  "parenthesized|    return take(([x.i64() for x in 0..<3])).i32()"
  "ternary_arm|    return take([x.i64() for x in 0..<3] if true else []).i32()"
  "qualified_callee|    return Sums::total(&[x.i64() for x in 0..<3]).i32()"
  "generic_argument|    return any_value([x.i64() for x in 0..<3]).i32()"
  "receiver|    return [x for x in 0..<3].count.i32()"
  "for_iterable|    sum: mutable i64 = 0\n    for v in [x.i64() for x in 0..<3] |sum|:\n        sum <- sum + v\n    return sum.i32()"
)
for entry in "${rejected[@]}"; do
  name="${entry%%|*}"; write "$name" "$(printf "${entry#*|}")"
  if "$ELISAC" -emit obj -o "$work/$name.o" "$work/$name.elisa" > "$work/$name.log" 2>&1; then
    fail "$name: a comprehension with no destination was accepted"
  fi
  grep -qF "$expected" "$work/$name.log" || fail "$name: wrong rejection: $(grep -v warning "$work/$name.log" | head -1)"
done
accepted=(
  "typed_binding|    xs: darray[i64] = [x.i64() for x in 0..<3]\n    return total(&xs).i32()"
  "inferred_binding|    xs = [x.i64() for x in 0..<3]\n    return xs.count.i32()"
  "struct_field|    h: Holder = Holder{items: [x.i64() for x in 0..<3]}\n    return h.items.count.i32()"
  "region_block|    region scratch(4096):\n        return take([x.i64() for x in 0..<3]).i32()"
  "query_argument|    xs: darray[i64] = [x.i64() for x in 0..<3]\n    return take(xs).i32() if (any v in xs where v == 2) else 0"
  "rebind_tuple|    rebind count: i64, items: darray[i64] =\n        2, [x.i64() for x in 0..<3]\n    return (count + items.count.i64()).i32()"
  "extend_argument|    return 0"
  "auto_wrapped|    acc: mutable darray[i64] = []\n    acc.push(1)\n    return take([x.i64() for x in 0..<3]).i32()"
)
for entry in "${accepted[@]}"; do
  name="${entry%%|*}"; write "$name" "$(printf "${entry#*|}")"
  "$ELISAC" -emit obj -o "$work/$name.o" "$work/$name.elisa" > "$work/$name.log" 2>&1 || fail "$name: rejected: $(grep -v warning "$work/$name.log" | head -1)"
done
echo "comprehension region smoke OK: ${#rejected[@]} destination-less shapes rejected at check time, ${#accepted[@]} destination shapes build"
